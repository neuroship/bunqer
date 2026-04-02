"""WebAuthn credential model for passkey authentication."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, LargeBinary, String, Text, text

from .base import Base


class WebAuthnCredential(Base):
    """Stored WebAuthn credential (passkey)."""

    __tablename__ = "webauthn_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    credential_id = Column(LargeBinary, nullable=False, unique=True)
    public_key = Column(LargeBinary, nullable=False)
    sign_count = Column(Integer, nullable=False, default=0)
    # Human-readable name for the passkey (e.g. "MacBook Pro Touch ID")
    name = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))


class WebAuthnCredentialResponse(BaseModel):
    """Response schema for a registered passkey."""

    id: int
    name: str | None
    created_at: datetime

    class Config:
        from_attributes = True
