"""Match documents (purchase/sales invoices, tax letters) to bank transactions.

Rules, in order of strength:
1. Reference: the invoice number or payment reference appears as a whole token in the
   transaction description, the amount agrees, and the dates are plausible.
2. Amount + counterparty: same absolute amount, the counterparty name resembles the vendor,
   and the transaction date is close to the invoice date.

Every document links to at most one transaction and every transaction to at most one
document. When more than one transaction qualifies and the dates do not separate them,
nothing is linked and the case is reported as ambiguous for a human to decide.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..logger import logger
from ..models import Document, DocumentStatus, Transaction

REF_MIN_LEN = 6
# Payments can precede the invoice date (direct debit announcements) or trail it.
WINDOW_BEFORE = timedelta(days=14)
WINDOW_AFTER = timedelta(days=75)
# Looser window for reference matches and suggestions.
WIDE_BEFORE = timedelta(days=30)
WIDE_AFTER = timedelta(days=120)
# Two amount candidates count as distinct when their date distances differ by at least this.
AMBIGUITY_GAP = timedelta(days=14)
NAME_SIMILARITY = 0.6
NOISE_TOKENS = {"bv", "nv", "ltd", "inc", "llc", "gmbh", "sa", "ag", "co", "the", "de", "van"}


@dataclass
class Candidate:
    txn: Transaction
    how: str  # reference | name | amount
    similarity: float = 0.0
    days: int | None = None  # transaction date minus invoice date


@dataclass
class Ambiguity:
    document: Document
    candidates: list[Candidate]


@dataclass
class MatchReport:
    matched: int = 0
    ambiguous: list[Ambiguity] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "matched": self.matched,
            "ambiguous": [
                {
                    "document_id": a.document.id,
                    "document_filename": a.document.filename,
                    "document_vendor": a.document.vendor_name,
                    "document_amount": str(a.document.total_amount),
                    "document_date": a.document.invoice_date.isoformat() if a.document.invoice_date else None,
                    "candidates": [
                        {
                            "transaction_id": c.txn.id,
                            "transaction_date": c.txn.transaction_date.date().isoformat(),
                            "transaction_amount": str(c.txn.amount),
                            "transaction_counterparty": c.txn.counterparty_name,
                            "transaction_description": c.txn.description,
                            "how": c.how,
                            "days_from_invoice": c.days,
                        }
                        for c in a.candidates
                    ],
                }
                for a in self.ambiguous
            ],
        }


# --- helpers ---


def _unmatched_documents(db: Session) -> list[Document]:
    matched_doc_ids = select(Transaction.document_id).where(Transaction.document_id.isnot(None))
    return (
        db.query(Document)
        .filter(Document.status == DocumentStatus.COMPLETED.value)
        .filter(~Document.id.in_(matched_doc_ids))
        .all()
    )


def _direction_ok(doc: Document, txn: Transaction) -> bool:
    if doc.doc_type == "purchase_invoice":
        return txn.amount < 0
    if doc.doc_type == "sales_invoice":
        return txn.amount > 0
    return True


def _amount_ok(doc: Document, txn: Transaction) -> bool:
    return doc.total_amount is not None and abs(txn.amount) == abs(doc.total_amount)


def _anchor_date(doc: Document) -> date | None:
    return doc.invoice_date or doc.due_date


def _days(doc: Document, txn: Transaction) -> int | None:
    anchor = _anchor_date(doc)
    return (txn.transaction_date.date() - anchor).days if anchor else None


def _window_ok(doc: Document, txn: Transaction, before: timedelta, after: timedelta) -> bool:
    anchor = _anchor_date(doc)
    if not anchor:
        return True
    d = txn.transaction_date.date()
    return anchor - before <= d <= anchor + after


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _ref_terms(doc: Document) -> list[str]:
    """Usable reference strings: long enough, not masked, not an IBAN."""
    terms = []
    for raw in (doc.invoice_number, doc.payment_reference):
        if not raw or "*" in raw:
            continue
        norm = _normalize(raw)
        if len(norm) < REF_MIN_LEN or re.match(r"^[a-z]{2}\d{2}[a-z0-9]{8,}$", norm):
            continue
        terms.append(norm)
    return terms


def _ref_in_description(term: str, description: str | None) -> bool:
    """Whole-token match: the reference must not be a fragment of a longer number."""
    if not description:
        return False
    tokens = re.findall(r"[a-z0-9]+", description.lower())
    if term in tokens:
        return True
    # References written with separators ("2026-0037", "INV 12 34") collapse to one token.
    joined = _normalize(description)
    idx = joined.find(term)
    while idx != -1:
        before = joined[idx - 1] if idx > 0 else ""
        after = joined[idx + len(term)] if idx + len(term) < len(joined) else ""
        if not before.isdigit() and not after.isdigit():
            return True
        idx = joined.find(term, idx + 1)
    return False


def _tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) >= 3 and t not in NOISE_TOKENS}


def _name_similarity(doc: Document, txn: Transaction) -> float:
    """1.0 for substring/token overlap, else SequenceMatcher ratio."""
    vendor = (doc.vendor_name or "").strip().lower()
    counterparty = (txn.counterparty_name or "").strip().lower()
    if not vendor or not counterparty:
        return 0.0
    if vendor in counterparty or counterparty in vendor:
        return 1.0
    if _tokens(vendor) & _tokens(counterparty):
        return 1.0
    return SequenceMatcher(None, vendor, counterparty).ratio()


def _pick(candidates: list[Candidate]) -> Candidate | None:
    """Single candidate wins; several win only when dates separate them clearly."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if any(c.days is None for c in candidates):
        return None
    ordered = sorted(candidates, key=lambda c: abs(c.days))
    gap = abs(ordered[1].days) - abs(ordered[0].days)
    return ordered[0] if gap >= AMBIGUITY_GAP.days else None


