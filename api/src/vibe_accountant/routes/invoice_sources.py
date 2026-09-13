"""Invoice source management, fetch runs, and Gmail OAuth."""

import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..logger import logger
from ..models import (
    InvoiceFetchRun,
    InvoiceFetchRunResponse,
    InvoiceSource,
    InvoiceSourceCreate,
    InvoiceSourceResponse,
    InvoiceSourceUpdate,
    SourceKind,
    get_provider_settings,
    require_provider,
)
from ..services import gmail_fetcher
from ..services.invoice_fetch_runner import is_running, run_source

router = APIRouter(prefix="/invoice-sources", tags=["invoice-sources"])
# Google redirects the browser here without our JWT, so this router is mounted without auth.
public_router = APIRouter(prefix="/invoice-sources", tags=["invoice-sources"])

GMAIL_CALLBACK_PATH = "/invoice-sources/gmail/callback"


def _to_response(src: InvoiceSource) -> InvoiceSourceResponse:
    resp = InvoiceSourceResponse.model_validate(src)
    resp.gmail_connected = bool(src.gmail_token)
    if is_running(src.id):
        resp.last_status = "running"
    return resp


def _run_to_response(run: InvoiceFetchRun) -> InvoiceFetchRunResponse:
    resp = InvoiceFetchRunResponse.model_validate(run)
    resp.source_name = run.source.name if run.source else None
    return resp


@router.get("", response_model=list[InvoiceSourceResponse])
async def list_sources(db: Session = Depends(get_db)):
    sources = db.query(InvoiceSource).order_by(InvoiceSource.created_at.desc()).all()
    return [_to_response(s) for s in sources]


@router.post("", response_model=InvoiceSourceResponse)
async def create_source(data: InvoiceSourceCreate, db: Session = Depends(get_db)):
    src = InvoiceSource(
        name=data.name,
        kind=data.kind.value,
        enabled=data.enabled,
        login_url=data.login_url,
        op_username_ref=data.op_username_ref,
        op_password_ref=data.op_password_ref,
        op_totp_ref=data.op_totp_ref,
        instructions=data.instructions,
        gmail_query=data.gmail_query,
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    logger.info(f"Created invoice source {src.name} ({src.kind})")
    return _to_response(src)


@router.patch("/{source_id}", response_model=InvoiceSourceResponse)
async def update_source(source_id: int, data: InvoiceSourceUpdate, db: Session = Depends(get_db)):
    src = db.query(InvoiceSource).get(source_id)
    if not src:
        raise HTTPException(404, "Source not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(src, field, value)
    db.commit()
    db.refresh(src)
    return _to_response(src)


@router.delete("/{source_id}")
async def delete_source(source_id: int, db: Session = Depends(get_db)):
    src = db.query(InvoiceSource).get(source_id)
    if not src:
        raise HTTPException(404, "Source not found")
    db.delete(src)
    db.commit()
    return {"detail": "Source deleted"}


@router.post("/{source_id}/run")
async def trigger_run(source_id: int, db: Session = Depends(get_db)):
    src = db.query(InvoiceSource).get(source_id)
    if not src:
        raise HTTPException(404, "Source not found")
    if is_running(source_id):
        raise HTTPException(409, "This source is already running")
    asyncio.create_task(run_source(source_id))
    return {"detail": f"Fetch started for {src.name}"}


@router.get("/runs", response_model=list[InvoiceFetchRunResponse])
async def list_runs(
    source_id: int | None = None, limit: int = Query(30, le=200), db: Session = Depends(get_db)
):
    q = db.query(InvoiceFetchRun)
    if source_id:
        q = q.filter(InvoiceFetchRun.source_id == source_id)
    runs = q.order_by(InvoiceFetchRun.started_at.desc()).limit(limit).all()
    return [_run_to_response(r) for r in runs]


# --- Gmail OAuth ---


def _gmail_config(db: Session) -> dict[str, str]:
    providers = get_provider_settings(db)
    require_provider(providers, "google_client_id", "google_client_secret", "google_redirect_uri")
    return providers


@router.get("/{source_id}/gmail/auth-url")
async def gmail_auth_url(source_id: int, db: Session = Depends(get_db)):
    src = db.query(InvoiceSource).get(source_id)
    if not src or src.kind != SourceKind.GMAIL.value:
        raise HTTPException(404, "Gmail source not found")
    try:
        p = _gmail_config(db)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    state = jwt.encode(
        {"source_id": source_id, "exp": datetime.utcnow() + timedelta(minutes=15)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    url = gmail_fetcher.build_auth_url(
        p["google_client_id"], p["google_client_secret"], p["google_redirect_uri"], state
    )
    return {"url": url}


@public_router.get("/gmail/callback")
async def gmail_callback(
    code: str | None = None, state: str | None = None, error: str | None = None,
    db: Session = Depends(get_db),
):
    frontend = f"{settings.frontend_url}/#fetchers"
    if error or not code or not state:
        return RedirectResponse(f"{frontend}?gmail=error")
    try:
        payload = jwt.decode(state, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        source_id = int(payload["source_id"])
    except (JWTError, KeyError, ValueError):
        return RedirectResponse(f"{frontend}?gmail=error")

    src = db.query(InvoiceSource).get(source_id)
    if not src:
        return RedirectResponse(f"{frontend}?gmail=error")
    try:
        p = _gmail_config(db)
        token_json, email = gmail_fetcher.exchange_code(
            p["google_client_id"], p["google_client_secret"], p["google_redirect_uri"], code
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"Gmail OAuth exchange failed: {e}")
        return RedirectResponse(f"{frontend}?gmail=error")

    src.gmail_token = token_json
    src.gmail_email = email
    db.commit()
    logger.info(f"Gmail connected for source {src.id} ({email})")
    return RedirectResponse(f"{frontend}?gmail=connected")


@router.post("/{source_id}/gmail/disconnect", response_model=InvoiceSourceResponse)
async def gmail_disconnect(source_id: int, db: Session = Depends(get_db)):
    src = db.query(InvoiceSource).get(source_id)
    if not src:
        raise HTTPException(404, "Source not found")
    src.gmail_token = None
    src.gmail_email = None
    db.commit()
    db.refresh(src)
    return _to_response(src)
