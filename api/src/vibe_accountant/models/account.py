"""Account model for bank accounts."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Account(Base):
    """SQLAlchemy model for bank accounts."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    iban: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tag: Mapped[str | None] = mapped_column(String(100), nullable=True)
    integration_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("integrations.id"), nullable=False
    )
    monetary_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationships
    integration: Mapped["Integration"] = relationship("Integration", back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="account"
    )


# Pydantic schemas
class AccountCreate(BaseModel):
    """Schema for creating an account."""

    name: str
    iban: str | None = None
    tag: str | None = None
    integration_id: int
    monetary_account_id: int | None = None


class AccountResponse(BaseModel):
    """Schema for account response."""

    id: int
    name: str
    iban: str | None
    tag: str | None
    integration_id: int
    monetary_account_id: int | None
    created_at: datetime

    class Config:
        from_attributes = True


# Import to avoid circular imports
from .integration import Integration  # noqa: E402, F401
from .transaction import Transaction  # noqa: E402, F401
