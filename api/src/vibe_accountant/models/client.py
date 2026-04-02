"""Client model for invoicing."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Client(Base):
    """SQLAlchemy model for invoice clients."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vat_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chamber_of_commerce: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    invoices: Mapped[list["Invoice"]] = relationship("Invoice", back_populates="client")


# Pydantic schemas
class ClientCreate(BaseModel):
    """Schema for creating a client."""

    name: str
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str | None = None
    vat_number: str | None = None
    chamber_of_commerce: str | None = None
    email: str | None = None
    phone: str | None = None
    bank_account: str | None = None
    notes: str | None = None
    is_active: bool = True


class ClientUpdate(BaseModel):
    """Schema for updating a client."""

    name: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str | None = None
    vat_number: str | None = None
    chamber_of_commerce: str | None = None
    email: str | None = None
    phone: str | None = None
    bank_account: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class ClientResponse(BaseModel):
    """Schema for client response."""

    id: int
    name: str
    address: str | None
    city: str | None
    postal_code: str | None
    country: str | None
    vat_number: str | None
    chamber_of_commerce: str | None
    email: str | None
    phone: str | None
    bank_account: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Import to avoid circular imports
from .invoice import Invoice  # noqa: E402, F401
