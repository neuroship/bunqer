"""Match documents to transactions based on invoice number or payment reference."""

from sqlalchemy.orm import Session

from ..logger import logger
from ..models import Document, DocumentStatus, Transaction


def match_documents_to_transactions(db: Session) -> int:
    """Match unmatched documents to transactions.

    Two-pass matching:
    1. Check if invoice_number or payment_reference appears (case-insensitive)
       in any unmatched transaction's description.
    2. For documents still unmatched after pass 1, fall back to matching by
       amount (absolute value) AND vendor_name vs counterparty_name.

    Returns count of new matches made.
    """
    docs = (
        db.query(Document)
        .filter(Document.status == DocumentStatus.COMPLETED.value)
        .all()
    )

    if not docs:
        return 0

    unmatched_txns = (
        db.query(Transaction)
        .filter(Transaction.document_id.is_(None))
        .all()
    )

    if not unmatched_txns:
        return 0

    match_count = 0
    matched_doc_ids = set()

    # Pass 1: invoice_number / payment_reference in description
    for doc in docs:
        search_terms = []
        if doc.invoice_number:
            search_terms.append(doc.invoice_number.strip())
        if doc.payment_reference:
            search_terms.append(doc.payment_reference.strip())

        if not search_terms:
            continue

        for txn in unmatched_txns:
            if txn.document_id is not None:
                continue
            if not txn.description:
                continue

            desc_lower = txn.description.lower()
            for term in search_terms:
                if term.lower() in desc_lower:
                    txn.document_id = doc.id
                    match_count += 1
                    matched_doc_ids.add(doc.id)
                    logger.info(
                        f"Matched document {doc.id} ({doc.filename}) "
                        f"to transaction {txn.id} (ref: '{term}')"
                    )
                    break

    # Pass 2: amount + vendor name fallback
    for doc in docs:
        if doc.id in matched_doc_ids:
            continue
        if doc.total_amount is None or not doc.vendor_name:
            continue

        doc_amount = abs(doc.total_amount)
        doc_vendor_lower = doc.vendor_name.lower().strip()

        if not doc_vendor_lower:
            continue

        for txn in unmatched_txns:
            if txn.document_id is not None:
                continue

            # Match absolute amount
            if abs(txn.amount) != doc_amount:
                continue

            # Match vendor name against counterparty name
            counterparty = txn.counterparty_name or ""
            if not counterparty:
                continue

            counterparty_lower = counterparty.lower().strip()
            if doc_vendor_lower in counterparty_lower or counterparty_lower in doc_vendor_lower:
                txn.document_id = doc.id
                match_count += 1
                matched_doc_ids.add(doc.id)
                logger.info(
                    f"Matched document {doc.id} ({doc.filename}) "
                    f"to transaction {txn.id} (amount+name fallback)"
                )
                break  # One match per document in fallback

    if match_count > 0:
        db.commit()
        logger.info(f"Document matching complete: {match_count} new matches")

    return match_count
