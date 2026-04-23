"""Match documents to transactions based on invoice number or payment reference."""

from sqlalchemy.orm import Session

from ..logger import logger
from ..models import Document, DocumentStatus, Transaction


def match_documents_to_transactions(db: Session) -> int:
    """Match unmatched documents to transactions.

    For each completed document with invoice_number or payment_reference,
    check if that value appears (case-insensitive) in any unmatched
    transaction's description. If found, link them.

    Returns count of new matches made.
    """
    # Get completed documents that have matchable fields
    docs = (
        db.query(Document)
        .filter(
            Document.status == DocumentStatus.COMPLETED.value,
            (Document.invoice_number.isnot(None)) | (Document.payment_reference.isnot(None)),
        )
        .all()
    )

    if not docs:
        return 0

    # Get transactions not yet matched to a document and that have a description
    unmatched_txns = (
        db.query(Transaction)
        .filter(
            Transaction.document_id.is_(None),
            Transaction.description.isnot(None),
        )
        .all()
    )

    if not unmatched_txns:
        return 0

    match_count = 0

    for doc in docs:
        # Collect search terms from document
        search_terms = []
        if doc.invoice_number:
            search_terms.append(doc.invoice_number.strip())
        if doc.payment_reference:
            search_terms.append(doc.payment_reference.strip())

        if not search_terms:
            continue

        for txn in unmatched_txns:
            if txn.document_id is not None:
                # Already matched in this run
                continue

            desc_lower = txn.description.lower()
            for term in search_terms:
                if term.lower() in desc_lower:
                    txn.document_id = doc.id
                    match_count += 1
                    logger.info(
                        f"Matched document {doc.id} ({doc.filename}) "
                        f"to transaction {txn.id} (term: '{term}')"
                    )
                    break  # One match per transaction is enough

    if match_count > 0:
        db.commit()
        logger.info(f"Document matching complete: {match_count} new matches")

    return match_count
