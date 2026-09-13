"""Run invoice sources: fetch files, ingest as documents, OCR, and match to transactions."""

import asyncio
import traceback
from datetime import datetime

from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..logger import logger
from ..models import (
    Document,
    InvoiceFetchRun,
    InvoiceSource,
    RunStatus,
    SourceKind,
    get_provider_settings,
    require_provider,
)
from ..routes.events import broadcast_event
from .document_ingest import ingest_document_bytes
from .document_matcher import match_documents_to_transactions

FETCH_INTERVAL_SECONDS = 24 * 60 * 60
_running: set[int] = set()


def is_running(source_id: int) -> bool:
    return source_id in _running


async def run_source(source_id: int) -> None:
    """Execute one source end-to-end. Safe to schedule with asyncio.create_task."""
    if source_id in _running:
        return
    _running.add(source_id)
    db: Session = SessionLocal()
    lines: list[str] = []

    def log(line: str) -> None:
        lines.append(f"{datetime.now().strftime('%H:%M:%S')} {line}")
        logger.info(f"[fetch {source_id}] {line}")

    run = InvoiceFetchRun(source_id=source_id)
    try:
        source = db.query(InvoiceSource).get(source_id)
        if not source:
            return
        db.add(run)
        db.commit()
        db.refresh(run)
        broadcast_event("fetch_started", {"source_id": source.id, "source_name": source.name,
                                          "message": f"Fetching invoices from {source.name}..."})

        providers = get_provider_settings(db)
        if source.kind == SourceKind.WEBSITE.value:
            require_provider(providers, "browserbase_api_key", "onepassword_service_account_token",
                             "llm_model", "llm_api_key")
            if not source.login_url or not source.op_username_ref or not source.op_password_ref:
                raise RuntimeError(
                    "Website source needs a login URL and 1Password username + password references"
                )
            from .website_fetcher import fetch_website_invoices

            def on_session(sid: str) -> None:
                run.browserbase_session_id = sid
                db.commit()

            files = await fetch_website_invoices(
                providers=providers, login_url=source.login_url,
                op_username_ref=source.op_username_ref, op_password_ref=source.op_password_ref,
                op_totp_ref=source.op_totp_ref,
                instructions=source.instructions, log=log, on_session=on_session,
            )
        else:
            if not source.gmail_token:
                raise RuntimeError("Gmail source is not connected yet")
            from .gmail_fetcher import fetch_pdf_attachments

            files = await asyncio.to_thread(fetch_pdf_attachments, source.gmail_token, source.gmail_query, log)

        run.documents_found = len(files)
        new_ids: list[int] = []
        for filename, data, origin_ref in files:
            if db.query(Document.id).filter(Document.origin_ref == origin_ref).first():
                continue
            doc, created = ingest_document_bytes(
                db, data, filename, "application/pdf", "purchase_invoice",
                source_id=source.id, origin_ref=origin_ref,
            )
            if created:
                new_ids.append(doc.id)
        run.documents_new = len(new_ids)
        log(f"{len(new_ids)} new document(s) stored")

        if new_ids:
            from ..routes.documents import _process_document

            for doc_id in new_ids:
                await asyncio.to_thread(_process_document, doc_id, settings.database_url)
            log("OCR + extraction complete")
            run.documents_matched = match_documents_to_transactions(db)
            log(f"{run.documents_matched} matched to transactions")

        run.status = RunStatus.COMPLETED.value
        source.last_status = RunStatus.COMPLETED.value
        broadcast_event("fetch_completed", {
            "source_id": source.id, "source_name": source.name, "new": run.documents_new,
            "matched": run.documents_matched,
            "message": f"{source.name}: {run.documents_new} new invoice(s), {run.documents_matched} matched",
        })
    except Exception as e:  # noqa: BLE001
        logger.error(f"Fetch run for source {source_id} failed: {e}\n{traceback.format_exc()}")
        run.status = RunStatus.FAILED.value
        run.error = str(e)
        source = db.query(InvoiceSource).get(source_id)
        if source:
            source.last_status = RunStatus.FAILED.value
            broadcast_event("fetch_error", {"source_id": source.id, "source_name": source.name,
                                            "message": f"{source.name} fetch failed: {e}"})
    finally:
        try:
            run.finished_at = datetime.now()
            run.log = "\n".join(lines)
            source = db.query(InvoiceSource).get(source_id)
            if source:
                source.last_run_at = run.finished_at
            db.commit()
        finally:
            db.close()
            _running.discard(source_id)


async def periodic_fetch() -> None:
    """Run every enabled source once a day."""
    await asyncio.sleep(30)
    while True:
        db = SessionLocal()
        try:
            ids = [s.id for s in db.query(InvoiceSource).filter(InvoiceSource.enabled.is_(True)).all()]
        finally:
            db.close()
        for sid in ids:
            try:
                await run_source(sid)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Scheduled fetch failed for source {sid}: {e}")
        await asyncio.sleep(FETCH_INTERVAL_SECONDS)
