"""Invoice and InvoiceItem models."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel
from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class InvoiceStatus(str, Enum):
    """Invoice status enum."""

    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class Invoice(Base):
    """SQLAlchemy model for invoices."""

    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clients.id"), nullable=False
    )
    invoice_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=InvoiceStatus.DRAFT.value
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    client: Mapped["Client"] = relationship("Client", back_populates="invoices")
    items: Mapped[list["InvoiceItem"]] = relationship(
        "InvoiceItem", back_populates="invoice", cascade="all, delete-orphan"
    )


class InvoiceItem(Base):
    """SQLAlchemy model for invoice line items."""

    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=21)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationships
    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="items")


# Pydantic schemas
class InvoiceItemCreate(BaseModel):
    """Schema for creating an invoice item."""

    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal
    vat_rate: Decimal = Decimal("21")


class InvoiceItemResponse(BaseModel):
    """Schema for invoice item response."""

    id: int
    invoice_id: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    vat_rate: Decimal
    line_total: Decimal
    created_at: datetime

    class Config:
        from_attributes = True


class InvoiceCreate(BaseModel):
    """Schema for creating an invoice."""

    client_id: int
    invoice_number: str
    invoice_date: date
    due_date: date
    notes: str | None = None
    items: list[InvoiceItemCreate] = []


class InvoiceUpdate(BaseModel):
    """Schema for updating an invoice."""

    client_id: int | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    status: InvoiceStatus | None = None
    notes: str | None = None
    items: list[InvoiceItemCreate] | None = None


class InvoiceResponse(BaseModel):
    """Schema for invoice response."""

    id: int
    client_id: int
    invoice_number: str
    invoice_date: date
    due_date: date
    status: str
    subtotal: Decimal
    vat_amount: Decimal
    total_amount: Decimal
    notes: str | None
    items: list[InvoiceItemResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Import to avoid circular imports
from .client import Client  # noqa: E402, F401
