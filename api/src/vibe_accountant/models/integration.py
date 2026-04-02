"""Integration model for bunq and other banking connections."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Integration(Base):
    """SQLAlchemy model for integrations (bunq connections)."""

    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False, default="bank")
    sub_type: Mapped[str] = mapped_column(String(50), nullable=False, default="bunq")
    secret_key: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    accounts: Mapped[list["Account"]] = relationship("Account", back_populates="integration")


# Pydantic schemas
class IntegrationCreate(BaseModel):
    """Schema for creating an integration."""

    name: str
    type: str = "bank"
    sub_type: str = "bunq"
    secret_key: str


class IntegrationResponse(BaseModel):
    """Schema for integration response."""

    id: int
    name: str
    type: str
    sub_type: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Import Account here to avoid circular import
from .account import Account  # noqa: E402, F401
