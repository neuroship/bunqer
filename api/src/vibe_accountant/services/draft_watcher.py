"""Background watcher for bunq draft payments awaiting approval."""

import asyncio
import threading
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from ..bunq_client import BunqClient
from ..database import SessionLocal
from ..logger import logger
from ..models import Account, Integration
from ..routes.events import broadcast_event

POLL_INTERVAL_SECONDS = 60

_lock = threading.Lock()
_pending: list[dict[str, Any]] | None = None  # None until the first successful poll


def _summarize(draft: dict[str, Any], account: Account) -> dict[str, Any]:
    entries = draft.get("entries") or []
    first = entries[0] if entries else {}
    counterparty = first.get("counterparty_alias") or {}
    label = counterparty.get("label_monetary_account") or counterparty
    total = sum(Decimal((e.get("amount") or {}).get("value") or "0") for e in entries)
    return {
        "id": draft.get("id"),
        "account_id": account.id,
        "account_name": account.name,
        "status": draft.get("status"),
        "created": draft.get("created"),
        "updated": draft.get("updated"),
        "amount": f"{total:.2f}",
        "currency": (first.get("amount") or {}).get("currency"),
        "counterparty_name": label.get("display_name")
        or (label.get("label_user") or {}).get("display_name"),
        "counterparty_iban": label.get("iban"),
        "description": first.get("description"),
        "entry_count": len(entries),
        "created_by": (draft.get("user_alias_created") or {}).get("display_name"),
    }


def fetch_pending_drafts(db: Session) -> list[dict[str, Any]]:
    """List PENDING draft payments across all bunq-linked accounts, newest first."""
    accounts = db.query(Account).filter(Account.monetary_account_id.isnot(None)).all()
    by_integration: dict[int, list[Account]] = {}
    for account in accounts:
        by_integration.setdefault(account.integration_id, []).append(account)

    drafts: list[dict[str, Any]] = []
    for integration_id, accts in by_integration.items():
        integration = db.query(Integration).filter(Integration.id == integration_id).first()
        if not integration or integration.sub_type != "bunq":
            continue
        client = BunqClient(api_key=integration.secret_key, account_key=integration.name)
        for account in accts:
            for draft in client.list_draft_payments(account.monetary_account_id):
                if draft.get("status") == "PENDING":
                    drafts.append(_summarize(draft, account))
    drafts.sort(key=lambda d: d.get("created") or "", reverse=True)
    return drafts


def get_cached_pending() -> list[dict[str, Any]] | None:
    """Pending drafts from the last poll, or None if no poll has completed yet."""
    with _lock:
        return list(_pending) if _pending is not None else None


def refresh_pending_drafts(db: Session | None = None) -> list[dict[str, Any]]:
    """Fetch pending drafts from bunq, cache them, and broadcast when the set changed."""
    global _pending
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        drafts = fetch_pending_drafts(db)
    finally:
        if own_session:
            db.close()

    with _lock:
        previous_ids = {d["id"] for d in _pending} if _pending is not None else None
        _pending = drafts
    current_ids = {d["id"] for d in drafts}
    if previous_ids == current_ids:
        return drafts

    new_count = len(current_ids - previous_ids) if previous_ids is not None else len(drafts)
    broadcast_event(
        "draft_payments_pending",
        {
            "count": len(drafts),
            "new_count": new_count,
            "items": drafts,
            "message": f"{len(drafts)} draft payment(s) awaiting approval",
        },
    )
    return drafts


async def watch_draft_payments() -> None:
    """Poll bunq for pending draft payments and push changes over SSE."""
    await asyncio.sleep(5)
    while True:
        try:
            await asyncio.to_thread(refresh_pending_drafts)
        except Exception as e:
            logger.error(f"Draft payment watcher failed: {e}")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
