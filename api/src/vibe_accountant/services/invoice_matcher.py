"""Mark open invoices as paid when an incoming transaction references their number."""

from sqlalchemy.orm import Session

from ..logger import logger
from ..models import Invoice, InvoiceStatus, Transaction

OPEN_STATUSES = (
    InvoiceStatus.DRAFT.value,
    InvoiceStatus.SENT.value,
    InvoiceStatus.OVERDUE.value,
)


def match_invoices_to_transactions(db: Session) -> list[Invoice]:
    """Mark open invoices as paid when their invoice number appears in an
    incoming transaction's description on or after the invoice date.

    Returns the invoices that were marked paid.
    """
    invoices = db.query(Invoice).filter(Invoice.status.in_(OPEN_STATUSES)).all()
    if not invoices:
        return []

    incoming = (
        db.query(Transaction)
        .filter(Transaction.amount > 0)
        .filter(Transaction.description.isnot(None))
        .all()
    )
    if not incoming:
        return []

    paid: list[Invoice] = []
    for invoice in invoices:
        number = invoice.invoice_number.strip().lower()
        if not number:
            continue
        for txn in incoming:
            if txn.transaction_date.date() < invoice.invoice_date:
                continue
            if number in txn.description.lower():
                invoice.status = InvoiceStatus.PAID.value
                paid.append(invoice)
                logger.info(
                    f"Invoice {invoice.invoice_number} marked paid "
                    f"from transaction {txn.id} ({txn.amount} {txn.currency})"
                )
                break

    if paid:
        db.commit()
    return paid
