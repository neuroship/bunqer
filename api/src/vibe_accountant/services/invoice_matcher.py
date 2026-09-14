"""Mark open invoices as paid when an incoming transaction references their number."""

from datetime import timedelta

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..logger import logger
from ..models import Invoice, InvoiceStatus, Transaction

OPEN_STATUSES = (
    InvoiceStatus.SENT.value,
    InvoiceStatus.OVERDUE.value,
)

# Clients sometimes pay a few days before the invoice is dated.
DATE_GRACE = timedelta(days=14)


def match_invoices_to_transactions(db: Session) -> list[Invoice]:
    """Mark open invoices as paid from incoming transactions and record which
    transaction paid them.

    Pass 1: invoice number appears in the transaction description.
    Pass 2: for invoices still unmatched, the transaction amount equals the invoice total.

    Candidates are dated on or after the invoice date minus a short grace period.
    Invoices already paid but not yet linked to a transaction are linked the same
    way without being counted as newly paid. Each transaction pays at most one
    invoice. Returns the invoices newly marked paid.
    """
    invoices = (
        db.query(Invoice)
        .filter(
            or_(
                Invoice.status.in_(OPEN_STATUSES),
                and_(
                    Invoice.status == InvoiceStatus.PAID.value,
                    Invoice.paid_transaction_id.is_(None),
                ),
            )
        )
        .all()
    )
    if not invoices:
        return []

    incoming = db.query(Transaction).filter(Transaction.amount > 0).all()
    if not incoming:
        return []

    paid: list[Invoice] = []
    used_txn_ids: set[int] = {
        row[0]
        for row in db.query(Invoice.paid_transaction_id).filter(
            Invoice.paid_transaction_id.isnot(None)
        )
    }
    linked = False

    def _mark(invoice: Invoice, txn: Transaction, how: str) -> None:
        nonlocal linked
        if invoice.status != InvoiceStatus.PAID.value:
            invoice.status = InvoiceStatus.PAID.value
            paid.append(invoice)
        invoice.paid_transaction_id = txn.id
        used_txn_ids.add(txn.id)
        linked = True
        logger.info(
            f"Invoice {invoice.invoice_number} paid by transaction "
            f"{txn.id} ({txn.amount} {txn.currency}, {how})"
        )

    def _candidates(invoice: Invoice):
        earliest = invoice.invoice_date - DATE_GRACE
        for txn in incoming:
            if txn.id in used_txn_ids:
                continue
            if txn.transaction_date.date() < earliest:
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
        if invoice.paid_transaction_id or not invoice.total_amount:
            continue
        for txn in _candidates(invoice):
            if txn.amount == invoice.total_amount:
                _mark(invoice, txn, "amount")
                break

    if linked:
        db.commit()
    return paid
