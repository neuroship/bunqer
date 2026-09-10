"""Tests for marking invoices paid from matching transactions."""

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


def _seed(db, description, amount="121.00", txn_date=datetime(2026, 9, 5), status="sent"):
    from vibe_accountant.models import Account, Client, Integration, Invoice, Transaction

    integration = Integration(name="bunq", secret_key="x")
    db.add(integration)
    db.flush()
    account = Account(name="Main", integration_id=integration.id)
    client = Client(name="ACME")
    db.add_all([account, client])
    db.flush()
    invoice = Invoice(
        client_id=client.id,
        invoice_number="INV-2026-001",
        invoice_date=date(2026, 9, 1),
        due_date=date(2026, 10, 1),
        status=status,
        total_amount=Decimal("121.00"),
    )
    txn = Transaction(
        account_id=account.id,
        amount=Decimal(amount),
        description=description,
        transaction_date=txn_date,
    )
    db.add_all([invoice, txn])
    db.commit()
    return invoice


def test_marks_paid_when_number_in_description(db):
    from vibe_accountant.services import match_invoices_to_transactions

    invoice = _seed(db, "Payment for inv-2026-001 thanks")
    paid = match_invoices_to_transactions(db)
    assert [i.id for i in paid] == [invoice.id]
    db.refresh(invoice)
    assert invoice.status == "paid"


def test_ignores_outgoing_and_unrelated(db):
    from vibe_accountant.services import match_invoices_to_transactions

    invoice = _seed(db, "INV-2026-001 refund", amount="-121.00")
    assert match_invoices_to_transactions(db) == []
    db.refresh(invoice)
    assert invoice.status == "sent"


def test_ignores_transactions_before_invoice_date(db):
    from vibe_accountant.services import match_invoices_to_transactions

    invoice = _seed(db, "INV-2026-001", txn_date=datetime(2026, 8, 30))
    assert match_invoices_to_transactions(db) == []
    db.refresh(invoice)
    assert invoice.status == "sent"


def test_skips_already_paid(db):
    from vibe_accountant.services import match_invoices_to_transactions

    _seed(db, "INV-2026-001", status="cancelled")
    assert match_invoices_to_transactions(db) == []


def test_matches_by_exact_amount_when_no_reference(db):
    from vibe_accountant.services import match_invoices_to_transactions

    invoice = _seed(db, "Bank transfer")
    paid = match_invoices_to_transactions(db)
    assert [i.id for i in paid] == [invoice.id]
    db.refresh(invoice)
    assert invoice.status == "paid"


def test_amount_must_match_exactly(db):
    from vibe_accountant.services import match_invoices_to_transactions

    invoice = _seed(db, "Bank transfer", amount="121.01")
    assert match_invoices_to_transactions(db) == []
    db.refresh(invoice)
    assert invoice.status == "sent"


def test_one_transaction_pays_one_invoice(db):
    from vibe_accountant.models import Invoice
    from vibe_accountant.services import match_invoices_to_transactions

    first = _seed(db, "Bank transfer")
    second = Invoice(
        client_id=first.client_id,
        invoice_number="INV-2026-002",
        invoice_date=date(2026, 9, 1),
        due_date=date(2026, 10, 1),
        status="sent",
        total_amount=Decimal("121.00"),
    )
    db.add(second)
    db.commit()

    paid = match_invoices_to_transactions(db)
    assert len(paid) == 1
    db.refresh(second)
    assert second.status == "sent"
