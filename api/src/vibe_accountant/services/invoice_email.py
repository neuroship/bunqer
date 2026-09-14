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


def pick_sender(db: Session) -> InvoiceSource:
    """The first Gmail source whose grant allows sending mail."""
    connected = (
        db.query(InvoiceSource)
        .filter(InvoiceSource.gmail_token.isnot(None))
        .order_by(InvoiceSource.created_at)
        .all()
    )
    if not connected:
        raise HTTPException(400, "Connect a Gmail source first; it is used to send the email")
    sender = next((s for s in connected if gmail_fetcher.can_send(s.gmail_token)), None)
    if not sender:
        raise HTTPException(
            400, f"Reconnect Gmail on '{connected[0].name}' to allow sending email (new permission)"
        )
    return sender
