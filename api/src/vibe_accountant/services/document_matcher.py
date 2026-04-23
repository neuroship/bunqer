"""Match documents to transactions based on invoice number or payment reference."""

from difflib import SequenceMatcher

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


def _name_similarity(a: str, b: str) -> float:
    """Return similarity ratio between two names (0.0 to 1.0)."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _is_substring_match(a: str, b: str) -> bool:
    """Check if either string is a substring of the other (already handled by auto-match)."""
    al, bl = a.lower().strip(), b.lower().strip()
    return al in bl or bl in al


def find_match_suggestions(
    db: Session, similarity_threshold: float = 0.4
) -> list[dict]:
    """Find potential document-transaction matches based on amount + name similarity.

    Returns suggestions for pairs where:
    - Amount matches (absolute value)
    - Counterparty name is similar to vendor name (above threshold)
    - But NOT a substring match (those are handled by auto-match)

    Each suggestion is a dict with document info, transaction info, and similarity score.
    """
    docs = (
        db.query(Document)
        .filter(Document.status == DocumentStatus.COMPLETED.value)
        .filter(Document.total_amount.isnot(None))
        .filter(Document.vendor_name.isnot(None))
        .filter(Document.vendor_name != "")
        .all()
    )

    if not docs:
        return []

    unmatched_txns = (
        db.query(Transaction)
        .filter(Transaction.document_id.is_(None))
        .all()
    )

    if not unmatched_txns:
        return []

    suggestions = []

    for doc in docs:
        doc_amount = abs(doc.total_amount)
        doc_vendor = doc.vendor_name.strip()

        if not doc_vendor:
            continue

        for txn in unmatched_txns:
            counterparty = txn.counterparty_name or ""
            if not counterparty.strip():
                continue

            if abs(txn.amount) != doc_amount:
                continue

            # Skip substring matches — auto-match handles those
            if _is_substring_match(doc_vendor, counterparty):
                continue

            similarity = _name_similarity(doc_vendor, counterparty)
            if similarity >= similarity_threshold:
                suggestions.append(
                    {
                        "document_id": doc.id,
                        "document_filename": doc.filename,
                        "document_vendor": doc.vendor_name,
                        "document_amount": str(doc.total_amount),
                        "transaction_id": txn.id,
                        "transaction_counterparty": txn.counterparty_name,
                        "transaction_amount": str(txn.amount),
                        "transaction_date": txn.transaction_date.isoformat()
                        if txn.transaction_date
                        else None,
                        "transaction_description": txn.description,
                        "similarity": round(similarity, 2),
                    }
                )

    # Sort by similarity descending
    suggestions.sort(key=lambda s: s["similarity"], reverse=True)
    return suggestions
