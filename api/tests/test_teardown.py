"""Tests for POST /setup/teardown."""

import sys
from datetime import datetime

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fresh app wired to a temporary SQLite database and bunq context directory."""
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("BUNQ_CONF_DIR", str(conf_dir))

    # Settings and the engine are created at import time, so drop any cached modules first
    for name in list(sys.modules):
        if name.startswith("vibe_accountant"):
            del sys.modules[name]

    from vibe_accountant.auth import get_current_user
    from vibe_accountant.database import SessionLocal, engine
    from vibe_accountant.main import app
    from vibe_accountant.models import Account, Base, Integration, Transaction
    from vibe_accountant.routes import setup

    Base.metadata.create_all(engine)
    app.dependency_overrides[get_current_user] = lambda: "test"
    monkeypatch.setattr(setup, "verify_passkey_assertion", lambda db, body, key: None)

    class StubApiContext:
        @staticmethod
        def restore(path):
            raise RuntimeError("bunq unreachable")

    monkeypatch.setattr(setup, "ApiContext", StubApiContext)

    db = SessionLocal()
    integration = Integration(name="main", secret_key="secret")
    db.add(integration)
    db.flush()
    account = Account(name="Checking", integration_id=integration.id)
    db.add(account)
    db.flush()
    for i in range(2):
        db.add(Transaction(account_id=account.id, amount=10 + i, transaction_date=datetime(2026, 1, 1)))
    db.commit()
    db.close()

    (conf_dir / "main.conf").write_text("{}")
    (conf_dir / "orphan.conf").write_text("{}")

    yield {
        "client": TestClient(app),
        "SessionLocal": SessionLocal,
        "conf_dir": conf_dir,
        "models": (Integration, Account, Transaction),
    }
    app.dependency_overrides.clear()
    engine.dispose()


PASSKEY = {"id": "x", "rawId": "eA", "type": "public-key", "response": {}}


def test_teardown_wipes_bunq_state(env):
    Integration, Account, Transaction = env["models"]
    response = env["client"].post(
        "/setup/teardown", json={"confirmation": "TEARDOWN", "passkey": PASSKEY}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "integrations": 1,
        "accounts": 1,
        "transactions": 2,
        "context_files": 2,
    }

    db = env["SessionLocal"]()
    assert db.query(Transaction).count() == 0
    assert db.query(Account).count() == 0
    assert db.query(Integration).count() == 0
    db.close()
    assert list(env["conf_dir"].glob("*.conf")) == []


def test_teardown_rejects_wrong_phrase(env):
    Integration, Account, Transaction = env["models"]
    response = env["client"].post(
        "/setup/teardown", json={"confirmation": "teardown", "passkey": PASSKEY}
    )
    assert response.status_code == 400

    db = env["SessionLocal"]()
    assert db.query(Transaction).count() == 2
    assert db.query(Integration).count() == 1
    db.close()
    assert len(list(env["conf_dir"].glob("*.conf"))) == 2
