"""Document upload, OCR, and management endpoints."""

import hashlib
import json
import traceback
from collections import defaultdict
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

from ..database import get_db
from ..logger import logger
from ..models import Document, DocumentListResponse, DocumentResponse, DocumentStatus, DocumentType, MatchedTransactionInfo, Transaction
from ..services import s3
from ..services.document_processor import (
    denormalize_fields,
    extract_structured_data,
    ocr_document,
)

router = APIRouter(prefix="/documents", tags=["documents"])


def _doc_to_response(doc: Document) -> DocumentResponse:
    """Convert Document ORM object to response, including matched transactions."""
    resp = DocumentResponse.model_validate(doc)
    if doc.transactions:
        resp.matched_transactions = [
            MatchedTransactionInfo.model_validate(t) for t in doc.transactions
        ]
    return resp

ALLOWED_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/tiff",
}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


def _process_document(doc_id: int, db_url: str):
    """Background task: OCR + extraction for a document."""
    import asyncio

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        doc = db.query(Document).get(doc_id)
        if not doc:
            return

        doc.status = DocumentStatus.PROCESSING.value
        db.commit()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # OCR
        ocr_text = loop.run_until_complete(ocr_document(doc.s3_key))
        doc.ocr_text = ocr_text

        # Extract structured data
        extracted = loop.run_until_complete(extract_structured_data(ocr_text, doc.doc_type))
        doc.extracted_data = json.dumps(extracted)

        # Denormalize for search
        denormalize_fields(doc, extracted, doc.doc_type)

        doc.status = DocumentStatus.COMPLETED.value
        db.commit()
        logger.info(f"Document {doc_id} processed successfully")

    except Exception as e:
        logger.error(f"Document {doc_id} processing failed: {e}\n{traceback.format_exc()}")
        doc = db.query(Document).get(doc_id)
        if doc:
            doc.status = DocumentStatus.FAILED.value
            doc.error_message = str(e)
            db.commit()
    finally:
        db.close()
        engine.dispose()


