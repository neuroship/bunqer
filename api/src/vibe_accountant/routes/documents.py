"""Document upload, OCR, and management endpoints."""

import json
import traceback
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..logger import logger
from ..models import Document, DocumentListResponse, DocumentResponse, DocumentStatus, DocumentType
from ..services import s3
from ..services.document_processor import (
    denormalize_fields,
    extract_structured_data,
    ocr_document,
)

router = APIRouter(prefix="/documents", tags=["documents"])

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

    # Upload to S3
    s3_key = s3.upload_document(contents, file.filename, file.content_type)

    # Create DB record
    doc = Document(
        filename=file.filename,
        s3_key=s3_key,
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
    q = db.query(Document)

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
    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(d) for d in docs],
        total=total,
    )


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: int, db: Session = Depends(get_db)):
    """Get document details + extracted data."""
    doc = db.query(Document).get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
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
