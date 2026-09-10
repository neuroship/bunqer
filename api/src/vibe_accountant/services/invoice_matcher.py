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
    """Mark open invoices as paid from incoming transactions dated on or after
    the invoice date.

    Pass 1: invoice number appears in the transaction description.
    Pass 2: for invoices still open, the transaction amount equals the invoice total.

    Each transaction pays at most one invoice. Returns the invoices marked paid.
    """
    invoices = db.query(Invoice).filter(Invoice.status.in_(OPEN_STATUSES)).all()
    if not invoices:
        return []

    incoming = db.query(Transaction).filter(Transaction.amount > 0).all()
    if not incoming:
        return []

    paid: list[Invoice] = []
    used_txn_ids: set[int] = set()

    def _mark(invoice: Invoice, txn: Transaction, how: str) -> None:
        invoice.status = InvoiceStatus.PAID.value
        paid.append(invoice)
        used_txn_ids.add(txn.id)
        logger.info(
            f"Invoice {invoice.invoice_number} marked paid from transaction "
            f"{txn.id} ({txn.amount} {txn.currency}, {how})"
        )

    def _candidates(invoice: Invoice):
        for txn in incoming:
            if txn.id in used_txn_ids:
                continue
            if txn.transaction_date.date() < invoice.invoice_date:
                continue
            yield txn

    # Pass 1: invoice number in description
    for invoice in invoices:
        number = invoice.invoice_number.strip().lower()
        if not number:
            continue
        for txn in _candidates(invoice):
            if txn.description and number in txn.description.lower():
                _mark(invoice, txn, "reference")
                break

    # Pass 2: exact amount
    for invoice in invoices:
        if invoice.status == InvoiceStatus.PAID.value or not invoice.total_amount:
            continue
        for txn in _candidates(invoice):
            if txn.amount == invoice.total_amount:
                _mark(invoice, txn, "amount")
                break

    if paid:
        db.commit()
    return paid
