"""Background watcher for bunq items awaiting approval.

Covers two kinds: draft payments (outgoing, created by us or in the bunq app)
and incoming payment requests (someone asking this account to pay).
"""

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


def _label(counterparty: dict[str, Any] | None) -> dict[str, Any]:
    counterparty = counterparty or {}
    return counterparty.get("label_monetary_account") or counterparty


def _display_name(label: dict[str, Any]) -> str | None:
    return label.get("display_name") or (label.get("label_user") or {}).get("display_name")


def _summarize_draft(draft: dict[str, Any], account: Account) -> dict[str, Any]:
    entries = draft.get("entries") or []
    first = entries[0] if entries else {}
    label = _label(first.get("counterparty_alias"))
    total = sum(Decimal((e.get("amount") or {}).get("value") or "0") for e in entries)
    return {
        "kind": "draft",
        "id": draft.get("id"),
        "account_id": account.id,
        "account_name": account.name,
        "status": draft.get("status"),
        "created": draft.get("created"),
        "updated": draft.get("updated"),
        "amount": f"{total:.2f}",
        "currency": (first.get("amount") or {}).get("currency"),
        "counterparty_name": _display_name(label),
        "counterparty_iban": label.get("iban"),
        "description": first.get("description"),
        "entry_count": len(entries),
        "created_by": (draft.get("user_alias_created") or {}).get("display_name"),
    }


def _summarize_request(req: dict[str, Any], account: Account) -> dict[str, Any]:
    label = _label(req.get("counterparty_alias"))
    amount = req.get("amount_inquired") or {}
    return {
        "kind": "request",
        "id": req.get("id"),
        "account_id": account.id,
        "account_name": account.name,
        "status": req.get("status"),
        "created": req.get("created"),
        "updated": req.get("updated"),
        "amount": amount.get("value"),
        "currency": amount.get("currency"),
        "counterparty_name": _display_name(label),
        "counterparty_iban": label.get("iban"),
        "description": req.get("description"),
        "request_type": req.get("type"),
        "expires": req.get("time_expiry"),
    }


def fetch_pending_approvals(db: Session) -> list[dict[str, Any]]:
    """List PENDING drafts and incoming requests across all bunq-linked accounts, newest first."""
    accounts = db.query(Account).filter(Account.monetary_account_id.isnot(None)).all()
    by_integration: dict[int, list[Account]] = {}
    for account in accounts:
        by_integration.setdefault(account.integration_id, []).append(account)

    items: list[dict[str, Any]] = []
    for integration_id, accts in by_integration.items():
        integration = db.query(Integration).filter(Integration.id == integration_id).first()
        if not integration or integration.sub_type != "bunq":
            continue
        client = BunqClient(api_key=integration.secret_key, account_key=integration.name)
        for account in accts:
            for draft in client.list_draft_payments(account.monetary_account_id):
                if draft.get("status") == "PENDING":
                    items.append(_summarize_draft(draft, account))
            for req in client.list_request_responses(account.monetary_account_id):
                if req.get("status") == "PENDING":
                    items.append(_summarize_request(req, account))
    items.sort(key=lambda d: d.get("created") or "", reverse=True)
    return items


def get_cached_pending() -> list[dict[str, Any]] | None:
    """Pending items from the last poll, or None if no poll has completed yet."""
    with _lock:
        return list(_pending) if _pending is not None else None


def _key(item: dict[str, Any]) -> tuple[str, Any]:
    return (item["kind"], item["id"])


def _message(items: list[dict[str, Any]]) -> str:
    drafts = sum(1 for i in items if i["kind"] == "draft")
    requests = len(items) - drafts
    parts = []
    if drafts:
        parts.append(f"{drafts} draft payment(s)")
    if requests:
        parts.append(f"{requests} incoming request(s)")
    return (" and ".join(parts) or "Nothing") + " awaiting approval"


def refresh_pending_approvals(db: Session | None = None) -> list[dict[str, Any]]:
    """Fetch pending items from bunq, cache them, and broadcast when the set changed."""
    global _pending
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        items = fetch_pending_approvals(db)
    finally:
        if own_session:
            db.close()

    with _lock:
        previous_keys = {_key(i) for i in _pending} if _pending is not None else None
        _pending = items
    current_keys = {_key(i) for i in items}
    if previous_keys == current_keys:
        return items

    new_count = len(current_keys - previous_keys) if previous_keys is not None else len(items)
    broadcast_event(
        "approvals_pending",
        {
            "count": len(items),
            "new_count": new_count,
            "items": items,
            "message": _message(items),
        },
    )
    return items


async def watch_pending_approvals() -> None:
    """Poll bunq for items awaiting approval and push changes over SSE."""
    await asyncio.sleep(5)
    while True:
        try:
            await asyncio.to_thread(refresh_pending_approvals)
        except Exception as e:
            logger.error(f"Approval watcher failed: {e}")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
