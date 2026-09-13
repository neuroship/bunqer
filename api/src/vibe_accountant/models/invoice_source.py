"""Invoice sources (websites / Gmail) and their fetch runs."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class SourceKind(str, Enum):
    WEBSITE = "website"
    GMAIL = "gmail"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class InvoiceSource(Base):
    """A place invoices are fetched from."""

    __tablename__ = "invoice_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # website
    login_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    op_username_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)  # op://Vault/Item/field
    op_password_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    # gmail
    gmail_query: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    gmail_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gmail_token: Mapped[str | None] = mapped_column(Text, nullable=True)  # authorized user JSON

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    runs: Mapped[list["InvoiceFetchRun"]] = relationship(
        "InvoiceFetchRun", back_populates="source", cascade="all, delete-orphan"
    )


class InvoiceFetchRun(Base):
    """One execution of a source."""

    __tablename__ = "invoice_fetch_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("invoice_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RunStatus.RUNNING.value)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    documents_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_matched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    log: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    browserbase_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    source: Mapped["InvoiceSource"] = relationship("InvoiceSource", back_populates="runs")


# --- Pydantic schemas ---


class InvoiceSourceCreate(BaseModel):
    name: str
    kind: SourceKind
    enabled: bool = True
    login_url: str | None = None
    op_username_ref: str | None = None
    op_password_ref: str | None = None
    instructions: str | None = None
    gmail_query: str | None = None


class InvoiceSourceUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    login_url: str | None = None
    op_username_ref: str | None = None
    op_password_ref: str | None = None
    instructions: str | None = None
    gmail_query: str | None = None


class InvoiceSourceResponse(BaseModel):
    id: int
    name: str
    kind: str
    enabled: bool
    login_url: str | None = None
    op_username_ref: str | None = None
    op_password_ref: str | None = None
    instructions: str | None = None
    gmail_query: str | None = None
    gmail_email: str | None = None
    gmail_connected: bool = False
    last_run_at: datetime | None = None
    last_status: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class InvoiceFetchRunResponse(BaseModel):
    id: int
    source_id: int
    source_name: str | None = None
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    documents_found: int
    documents_new: int
    documents_matched: int
    log: str | None = None
    error: str | None = None
    browserbase_session_id: str | None = None

    class Config:
        from_attributes = True
