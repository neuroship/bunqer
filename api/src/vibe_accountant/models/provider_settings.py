"""Key/value store for third-party provider credentials configured from the UI."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from .base import Base

# key -> is_secret. Secrets are masked in API responses.
PROVIDER_KEYS: dict[str, bool] = {
    "browserbase_api_key": True,
    "onepassword_service_account_token": True,
    "llm_model": False,
    "llm_api_key": True,
    "google_client_id": False,
    "google_client_secret": True,
    "google_redirect_uri": False,
}

PROVIDER_DEFAULTS: dict[str, str] = {
    "llm_model": "anthropic/claude-sonnet-5",
}


class ProviderSetting(Base):
    """One row per provider setting key."""

    __tablename__ = "provider_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


def get_provider_settings(db: Session) -> dict[str, str]:
    """Return all provider settings as a dict, with defaults for unset keys."""
    values = dict(PROVIDER_DEFAULTS)
    for row in db.query(ProviderSetting).all():
        if row.value:
            values[row.key] = row.value
    return values


def require_provider(values: dict[str, str], *keys: str) -> None:
    """Raise a clear error if any required provider key is missing."""
    missing = [k for k in keys if not values.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing provider settings: {', '.join(missing)}. Configure them in Settings > Providers."
        )


class ProviderSettingsUpdate(BaseModel):
    """Partial update. Empty string clears a key."""

    browserbase_api_key: str | None = None
    onepassword_service_account_token: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
