"""Tests for linking documents to transactions without over-matching."""

import sys
from datetime import date, datetime
from decimal import Decimal

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    for name in list(sys.modules):
        if name.startswith("vibe_accountant"):
            del sys.modules[name]

    from vibe_accountant.database import SessionLocal, engine
    from vibe_accountant.models import Base

    Base.metadata.create_all(engine)
    session = SessionLocal()
    yield session
    session.close()


def _account(db):
    from vibe_accountant.models import Account, Integration

    integration = Integration(name="bunq", secret_key="x")
    db.add(integration)
    db.flush()
    account = Account(name="Main", integration_id=integration.id)
    db.add(account)
    db.flush()
    return account


def _doc(db, **kw):
    from vibe_accountant.models import Document

    defaults = dict(
        filename="inv.pdf", s3_key=f"k{kw.get('invoice_number', 'x')}", content_type="application/pdf",
        file_size=1, doc_type="purchase_invoice", status="completed", vendor_name="KPN B.V.",
        invoice_number="11403438419", invoice_date=date(2026, 8, 4), total_amount=Decimal("67.40"),
    )
    defaults.update(kw)
    doc = Document(**defaults)
    db.add(doc)
    db.flush()
    return doc


def _txn(db, account, amount, day, description="Factuur, klantnummer 40104592219", counterparty="KPN B.V."):
    from vibe_accountant.models import Transaction

    txn = Transaction(
        account_id=account.id, amount=Decimal(amount), description=description,
        counterparty_name=counterparty, transaction_date=datetime.combine(day, datetime.min.time()),
    )
    db.add(txn)
    db.flush()
    return txn


def _links(db):
    from vibe_accountant.models import Transaction

    return {t.id: t.document_id for t in db.query(Transaction).all() if t.document_id}


def test_customer_number_reference_does_not_link_every_month(db):
    """A 'payment reference' that is really a customer number must not sweep up all transactions."""
    from vibe_accountant.services import match_documents_to_transactions

    acc = _account(db)
    doc = _doc(db, payment_reference="40104592219", total_amount=Decimal("66.57"), invoice_date=date(2026, 1, 2))
    months = [_txn(db, acc, "-39.29", date(2025, m, 10)) for m in (6, 7, 8, 9, 10, 11)]
    right = _txn(db, acc, "-66.57", date(2026, 1, 9))
    db.commit()

    report = match_documents_to_transactions(db)
    assert report.matched == 1
    assert _links(db) == {right.id: doc.id}
    assert all(t.document_id is None for t in months)


def test_reference_matches_whole_token_only(db):
    from vibe_accountant.services import match_documents_to_transactions

    acc = _account(db)
    doc = _doc(db, invoice_number="123456", total_amount=None)
    _txn(db, acc, "-10.00", date(2026, 8, 6), description="ref 9912345678")
    hit = _txn(db, acc, "-10.00", date(2026, 8, 7), description="ref 123456 paid")
    db.commit()

    report = match_documents_to_transactions(db)
    assert report.matched == 1
    assert _links(db) == {hit.id: doc.id}


def test_identical_monthly_amounts_link_by_date(db):
    """Three invoices of 67.40 and three payments of 67.40: each goes to its own month."""
    from vibe_accountant.services import match_documents_to_transactions

    acc = _account(db)
    docs = [
        _doc(db, invoice_number=f"1140000{i}", invoice_date=date(2026, m, 4), s3_key=f"s{i}")
        for i, m in enumerate((6, 7, 8))
    ]
    txns = [_txn(db, acc, "-67.40", date(2026, m, 11)) for m in (6, 7, 8)]
    db.commit()

    report = match_documents_to_transactions(db)
    assert report.matched == 3
    assert _links(db) == {t.id: d.id for t, d in zip(txns, docs)}


def test_two_close_candidates_are_reported_not_guessed(db):
    from vibe_accountant.services import match_documents_to_transactions

    acc = _account(db)
    doc = _doc(db)
    a = _txn(db, acc, "-67.40", date(2026, 8, 10))
    b = _txn(db, acc, "-67.40", date(2026, 8, 12))
    db.commit()

    report = match_documents_to_transactions(db)
    assert report.matched == 0
    assert _links(db) == {}
    assert len(report.ambiguous) == 1
    assert {c.txn.id for c in report.ambiguous[0].candidates} == {a.id, b.id}
    assert report.as_dict()["ambiguous"][0]["document_id"] == doc.id


def test_purchase_invoice_ignores_incoming_money(db):
    from vibe_accountant.services import match_documents_to_transactions

    acc = _account(db)
    _doc(db)
    _txn(db, acc, "67.40", date(2026, 8, 10))
    db.commit()

    assert match_documents_to_transactions(db).matched == 0
    assert _links(db) == {}


def test_amount_match_outside_date_window_is_ignored(db):
    from vibe_accountant.services import match_documents_to_transactions

    acc = _account(db)
    _doc(db, invoice_date=date(2026, 6, 4))
    _txn(db, acc, "-67.40", date(2025, 10, 9))
    db.commit()

    assert match_documents_to_transactions(db).matched == 0


def test_one_transaction_never_serves_two_documents(db):
    from vibe_accountant.services import match_documents_to_transactions

    acc = _account(db)
    _doc(db, invoice_number="1", s3_key="a")
    _doc(db, invoice_number="2", s3_key="b")
    _txn(db, acc, "-67.40", date(2026, 8, 10))
    db.commit()

    report = match_documents_to_transactions(db)
    assert report.matched == 1
    assert len(_links(db)) == 1


def test_suggestions_flag_ambiguous_groups(db):
    from vibe_accountant.services import find_match_suggestions

    acc = _account(db)
    doc = _doc(db)
    _txn(db, acc, "-67.40", date(2026, 8, 10))
    _txn(db, acc, "-67.40", date(2026, 8, 12))
    db.commit()

    sugg = find_match_suggestions(db)
    assert len(sugg) == 2
    assert {s["match_type"] for s in sugg} == {"ambiguous"}
    assert all(s["document_id"] == doc.id and s["candidates"] == 2 for s in sugg)


def test_repair_unlinks_rule_breaking_links_and_rematches(db):
    from vibe_accountant.services import match_documents_to_transactions
    from vibe_accountant.services.document_matcher import find_bad_links, unlink_bad_links

    acc = _account(db)
    doc = _doc(db)
    wrong_amount = _txn(db, acc, "-39.29", date(2026, 8, 10))
    far_away = _txn(db, acc, "-67.40", date(2025, 1, 10))
    right = _txn(db, acc, "-67.40", date(2026, 8, 11))
    wrong_amount.document_id = doc.id
    far_away.document_id = doc.id
    db.commit()

    reasons = {t.id: why for t, _, why in find_bad_links(db)}
    assert set(reasons) == {wrong_amount.id, far_away.id}
    assert unlink_bad_links(db) == 2
    match_documents_to_transactions(db)
    assert _links(db) == {right.id: doc.id}
