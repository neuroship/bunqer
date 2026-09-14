"""Invoice source management, fetch runs, and Gmail OAuth."""

import asyncio
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..database import get_db
from ..logger import logger
from ..models import (
    Document,
    DocumentResponse,
    InvoiceFetchRun,
    InvoiceFetchRunResponse,
    InvoiceSource,
    InvoiceSourceCreate,
    InvoiceSourceResponse,
    InvoiceSourceUpdate,
    RunRequest,
    RunStatus,
    SourceKind,
    get_provider_settings,
    require_provider,
)
from ..services import gmail_fetcher, invoice_email, s3
from ..services.invoice_fetch_runner import is_running, run_all, run_source

router = APIRouter(prefix="/invoice-sources", tags=["invoice-sources"])
# Google redirects the browser here without our JWT, so this router is mounted without auth.
public_router = APIRouter(prefix="/invoice-sources", tags=["invoice-sources"])

GMAIL_CALLBACK_PATH = "/invoice-sources/gmail/callback"


class EmailRunRequest(BaseModel):
    to: str


class EmailRunsRequest(BaseModel):
    to: str
    run_ids: list[int]
    label: str  # e.g. "Q3 2026", used in the subject


def _to_response(src: InvoiceSource) -> InvoiceSourceResponse:
    resp = InvoiceSourceResponse.model_validate(src)
    resp.gmail_connected = bool(src.gmail_token)
    resp.gmail_can_send = resp.gmail_connected and gmail_fetcher.can_send(src.gmail_token)
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
        collect_description=data.collect_description,
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
async def trigger_run(
    source_id: int, period: RunRequest | None = None, db: Session = Depends(get_db)
):
    src = db.query(InvoiceSource).get(source_id)
    if not src:
        raise HTTPException(404, "Source not found")
    if is_running(source_id):
        raise HTTPException(409, "This source is already running")
    period = period or RunRequest()
    if period.date_from and period.date_to and period.date_from > period.date_to:
        raise HTTPException(400, "date_from must be on or before date_to")
    asyncio.create_task(run_source(source_id, period.date_from, period.date_to))
    return {"detail": f"Fetch started for {src.name}"}


@router.post("/run-all")
async def trigger_run_all(period: RunRequest, db: Session = Depends(get_db)):
    """Run every source sequentially for one period (e.g. a quarter)."""
    if not period.date_from or not period.date_to:
        raise HTTPException(400, "date_from and date_to are required")
    if period.date_from > period.date_to:
        raise HTTPException(400, "date_from must be on or before date_to")
    count = db.query(InvoiceSource).count()
    if not count:
        raise HTTPException(400, "No sources configured")
    asyncio.create_task(run_all(period.date_from, period.date_to))
    return {"detail": f"Collecting {period.date_from} to {period.date_to} from {count} source(s)"}


@router.get("/runs", response_model=list[InvoiceFetchRunResponse])
async def list_runs(
    source_id: int | None = None, limit: int = Query(30, le=200), db: Session = Depends(get_db)
):
    q = db.query(InvoiceFetchRun)
    if source_id:
        q = q.filter(InvoiceFetchRun.source_id == source_id)
    runs = q.order_by(InvoiceFetchRun.started_at.desc()).limit(limit).all()
    return [_run_to_response(r) for r in runs]


@router.delete("/runs/cleanup")
async def cleanup_runs(db: Session = Depends(get_db)):
    """Delete finished runs that failed or stored no documents."""
    runs = (
        db.query(InvoiceFetchRun)
        .filter(InvoiceFetchRun.status != RunStatus.RUNNING.value)
        .filter((InvoiceFetchRun.status == RunStatus.FAILED.value) | (InvoiceFetchRun.documents_new == 0))
        .all()
    )
    doomed = [r for r in runs if not is_running(r.source_id) or r.status != RunStatus.RUNNING.value]
    for r in doomed:
        db.delete(r)
    db.commit()
    return {"deleted": len(doomed)}


