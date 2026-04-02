"""Category model for transaction categorization."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Category(Base):
    """SQLAlchemy model for transaction categories."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)  # Hex color e.g. #FF5733
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationships
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="category"
    )
    rules: Mapped[list["CategoryRule"]] = relationship(
        "CategoryRule", back_populates="category", cascade="all, delete-orphan"
    )


# Pydantic schemas
class CategoryCreate(BaseModel):
    """Schema for creating a category."""

    name: str
    description: str | None = None
    color: str | None = None


class CategoryUpdate(BaseModel):
    """Schema for updating a category."""

    name: str | None = None
    description: str | None = None
    color: str | None = None


class CategoryResponse(BaseModel):
    """Schema for category response."""

    id: int
    name: str
    description: str | None
    color: str | None
    created_at: datetime

    class Config:
        from_attributes = True


# Import to avoid circular imports
from .transaction import Transaction  # noqa: E402, F401
from .category_rule import CategoryRule, RuleConditions  # noqa: E402, F401


# Export/Import schemas
class RuleExport(BaseModel):
    """Schema for exporting a rule (without IDs)."""

    name: str
    conditions: RuleConditions
    is_active: bool
    priority: int


class CategoryExport(BaseModel):
    """Schema for exporting a category with its rules."""

    name: str
    description: str | None
    color: str | None
    rules: list[RuleExport]


class CategoriesExport(BaseModel):
    """Schema for the full export file."""

    version: str = "1.0"
    exported_at: datetime
    categories: list[CategoryExport]


class CategoriesImport(BaseModel):
    """Schema for importing categories and rules."""

    version: str
    categories: list[CategoryExport]
