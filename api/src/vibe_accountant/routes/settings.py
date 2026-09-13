"""Company settings endpoints."""

import base64

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..logger import logger
from ..models import (
    PROVIDER_KEYS,
    CompanySettings,
    CompanySettingsResponse,
    CompanySettingsUpdate,
    ProviderSetting,
    ProviderSettingsUpdate,
    get_provider_settings,
)

router = APIRouter(prefix="/settings", tags=["settings"])

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/svg+xml"}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2MB


def _get_or_create(db: Session) -> CompanySettings:
    """Get the singleton company settings row, creating it if needed."""
    settings = db.query(CompanySettings).first()
    if not settings:
        settings = CompanySettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@router.get("/company", response_model=CompanySettingsResponse)
async def get_company_settings(db: Session = Depends(get_db)):
    """Get company settings."""
    settings = _get_or_create(db)
    response = CompanySettingsResponse.model_validate(settings)
    response.has_logo = bool(settings.logo_base64)
    return response


@router.put("/company", response_model=CompanySettingsResponse)
async def update_company_settings(
    data: CompanySettingsUpdate, db: Session = Depends(get_db)
):
    """Update company settings."""
    settings = _get_or_create(db)
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(settings, field, value)
    db.commit()
    db.refresh(settings)
    logger.info("Updated company settings")
    response = CompanySettingsResponse.model_validate(settings)
    response.has_logo = bool(settings.logo_base64)
    return response


@router.post("/company/logo", response_model=CompanySettingsResponse)
async def upload_company_logo(
    file: UploadFile = File(...), db: Session = Depends(get_db)
):
    """Upload company logo (PNG, JPEG, WebP, or SVG, max 2MB)."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}",
        )

    contents = await file.read()
    if len(contents) > MAX_LOGO_SIZE:
        raise HTTPException(status_code=400, detail="Logo must be under 2MB")

    b64 = base64.b64encode(contents).decode("utf-8")
    data_uri = f"data:{file.content_type};base64,{b64}"

    settings = _get_or_create(db)
    settings.logo_base64 = data_uri
    db.commit()
    db.refresh(settings)
    logger.info("Uploaded company logo")
    response = CompanySettingsResponse.model_validate(settings)
    response.has_logo = True
    return response


@router.delete("/company/logo", response_model=CompanySettingsResponse)
async def delete_company_logo(db: Session = Depends(get_db)):
    """Remove company logo."""
    settings = _get_or_create(db)
    settings.logo_base64 = None
    db.commit()
    db.refresh(settings)
    response = CompanySettingsResponse.model_validate(settings)
    response.has_logo = False
    return response


# --- Provider credentials (Browserbase, 1Password, LLM, Google) ---


def _mask(value: str) -> str:
    return "••••" + value[-4:] if len(value) > 4 else "••••"


@router.get("/providers")
async def get_provider_settings_route(db: Session = Depends(get_db)):
    """Provider settings with secrets masked."""
    values = get_provider_settings(db)
    out = {}
    for key, is_secret in PROVIDER_KEYS.items():
        val = values.get(key) or ""
        out[key] = {"set": bool(val), "value": _mask(val) if (is_secret and val) else val}
    return out


def _normalize_secret(value: str | None) -> str | None:
    """Trim, and tolerate a pasted `ENV_NAME=value` line or surrounding quotes."""
    v = (value or "").strip()
    name, sep, rest = v.partition("=")
    if sep and name.isupper() and "_" in name and rest:
        v = rest.strip()
    return v.strip("\"'") or None


def _validate_llm_model(model: str) -> None:
    """Stagehand only accepts a fixed list of provider/model ids; fail early with a hint."""
    import re

    from stagehand._generated.models import ModelConfig

    try:
        ModelConfig(model_name=model)
    except Exception as e:
        match = re.search(r"\^anthropic\\/\((.*?)\)\$", str(e))
        ids = match.group(1).replace("\\", "").split("|") if match else []
        hint = f" Supported Anthropic ids: {', '.join(ids[-6:])}." if ids else ""
        raise HTTPException(
            400, f"LLM model '{model}' is not supported by Stagehand. Use provider/model form.{hint}"
        )


@router.put("/providers")
async def update_provider_settings_route(data: ProviderSettingsUpdate, db: Session = Depends(get_db)):
    """Update provider settings. Only keys present in the body change; empty string clears."""
    updates = {k: _normalize_secret(v) for k, v in data.model_dump(exclude_unset=True).items()}
    if updates.get("llm_model"):
        _validate_llm_model(updates["llm_model"])
    for key, value in updates.items():
        row = db.query(ProviderSetting).get(key)
        if not row:
            row = ProviderSetting(key=key)
            db.add(row)
        row.value = value
    db.commit()
    logger.info("Updated provider settings")
    return await get_provider_settings_route(db)
