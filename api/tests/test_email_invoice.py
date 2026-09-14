"""Tests for POST /invoices/{invoice_id}/email."""

import base64
import json
import sys
from datetime import date
from decimal import Decimal
from email import message_from_bytes

import pytest
from fastapi.testclient import TestClient

READ = "https://www.googleapis.com/auth/gmail.readonly"
SEND = "https://www.googleapis.com/auth/gmail.send"


def _token(*scopes: str) -> str:
    return json.dumps({"token": "t", "refresh_token": "r", "scopes": list(scopes)})


class StubService:
    """Records Gmail send calls."""

    def __init__(self, sent: list):
        self.sent = sent

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        self.sent.append(body)
        return self

    def execute(self):
        return {}


def _purge_modules():
    for name in list(sys.modules):
        if name.startswith("vibe_accountant"):
            del sys.modules[name]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    _purge_modules()

    from vibe_accountant.auth import get_current_user
    from vibe_accountant.database import SessionLocal, engine
    from vibe_accountant.main import app
    from vibe_accountant.models import (
        Base,
        Client,
        CompanySettings,
        Invoice,
        InvoiceItem,
        InvoiceSource,
    )
    from vibe_accountant.services import gmail_fetcher

    Base.metadata.create_all(engine)
    app.dependency_overrides[get_current_user] = lambda: "test"

    sent: list[dict] = []
    monkeypatch.setattr(gmail_fetcher, "_service", lambda token_json: StubService(sent))

    db = SessionLocal()
    db.add(CompanySettings(name="Neuroship"))
    client = Client(name="ACME")
    db.add(client)
    db.flush()
    inv = Invoice(
        client_id=client.id,
        invoice_number="2026-001",
        invoice_date=date(2026, 9, 1),
        due_date=date(2026, 10, 1),
        subtotal=Decimal("100"),
        vat_amount=Decimal("21"),
        total_amount=Decimal("121"),
    )
    db.add(inv)
    db.flush()
    db.add(
        InvoiceItem(
            invoice_id=inv.id,
            description="Work",
            quantity=Decimal("1"),
            unit_price=Decimal("100"),
            vat_rate=Decimal("21"),
            line_total=Decimal("100"),
        )
    )
    db.commit()
    invoice_id = inv.id
    db.close()

    yield {
        "client": TestClient(app),
        "SessionLocal": SessionLocal,
        "invoice_id": invoice_id,
        "sent": sent,
        "InvoiceSource": InvoiceSource,
    }
    app.dependency_overrides.clear()
    engine.dispose()


def _add_gmail(env, name, token):
    db = env["SessionLocal"]()
    db.add(
        env["InvoiceSource"](name=name, kind="gmail", gmail_token=token, gmail_email=f"{name}@x")
    )
    db.commit()
    db.close()


def test_sends_pdf_and_remembers_recipient(env):
    _add_gmail(env, "work", _token(READ, SEND))
    r = env["client"].post(f"/invoices/{env['invoice_id']}/email", json={"to": "books@example.com"})
    assert r.status_code == 200, r.text
    assert r.json()["detail"] == "Sent 2026-001.pdf to books@example.com"

    msg = message_from_bytes(base64.urlsafe_b64decode(env["sent"][0]["raw"]))
    assert msg["To"] == "books@example.com"
    assert msg["Subject"] == "Invoice 2026-001 from Neuroship"
    attachments = [p for p in msg.walk() if p.get_filename()]
    assert [p.get_filename() for p in attachments] == ["2026-001.pdf"]
    assert attachments[0].get_payload(decode=True).startswith(b"%PDF-")

    # Same remembered address as the auto-fetch run email
    assert env["client"].get("/invoice-sources/email/recipient").json()["to"] == "books@example.com"


def test_requires_send_permission_and_valid_input(env):
    r = env["client"].post(f"/invoices/{env['invoice_id']}/email", json={"to": "books@example.com"})
    assert r.status_code == 400
    assert "Connect a Gmail source" in r.json()["detail"]

    _add_gmail(env, "old", _token(READ))
    r = env["client"].post(f"/invoices/{env['invoice_id']}/email", json={"to": "books@example.com"})
    assert r.status_code == 400
    assert "Reconnect Gmail on 'old'" in r.json()["detail"]

    _add_gmail(env, "work", _token(READ, SEND))
    assert (
        env["client"].post(f"/invoices/{env['invoice_id']}/email", json={"to": "nope"}).status_code
        == 400
    )
    assert (
        env["client"].post("/invoices/999/email", json={"to": "books@example.com"}).status_code
        == 404
    )
    assert env["sent"] == []
