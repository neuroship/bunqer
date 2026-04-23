"""Document model for uploaded invoices and tax letters."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel
from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class DocumentType(str, Enum):
    """Document type enum."""

    SALES_INVOICE = "sales_invoice"
    PURCHASE_INVOICE = "purchase_invoice"
    TAX_LETTER = "tax_letter"


class DocumentStatus(str, Enum):
    """Processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base):
    """SQLAlchemy model for uploaded documents."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DocumentStatus.PENDING.value
    )
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string

    # Denormalized fields for search/filter
    vendor_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    tax_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="document")


# --- Pydantic schemas ---


class MatchedTransactionInfo(BaseModel):
    """Minimal transaction info for document response."""

    id: int
    amount: Decimal
    description: str | None = None
    counterparty_name: str | None = None
    transaction_date: datetime

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    """Response schema for a document."""

    id: int
    filename: str
    s3_key: str
    content_hash: str | None = None
    content_type: str
    file_size: int
    doc_type: str
    status: str
    ocr_text: str | None = None
    extracted_data: str | None = None
    vendor_name: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    total_amount: Decimal | None = None
    tax_subject: str | None = None
    payment_reference: str | None = None
    error_message: str | None = None
    matched_transactions: list[MatchedTransactionInfo] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """Response schema for document list with pagination."""

    documents: list[DocumentResponse]
    total: int


# Import to avoid circular imports
from .transaction import Transaction  # noqa: E402, F401