# --- auto matching ---


def match_documents_to_transactions(db: Session) -> MatchReport:
    """Link each unmatched completed document to at most one transaction. See module doc."""
    report = MatchReport()
    docs = _unmatched_documents(db)
    if not docs:
        return report
    txns = db.query(Transaction).filter(Transaction.document_id.is_(None)).all()
    if not txns:
        return report

    used: set[int] = set()
    for doc in docs:
        free = [t for t in txns if t.id not in used and _direction_ok(doc, t)]

        # Pass 1: reference in description (+ amount when the document has one)
        terms = _ref_terms(doc)
        refs = [
            Candidate(t, "reference", 1.0, _days(doc, t))
            for t in free
            if terms
            and any(_ref_in_description(term, t.description) for term in terms)
            and (doc.total_amount is None or _amount_ok(doc, t))
            and _window_ok(doc, t, WIDE_BEFORE, WIDE_AFTER)
        ]
        chosen = _pick(refs)
        if chosen is None and len(refs) > 1:
            report.ambiguous.append(Ambiguity(doc, refs))
            continue

        # Pass 2: amount + counterparty name within the date window
        if chosen is None:
            by_amount = [
                Candidate(t, "name", _name_similarity(doc, t), _days(doc, t))
                for t in free
                if _amount_ok(doc, t) and _window_ok(doc, t, WINDOW_BEFORE, WINDOW_AFTER)
            ]
            strong = [c for c in by_amount if c.similarity >= NAME_SIMILARITY]
            chosen = _pick(strong)
            if chosen is None and len(strong) > 1:
                report.ambiguous.append(Ambiguity(doc, strong))
                continue

        if chosen is None:
            continue
        chosen.txn.document_id = doc.id
        used.add(chosen.txn.id)
        report.matched += 1
        logger.info(
            f"Matched document {doc.id} ({doc.filename}) to transaction {chosen.txn.id} "
            f"({chosen.how}, {chosen.days} days from invoice)"
        )

    if report.matched:
        db.commit()
    if report.ambiguous:
        logger.info(f"{len(report.ambiguous)} document(s) have several plausible transactions; left unmatched")
    return report