@router.post("", response_model=DocumentResponse)
async def upload_document(
    doc_type: DocumentType = Query(...),
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """Upload a document and trigger OCR processing."""
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"File type not allowed. Accepted: {', '.join(ALLOWED_TYPES)}")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(400, "File too large. Max 20MB.")

    # Compute content hash
    content_hash = hashlib.sha256(contents).hexdigest()

    # Check for exact duplicate
    existing = db.query(Document).filter(Document.content_hash == content_hash).first()
    if existing:
        raise HTTPException(
            409,
            f"Duplicate document: '{existing.filename}' (id={existing.id}) has identical content.",
        )

    # Upload to S3
    s3_key = s3.upload_document(contents, file.filename, file.content_type)

    # Create DB record
    doc = Document(
        filename=file.filename,
        s3_key=s3_key,
        content_hash=content_hash,
        content_type=file.content_type,
        file_size=len(contents),
        doc_type=doc_type.value,
        status=DocumentStatus.PENDING.value,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Kick off background processing
    from ..config import settings

    background_tasks.add_task(_process_document, doc.id, settings.database_url)

    return DocumentResponse.model_validate(doc)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    doc_type: DocumentType | None = None,
    status: DocumentStatus | None = None,
    search: str | None = None,
    vendor: str | None = None,
    invoice_number: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List documents with filters."""
    q = db.query(Document).options(selectinload(Document.transactions))

    if doc_type:
        q = q.filter(Document.doc_type == doc_type.value)
    if status:
        q = q.filter(Document.status == status.value)
    if vendor:
        q = q.filter(Document.vendor_name.ilike(f"%{vendor}%"))
    if invoice_number:
        q = q.filter(Document.invoice_number.ilike(f"%{invoice_number}%"))
    if date_from:
        q = q.filter(
            or_(Document.invoice_date >= date_from, Document.due_date >= date_from)
        )
    if date_to:
        q = q.filter(
            or_(Document.invoice_date <= date_to, Document.due_date <= date_to)
        )
    if amount_min is not None:
        q = q.filter(Document.total_amount >= amount_min)
    if amount_max is not None:
        q = q.filter(Document.total_amount <= amount_max)
    if search:
        pattern = f"%{search}%"
        q = q.filter(
            or_(
                Document.filename.ilike(pattern),
                Document.vendor_name.ilike(pattern),
                Document.invoice_number.ilike(pattern),
                Document.tax_subject.ilike(pattern),
                Document.payment_reference.ilike(pattern),
            )
        )

    total = q.count()
    docs = q.order_by(Document.created_at.desc()).offset(skip).limit(limit).all()
    # Deduplicate (selectinload with offset/limit can sometimes cause dupes)
    seen = set()
    unique_docs = []
    for d in docs:
        if d.id not in seen:
            seen.add(d.id)
            unique_docs.append(d)
    return DocumentListResponse(
        documents=[_doc_to_response(d) for d in unique_docs],
        total=total,
    )


OCR_SIMILARITY_THRESHOLD = 0.85


@router.get("/duplicates/find")
async def find_duplicates(db: Session = Depends(get_db)):
    """Find duplicate document groups by content hash OR OCR text similarity."""
    completed_docs = (
        db.query(Document)
        .options(selectinload(Document.transactions))
        .filter(Document.status == DocumentStatus.COMPLETED.value)
        .all()
    )

    groups: list[dict] = []
    seen_ids: set[int] = set()

    # Pass 1: exact hash matches
    hash_groups: dict[str, list[Document]] = defaultdict(list)
    for doc in completed_docs:
        if doc.content_hash:
            hash_groups[doc.content_hash].append(doc)

    for hash_val, docs in hash_groups.items():
        if len(docs) > 1:
            for d in docs:
                seen_ids.add(d.id)
            groups.append({
                "reason": "exact_hash",
                "documents": [_doc_to_response(d) for d in docs],
            })

    # Pass 2: OCR text similarity for docs not already grouped
    ungrouped = [d for d in completed_docs if d.id not in seen_ids and d.ocr_text]
    for i, doc_a in enumerate(ungrouped):
        if doc_a.id in seen_ids:
            continue
        similar = [doc_a]
        for doc_b in ungrouped[i + 1:]:
            if doc_b.id in seen_ids:
                continue
            ratio = SequenceMatcher(None, doc_a.ocr_text, doc_b.ocr_text).ratio()
            if ratio >= OCR_SIMILARITY_THRESHOLD:
                similar.append(doc_b)
                seen_ids.add(doc_b.id)
        if len(similar) > 1:
            seen_ids.add(doc_a.id)
            groups.append({
                "reason": "ocr_similarity",
                "documents": [_doc_to_response(d) for d in similar],
            })

    return {"groups": groups, "total_groups": len(groups)}


@router.delete("/duplicates/{doc_id}")
async def delete_duplicate(
    doc_id: int,
    keep_id: int = Query(..., description="Document ID to reassign transactions to"),
    db: Session = Depends(get_db),
):
    """Delete a duplicate document, reassigning its transactions to the kept document."""
    doc = db.query(Document).get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    keep_doc = db.query(Document).get(keep_id)
    if not keep_doc:
        raise HTTPException(404, "Target document to keep not found")

    if doc_id == keep_id:
        raise HTTPException(400, "Cannot delete and keep the same document")

    # Reassign transactions
    reassigned = (
        db.query(Transaction)
        .filter(Transaction.document_id == doc_id)
        .update({Transaction.document_id: keep_id})
    )

    # Delete S3 object
    try:
        s3.delete_document(doc.s3_key)
    except Exception as e:
        logger.warning(f"Failed to delete S3 object {doc.s3_key}: {e}")

    db.delete(doc)
    db.commit()
    return {"detail": "Duplicate deleted", "transactions_reassigned": reassigned}


@router.post("/duplicates/backfill-hashes")
async def backfill_hashes(db: Session = Depends(get_db)):
    """Compute content_hash for existing documents that don't have one."""
    docs = db.query(Document).filter(Document.content_hash.is_(None)).all()
    updated = 0
    errors = 0
    for doc in docs:
        try:
            client = s3._get_client()
            response = client.get_object(
                Bucket=s3.settings.aws_s3_bucket_name,
                Key=doc.s3_key,
            )
            file_bytes = response["Body"].read()
            doc.content_hash = hashlib.sha256(file_bytes).hexdigest()
            updated += 1
        except Exception as e:
            logger.warning(f"Failed to hash document {doc.id} ({doc.s3_key}): {e}")
            errors += 1
    db.commit()
    return {"updated": updated, "errors": errors, "total": len(docs)}


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: int, db: Session = Depends(get_db)):
    """Get document details + extracted data."""
    doc = (
        db.query(Document)
        .options(selectinload(Document.transactions))
        .filter(Document.id == doc_id)
        .first()
    )
    if not doc:
        raise HTTPException(404, "Document not found")
    return _doc_to_response(doc)


@router.patch("/{doc_id}", response_model=DocumentResponse)
async def update_document(
    doc_id: int,
    doc_type: DocumentType = Query(...),
    reprocess: bool = Query(False),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """Update document type. Optionally reprocess with new type."""
    doc = db.query(Document).get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    doc.doc_type = doc_type.value
    db.commit()

    if reprocess:
        doc.status = DocumentStatus.PENDING.value
        doc.error_message = None
        db.commit()
        from ..config import settings
        background_tasks.add_task(_process_document, doc.id, settings.database_url)

    db.refresh(doc)
    return DocumentResponse.model_validate(doc)


@router.get("/{doc_id}/view-url")
async def get_document_view_url(doc_id: int, db: Session = Depends(get_db)):
    """Get presigned URL to view raw document."""
    doc = db.query(Document).get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    url = s3.get_presigned_url(doc.s3_key)
    return {"url": url}


@router.post("/{doc_id}/reprocess", response_model=DocumentResponse)
async def reprocess_document(
    doc_id: int,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """Re-run OCR + extraction on a document."""
    doc = db.query(Document).get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    doc.status = DocumentStatus.PENDING.value
    doc.error_message = None
    db.commit()
    db.refresh(doc)

    from ..config import settings

    background_tasks.add_task(_process_document, doc.id, settings.database_url)
    return DocumentResponse.model_validate(doc)


@router.delete("/{doc_id}")
async def delete_document(doc_id: int, db: Session = Depends(get_db)):
    """Delete document from DB and S3."""
    doc = db.query(Document).get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    try:
        s3.delete_document(doc.s3_key)
    except Exception as e:
        logger.warning(f"Failed to delete S3 object {doc.s3_key}: {e}")

    db.delete(doc)
    db.commit()
    return {"detail": "Document deleted"}
