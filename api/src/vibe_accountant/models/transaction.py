"""Transaction model for bank transactions."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Transaction(Base):
    """SQLAlchemy model for bank transactions."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bunq_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    # Sender info (who sent the money)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_iban: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Receiver info (who received the money)
    receiver_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receiver_iban: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Legacy counterparty fields (kept for compatibility)
    counterparty_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    counterparty_iban: Mapped[str | None] = mapped_column(String(50), nullable=True)

    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sub_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Balance after this transaction
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Geolocation (where the transaction happened)
    geo_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    geo_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Batch and scheduling
    batch_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    scheduled_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Request reference (for payment requests / split bills)
    request_reference_split_the_bill: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Raw JSON from bunq API
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Category and tag
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=True
    )
    tag: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Matched document
    document_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    transaction_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationships
    account: Mapped["Account"] = relationship("Account", back_populates="transactions")
    category: Mapped["Category | None"] = relationship("Category", back_populates="transactions")
    document: Mapped["Document | None"] = relationship("Document", back_populates="transactions")


# Pydantic schemas
class TransactionCreate(BaseModel):
    """Schema for creating a transaction."""

    bunq_id: int | None = None
    account_id: int
    amount: Decimal
    currency: str = "EUR"
    sender_name: str | None = None
    sender_iban: str | None = None
    receiver_name: str | None = None
    receiver_iban: str | None = None
    counterparty_name: str | None = None
    counterparty_iban: str | None = None
    description: str | None = None
    type: str | None = None
    sub_type: str | None = None
    balance_after: Decimal | None = None
    geo_latitude: float | None = None
    geo_longitude: float | None = None
    batch_id: int | None = None
    scheduled_id: int | None = None
    request_reference_split_the_bill: str | None = None
    category_id: int | None = None
    tag: str | None = None
    transaction_date: datetime


class TransactionResponse(BaseModel):
    """Schema for transaction response."""

    id: int
    bunq_id: int | None
    account_id: int
    amount: Decimal
    currency: str
    sender_name: str | None
    sender_iban: str | None
    receiver_name: str | None
    receiver_iban: str | None
    counterparty_name: str | None
    counterparty_iban: str | None
    description: str | None
    type: str | None
    sub_type: str | None
    balance_after: Decimal | None
    geo_latitude: float | None
    geo_longitude: float | None
    batch_id: int | None
    scheduled_id: int | None
    request_reference_split_the_bill: str | None
    category_id: int | None
    tag: str | None
    document_id: int | None = None
    document_filename: str | None = None
    transaction_date: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class BunqTransaction(BaseModel):
    """Schema for bunq API transaction data."""

    id: int
    amount: Decimal
    currency: str
    sender_name: str | None = None
    sender_iban: str | None = None
    receiver_name: str | None = None
    receiver_iban: str | None = None
    counterparty_name: str | None = None
    counterparty_iban: str | None = None
    description: str | None = None
    type: str | None = None
    sub_type: str | None = None
    balance_after: Decimal | None = None
    geo_latitude: float | None = None
    geo_longitude: float | None = None
    batch_id: int | None = None
    scheduled_id: int | None = None
    request_reference_split_the_bill: str | None = None
    created: datetime
    monetary_account_id: int | None = None
    raw_json: str | None = None

    @classmethod
    def from_api_response(cls, data: dict) -> "BunqTransaction":
        """Create a BunqTransaction from bunq API response data."""
        import json
        # Store raw JSON
        raw_json = json.dumps(data, indent=2, default=str)

        # Extract amount
        amount_data = data.get("amount", {})
        amount = Decimal(amount_data.get("value", "0"))
        currency = amount_data.get("currency", "EUR")

        # Extract counterparty info (the other party)
        counterparty = data.get("counterparty_alias", {}) or {}
        counterparty_name = counterparty.get("display_name") or counterparty.get("name")
        counterparty_iban = None
        if counterparty.get("type") == "IBAN":
            counterparty_iban = counterparty.get("value")

        # Extract alias info (our own account)
        alias = data.get("alias", {}) or {}
        alias_name = alias.get("display_name") or alias.get("name")
        alias_iban = None
        if alias.get("type") == "IBAN":
            alias_iban = alias.get("value")

        # Determine sender and receiver based on amount direction
        # Negative amount = we sent money (we are sender)
        # Positive amount = we received money (counterparty is sender)
        if amount < 0:
            # Outgoing payment: we are sender, counterparty is receiver
            sender_name = alias_name
            sender_iban = alias_iban
            receiver_name = counterparty_name
            receiver_iban = counterparty_iban
        else:
            # Incoming payment: counterparty is sender, we are receiver
            sender_name = counterparty_name
            sender_iban = counterparty_iban
            receiver_name = alias_name
            receiver_iban = alias_iban

        # Extract balance after mutation
        balance_after_data = data.get("balance_after_mutation", {}) or {}
        balance_after = None
        if balance_after_data.get("value"):
            balance_after = Decimal(balance_after_data.get("value", "0"))

        # Extract geolocation
        geo = data.get("geolocation", {}) or {}
        geo_latitude = None
        geo_longitude = None
        if geo.get("latitude"):
            try:
                geo_latitude = float(geo.get("latitude"))
            except (ValueError, TypeError):
                pass
        if geo.get("longitude"):
            try:
                geo_longitude = float(geo.get("longitude"))
            except (ValueError, TypeError):
                pass

        # Extract request references (for split bills)
        request_refs = data.get("request_reference_split_the_bill", []) or []
        request_ref_str = None
        if request_refs:
            # Convert list to comma-separated string of IDs
            ref_ids = [str(ref.get("id", "")) for ref in request_refs if ref.get("id")]
            request_ref_str = ",".join(ref_ids) if ref_ids else None

        # Parse created timestamp
        created_str = data.get("created", "")
        try:
            created = datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            created = datetime.now()

        return cls(
            id=data.get("id", 0),
            amount=amount,
            currency=currency,
            sender_name=sender_name,
            sender_iban=sender_iban,
            receiver_name=receiver_name,
            receiver_iban=receiver_iban,
            counterparty_name=counterparty_name,
            counterparty_iban=counterparty_iban,
            description=data.get("description"),
            type=data.get("type"),
            sub_type=data.get("sub_type"),
            balance_after=balance_after,
            geo_latitude=geo_latitude,
            geo_longitude=geo_longitude,
            batch_id=data.get("batch_id"),
            scheduled_id=data.get("scheduled_id"),
            request_reference_split_the_bill=request_ref_str,
            created=created,
            monetary_account_id=data.get("monetary_account_id"),
            raw_json=raw_json,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "amount": str(self.amount),
            "currency": self.currency,
            "sender_name": self.sender_name,
            "sender_iban": self.sender_iban,
            "receiver_name": self.receiver_name,
            "receiver_iban": self.receiver_iban,
            "counterparty_name": self.counterparty_name,
            "counterparty_iban": self.counterparty_iban,
            "description": self.description,
            "type": self.type,
            "sub_type": self.sub_type,
            "balance_after": str(self.balance_after) if self.balance_after else None,
            "geo_latitude": self.geo_latitude,
            "geo_longitude": self.geo_longitude,
            "batch_id": self.batch_id,
            "scheduled_id": self.scheduled_id,
            "request_reference_split_the_bill": self.request_reference_split_the_bill,
            "created": self.created.isoformat(),
            "monetary_account_id": self.monetary_account_id,
        }


# Import to avoid circular imports
from .account import Account  # noqa: E402, F401
from .category import Category  # noqa: E402, F401
from .document import Document  # noqa: E402, F401
