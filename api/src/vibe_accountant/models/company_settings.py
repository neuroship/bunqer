"""Company settings model for invoice branding."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class CompanySettings(Base):
    """Single-row table for company information displayed on invoices."""

    __tablename__ = "company_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vat_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chamber_of_commerce: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    iban: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logo_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CompanySettingsUpdate(BaseModel):
    """Schema for updating company settings."""

    name: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str | None = None
    vat_number: str | None = None
    chamber_of_commerce: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    iban: str | None = None
    bank_name: str | None = None


class CompanySettingsResponse(BaseModel):
    """Schema for company settings response."""

    id: int
    name: str | None
    address: str | None
    city: str | None
    postal_code: str | None
    country: str | None
    vat_number: str | None
    chamber_of_commerce: str | None
    email: str | None
    phone: str | None
    website: str | None
    iban: str | None
    bank_name: str | None
    logo_base64: str | None = None
    has_logo: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
