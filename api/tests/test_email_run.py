"""Tests for POST /invoice-sources/runs/{run_id}/email."""

import base64
import json
import sys
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
    from vibe_accountant.models import Base, Document, InvoiceFetchRun, InvoiceSource
    from vibe_accountant.routes import invoice_sources
    from vibe_accountant.services import gmail_fetcher

    Base.metadata.create_all(engine)
    app.dependency_overrides[get_current_user] = lambda: "test"

    sent: list[dict] = []
    monkeypatch.setattr(gmail_fetcher, "_service", lambda token_json: StubService(sent))
    monkeypatch.setattr(invoice_sources.s3, "download_document", lambda key: b"%PDF-" + key.encode())

    db = SessionLocal()
    src = InvoiceSource(name="Hetzner", kind="website")
    db.add(src)
    db.flush()
    run = InvoiceFetchRun(source_id=src.id, status="completed")
    db.add(run)
    db.flush()
    for i in range(2):
        db.add(Document(
            filename=f"inv{i}.pdf", s3_key=f"documents/{i}.pdf", content_type="application/pdf",
            file_size=5, doc_type="purchase_invoice", run_id=run.id, source_id=src.id,
        ))
    db.commit()
    run_id = run.id
    db.close()

    yield {
        "client": TestClient(app),
        "SessionLocal": SessionLocal,
        "run_id": run_id,
        "sent": sent,
        "InvoiceSource": InvoiceSource,
    }
    app.dependency_overrides.clear()
    engine.dispose()


def _add_gmail(env, name, token):
    db = env["SessionLocal"]()
    db.add(env["InvoiceSource"](name=name, kind="gmail", gmail_token=token, gmail_email=f"{name}@x"))
    db.commit()
    db.close()


def test_sends_all_run_documents_and_remembers_recipient(env):
    _add_gmail(env, "work", _token(READ, SEND))
    r = env["client"].post(f"/invoice-sources/runs/{env['run_id']}/email", json={"to": "me@example.com"})
    assert r.status_code == 200, r.text
    assert r.json()["detail"] == "Sent 2 document(s) to me@example.com in 1 email(s)"

    assert len(env["sent"]) == 1
    msg = message_from_bytes(base64.urlsafe_b64decode(env["sent"][0]["raw"]))
    assert msg["To"] == "me@example.com"
    assert msg["Subject"].startswith("Invoices: Hetzner")
    attachments = [p for p in msg.walk() if p.get_filename()]
    assert [p.get_filename() for p in attachments] == ["inv0.pdf", "inv1.pdf"]
    assert attachments[0].get_payload(decode=True) == b"%PDF-documents/0.pdf"

    assert env["client"].get("/invoice-sources/email/recipient").json() == {
        "to": "me@example.com", "sender": "work@x", "reconnect": None,
    }


def test_emails_several_runs_at_once(env):
    _add_gmail(env, "work", _token(READ, SEND))
    from vibe_accountant.models import Document, InvoiceFetchRun

    db = env["SessionLocal"]()
    other = InvoiceFetchRun(source_id=1, status="completed")
    db.add(other)
    db.flush()
    db.add(Document(
        filename="other.pdf", s3_key="documents/other.pdf", content_type="application/pdf",
        file_size=5, doc_type="purchase_invoice", run_id=other.id, source_id=1,
    ))
    db.commit()
    other_id = other.id
    db.close()

    r = env["client"].post(
        "/invoice-sources/runs/email",
        json={"to": "me@example.com", "run_ids": [env["run_id"], other_id], "label": "Q3 2026"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["detail"] == "Sent 3 document(s) to me@example.com in 1 email(s)"
    msg = message_from_bytes(base64.urlsafe_b64decode(env["sent"][0]["raw"]))
    assert msg["Subject"] == "Invoices: Q3 2026"
    assert [p.get_filename() for p in msg.walk() if p.get_filename()] == ["inv0.pdf", "inv1.pdf", "other.pdf"]

    r = env["client"].post("/invoice-sources/runs/email", json={"to": "me@example.com", "run_ids": [999], "label": "x"})
    assert r.status_code == 400


def test_requires_gmail_source_with_send_permission(env):
    r = env["client"].post(f"/invoice-sources/runs/{env['run_id']}/email", json={"to": "me@example.com"})
    assert r.status_code == 400
    assert "Connect a Gmail source" in r.json()["detail"]

    _add_gmail(env, "old", _token(READ))
    r = env["client"].post(f"/invoice-sources/runs/{env['run_id']}/email", json={"to": "me@example.com"})
    assert r.status_code == 400
    assert "Reconnect Gmail on 'old'" in r.json()["detail"]
    assert env["sent"] == []


def test_rejects_bad_address_and_missing_run(env):
    _add_gmail(env, "work", _token(READ, SEND))
    r = env["client"].post(f"/invoice-sources/runs/{env['run_id']}/email", json={"to": "nope"})
    assert r.status_code == 400
    r = env["client"].post("/invoice-sources/runs/999/email", json={"to": "me@example.com"})
    assert r.status_code == 404


def test_splits_large_runs_into_several_emails(monkeypatch):
    _purge_modules()
    from vibe_accountant.services import gmail_fetcher

    sent: list[dict] = []
    monkeypatch.setattr(gmail_fetcher, "_service", lambda token_json: StubService(sent))
    monkeypatch.setattr(gmail_fetcher, "MAX_ATTACHMENTS_BYTES", 10)
    files = [
        ("a.pdf", b"123456", "application/pdf"),
        ("b.pdf", b"123456", "application/pdf"),
        ("c.pdf", b"1", "application/pdf"),
    ]
    assert gmail_fetcher.send_files(_token(SEND), "me@example.com", "Invoices", "body", files) == 2
    subjects = [message_from_bytes(base64.urlsafe_b64decode(b["raw"]))["Subject"] for b in sent]
    assert subjects == ["Invoices (1/2)", "Invoices (2/2)"]


def test_recipient_can_be_saved_without_sending(env):
    assert env["client"].get("/invoice-sources/email/recipient").json()["to"] is None
    r = env["client"].put("/invoice-sources/email/recipient", json={"to": " books@example.com "})
    assert r.status_code == 200
    assert r.json() == {"to": "books@example.com"}
    assert env["client"].get("/invoice-sources/email/recipient").json()["to"] == "books@example.com"
    assert env["client"].put("/invoice-sources/email/recipient", json={"to": "nope"}).status_code == 400


def test_recipient_status_points_at_source_needing_reconnect(env):
    _add_gmail(env, "old", _token(READ))
    status = env["client"].get("/invoice-sources/email/recipient").json()
    assert status["sender"] is None
    assert status["reconnect"]["name"] == "old"
    src = next(s for s in env["client"].get("/invoice-sources").json() if s["name"] == "old")
    assert src["gmail_connected"] is True
    assert src["gmail_can_send"] is False

    _add_gmail(env, "work", _token(READ, SEND))
    status = env["client"].get("/invoice-sources/email/recipient").json()
    assert status["sender"] == "work@x"
    assert status["reconnect"] is None