@router.delete("/runs/{run_id}")
async def delete_run(run_id: int, db: Session = Depends(get_db)):
    """Delete one finished run. Its documents stay (their run link is cleared)."""
    run = db.query(InvoiceFetchRun).get(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status == RunStatus.RUNNING.value:
        raise HTTPException(409, "Run is still in progress")
    db.delete(run)
    db.commit()
    return {"detail": "Run deleted"}


@router.get("/runs/{run_id}/documents", response_model=list[DocumentResponse])
async def run_documents(run_id: int, db: Session = Depends(get_db)):
    """Documents collected by one fetch run."""
    from .documents import _doc_to_response

    docs = (
        db.query(Document)
        .options(selectinload(Document.transactions))
        .filter(Document.run_id == run_id)
        .order_by(Document.invoice_date.desc().nullslast(), Document.id.desc())
        .all()
    )
    return [_doc_to_response(d) for d in docs]


@router.get("/email/recipient")
async def email_recipient(db: Session = Depends(get_db)):
    """The saved address invoices are emailed to, plus which Gmail source will send them.
    `reconnect` names a connected source that lacks the send permission."""
    sender, reconnect = invoice_email.find_sender(db)
    return {
        "to": invoice_email.get_recipient(db),
        "sender": sender.gmail_email if sender else None,
        "reconnect": {"id": reconnect.id, "name": reconnect.name} if reconnect else None,
    }


@router.put("/email/recipient")
async def save_email_recipient(body: EmailRunRequest, db: Session = Depends(get_db)):
    """Save the address invoices are emailed to."""
    to = invoice_email.clean_address(body.to)
    invoice_email.remember_recipient(db, to)
    return {"to": to}


async def _email_documents(db: Session, to: str, subject: str, intro: str, docs: list[Document]) -> dict:
    """Send documents as attachments via the first Gmail source that can send."""
    if not docs:
        raise HTTPException(400, "No documents to send")
    sender = invoice_email.pick_sender(db)
    text = f"{intro}\n\n" + "\n".join(f"- {d.filename}" for d in docs)
    try:
        files = await asyncio.to_thread(
            lambda: [(d.filename, s3.download_document(d.s3_key), d.content_type) for d in docs]
        )
        sent = await asyncio.to_thread(gmail_fetcher.send_files, sender.gmail_token, to, subject, text, files)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Emailing '{subject}' failed: {e}")
        raise HTTPException(502, f"Sending failed: {e}")

    invoice_email.remember_recipient(db, to)
    return {"detail": f"Sent {len(docs)} document(s) to {to} in {sent} email(s)"}


@router.post("/runs/email")
async def email_runs(body: EmailRunsRequest, db: Session = Depends(get_db)):
    """Send the documents of several runs (one quarter) in one go."""
    to = invoice_email.clean_address(body.to)
    if not body.run_ids:
        raise HTTPException(400, "No runs selected")
    docs = (
        db.query(Document)
        .filter(Document.run_id.in_(body.run_ids))
        .order_by(Document.run_id, Document.id)
        .all()
    )
    if not docs:
        raise HTTPException(400, "These runs have no documents to send")
    intro = f"{len(docs)} document(s) collected for {body.label} across {len(body.run_ids)} run(s):"
    return await _email_documents(db, to, f"Invoices: {body.label}", intro, docs)


@router.post("/runs/{run_id}/email")
async def email_run(run_id: int, body: EmailRunRequest, db: Session = Depends(get_db)):
    """Send every document of one run as attachments, via the first Gmail source that can send."""
    to = invoice_email.clean_address(body.to)
    run = db.query(InvoiceFetchRun).get(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    docs = db.query(Document).filter(Document.run_id == run_id).order_by(Document.id).all()
    if not docs:
        raise HTTPException(400, "This run has no documents to send")

    period = f"{run.date_from} to {run.date_to}" if run.date_from and run.date_to else "run"
    source_name = run.source.name if run.source else "auto-fetch"
    intro = f"{len(docs)} document(s) collected from {source_name} ({period}):"
    return await _email_documents(db, to, f"Invoices: {source_name}, {period}", intro, docs)


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

    def fail(reason: str):
        logger.error(f"Gmail OAuth callback failed: {reason}")
        return RedirectResponse(f"{frontend}?gmail=error&reason={quote(reason[:200])}")

    if error:
        return fail(f"Google returned: {error}")
    if not code or not state:
        return fail("Missing code or state in callback")
    try:
        payload = jwt.decode(state, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        source_id = int(payload["source_id"])
    except (JWTError, KeyError, ValueError):
        return fail("Login state expired or invalid, start the connection again")

    src = db.query(InvoiceSource).get(source_id)
    if not src:
        return fail("Source no longer exists")
    try:
        p = _gmail_config(db)
        token_json, email = gmail_fetcher.exchange_code(
            p["google_client_id"], p["google_client_secret"], p["google_redirect_uri"], code
        )
    except Exception as e:  # noqa: BLE001
        return fail(f"Token exchange failed: {e}")

    src.gmail_token = token_json
    src.gmail_email = email
    db.commit()
    logger.info(f"Gmail connected for source {src.id} ({email})")
    return RedirectResponse(f"{frontend}?gmail=connected")


@router.post("/{source_id}/gmail/preview")
async def gmail_preview(source_id: int, period: RunRequest, db: Session = Depends(get_db)):
    """Show the generated Gmail query and the emails a run for this period would collect."""
    src = db.query(InvoiceSource).get(source_id)
    if not src or src.kind != SourceKind.GMAIL.value:
        raise HTTPException(404, "Gmail source not found")
    if not src.gmail_token:
        raise HTTPException(400, "Gmail is not connected for this source")
    providers = get_provider_settings(db)
    try:
        return await gmail_fetcher.preview(
            providers, src.gmail_token, src.collect_description, src.gmail_query, period.date_from, period.date_to
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))


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
