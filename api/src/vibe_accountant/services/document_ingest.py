"""Create Document rows from raw bytes (shared by upload and auto-fetch)."""

import hashlib

from sqlalchemy.orm import Session

from ..models import Document, DocumentStatus
from . import s3


def ingest_document_bytes(
    db: Session,
    contents: bytes,
    filename: str,
    content_type: str,
    doc_type: str,
    source_id: int | None = None,
    origin_ref: str | None = None,
) -> tuple[Document, bool]:
    """Store bytes as a new Document. Returns (document, created).

    If a document with identical content already exists, returns it with created=False.
    """
    content_hash = hashlib.sha256(contents).hexdigest()
    existing = db.query(Document).filter(Document.content_hash == content_hash).first()
    if existing:
        return existing, False

    s3_key = s3.upload_document(contents, filename, content_type)
    doc = Document(
        filename=filename,
        s3_key=s3_key,
        content_hash=content_hash,
        content_type=content_type,
        file_size=len(contents),
        doc_type=doc_type,
        status=DocumentStatus.PENDING.value,
        source_id=source_id,
        origin_ref=origin_ref,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc, True
