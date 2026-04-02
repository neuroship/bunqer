"""CategoryRule model for automatic transaction categorization."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class CategoryRule(Base):
    """SQLAlchemy model for category rules."""

    __tablename__ = "category_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    conditions: Mapped[str] = mapped_column(Text, nullable=False)  # JSON blob
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationships
    category: Mapped["Category"] = relationship("Category", back_populates="rules")


# Pydantic schemas
class RuleCondition(BaseModel):
    """Schema for a single rule condition."""

    field: str  # description, counterparty_name, counterparty_iban, account_name, amount, direction, type, sub_type
    operator: str  # contains, not_contains, equals, starts_with, ends_with, greater_than, less_than, between
    value: Any  # string, number, or list for "between"

    @field_validator("field")
    @classmethod
    def validate_field(cls, v: str) -> str:
        allowed_fields = [
            "description",
            "counterparty_name",
            "counterparty_iban",
            "account_name",
            "amount",
            "direction",
            "type",
            "sub_type",
        ]
        if v not in allowed_fields:
            raise ValueError(f"Invalid field: {v}. Must be one of {allowed_fields}")
        return v

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        allowed_operators = [
            "contains",
            "not_contains",
            "equals",
            "starts_with",
            "ends_with",
            "greater_than",
            "less_than",
            "between",
        ]
        if v not in allowed_operators:
            raise ValueError(f"Invalid operator: {v}. Must be one of {allowed_operators}")
        return v


class RuleConditions(BaseModel):
    """Schema for rule conditions structure."""

    match: str = "all"  # "all" = AND, "any" = OR
    rules: list[RuleCondition]

    @field_validator("match")
    @classmethod
    def validate_match(cls, v: str) -> str:
        if v not in ["all", "any"]:
            raise ValueError("match must be 'all' or 'any'")
        return v


class CategoryRuleCreate(BaseModel):
    """Schema for creating a category rule."""

    name: str
    conditions: RuleConditions
    is_active: bool = True
    priority: int = 0


class CategoryRuleUpdate(BaseModel):
    """Schema for updating a category rule."""

    name: str | None = None
    conditions: RuleConditions | None = None
    is_active: bool | None = None
    priority: int | None = None


class CategoryRuleResponse(BaseModel):
    """Schema for category rule response."""

    id: int
    category_id: int
    name: str
    conditions: RuleConditions
    is_active: bool
    priority: int
    created_at: datetime

    class Config:
        from_attributes = True


# Import to avoid circular imports
from .category import Category  # noqa: E402, F401
