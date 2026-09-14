"""Shared pieces for emailing invoices through a connected Gmail source."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import InvoiceSource, ProviderSetting
from . import gmail_fetcher

# Last address invoices were emailed to, kept in the provider key/value store (not shown under Providers).
RECIPIENT_KEY = "invoice_email_to"


def clean_address(to: str) -> str:
    to = to.strip()
    if "@" not in to:
        raise HTTPException(400, "Enter a valid email address")
    return to


def get_recipient(db: Session) -> str | None:
    row = db.query(ProviderSetting).get(RECIPIENT_KEY)
    return row.value if row else None


def remember_recipient(db: Session, to: str) -> None:
    row = db.query(ProviderSetting).get(RECIPIENT_KEY) or ProviderSetting(key=RECIPIENT_KEY)
    row.value = to
    db.add(row)
    db.commit()


def find_sender(db: Session) -> tuple[InvoiceSource | None, InvoiceSource | None]:
    """(sender, needs_reconnect): the first Gmail source that can send, or else the first
    connected one, which must be reconnected to grant the send permission."""
    connected = (
        db.query(InvoiceSource)
        .filter(InvoiceSource.gmail_token.isnot(None))
        .order_by(InvoiceSource.created_at)
        .all()
    )
    sender = next((s for s in connected if gmail_fetcher.can_send(s.gmail_token)), None)
    if sender:
        return sender, None
    return None, (connected[0] if connected else None)


def pick_sender(db: Session) -> InvoiceSource:
    sender, reconnect = find_sender(db)
    if sender:
        return sender
    if reconnect:
        raise HTTPException(
            400, f"Reconnect Gmail on '{reconnect.name}' to allow sending email (new permission)"
        )
    raise HTTPException(400, "Connect a Gmail source first; it is used to send the email")