# --- suggestions for the UI ---


def _suggestion(doc: Document, c: Candidate, match_type: str, group_size: int = 1) -> dict:
    return {
        "document_id": doc.id,
        "document_filename": doc.filename,
        "document_vendor": doc.vendor_name,
        "document_amount": str(doc.total_amount),
        "document_date": doc.invoice_date.isoformat() if doc.invoice_date else None,
        "transaction_id": c.txn.id,
        "transaction_counterparty": c.txn.counterparty_name,
        "transaction_amount": str(c.txn.amount),
        "transaction_date": c.txn.transaction_date.isoformat() if c.txn.transaction_date else None,
        "transaction_description": c.txn.description,
        "similarity": round(c.similarity, 2),
        "days_from_invoice": c.days,
        "match_type": match_type,
        "candidates": group_size,
    }


def find_match_suggestions(db: Session, similarity_threshold: float = 0.4) -> list[dict]:
    """Candidates for documents the auto matcher left alone.

    match_type: "ambiguous" (several strong candidates, pick one), "name_similar"
    (one amount match with a resembling name), "amount_only" (amount matches, name does not).
    """
    docs = [d for d in _unmatched_documents(db) if d.total_amount is not None]
    if not docs:
        return []
    txns = db.query(Transaction).filter(Transaction.document_id.is_(None)).all()
    if not txns:
        return []

    out: list[dict] = []
    for doc in docs:
        cands = [
            Candidate(t, "amount", _name_similarity(doc, t), _days(doc, t))
            for t in txns
            if _direction_ok(doc, t) and _amount_ok(doc, t) and _window_ok(doc, t, WIDE_BEFORE, WIDE_AFTER)
        ]
        if not cands:
            continue
        strong = [c for c in cands if c.similarity >= similarity_threshold]
        if len(strong) > 1:
            for c in sorted(strong, key=lambda c: abs(c.days) if c.days is not None else 10**6):
                out.append(_suggestion(doc, c, "ambiguous", len(strong)))
        elif len(strong) == 1:
            out.append(_suggestion(doc, strong[0], "name_similar"))
        else:
            for c in sorted(cands, key=lambda c: abs(c.days) if c.days is not None else 10**6)[:3]:
                out.append(_suggestion(doc, c, "amount_only", len(cands)))

    order = {"ambiguous": 0, "name_similar": 1, "amount_only": 2}
    out.sort(key=lambda s: (order[s["match_type"]], s["document_id"], -s["similarity"]))
    return out


# --- audit / repair of existing links ---


def find_bad_links(db: Session) -> list[tuple[Transaction, Document, str]]:
    """Existing links that break the rules: wrong direction, different amount, or dates far apart."""
    bad = []
    linked = db.query(Transaction).filter(Transaction.document_id.isnot(None)).all()
    per_doc: dict[int, list[Transaction]] = {}
    for t in linked:
        per_doc.setdefault(t.document_id, []).append(t)
    for doc_id, ts in per_doc.items():
        doc = db.get(Document, doc_id)
        if not doc:
            continue
        for t in ts:
            if not _direction_ok(doc, t):
                bad.append((t, doc, "wrong direction"))
            elif doc.total_amount is not None and not _amount_ok(doc, t):
                bad.append((t, doc, f"amount {t.amount} vs {doc.total_amount}"))
            elif not _window_ok(doc, t, WIDE_BEFORE, WIDE_AFTER):
                bad.append((t, doc, f"{_days(doc, t)} days from invoice"))
        if len(ts) > 1:
            for t in ts:
                if not any(b[0].id == t.id for b in bad):
                    bad.append((t, doc, "document linked to several transactions"))
    return bad


def unlink_bad_links(db: Session) -> int:
    bad = find_bad_links(db)
    for t, doc, reason in bad:
        logger.info(f"Unlinking transaction {t.id} from document {doc.id}: {reason}")
        t.document_id = None
    if bad:
        db.commit()
    return len(bad)
