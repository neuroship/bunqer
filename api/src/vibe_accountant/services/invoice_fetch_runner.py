"""Run invoice sources: fetch files, ingest as documents, OCR, and match to transactions."""

import asyncio
import hashlib
import traceback
from datetime import date, datetime, timedelta

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

DEFAULT_LOOKBACK_DAYS = 90
OVERLAP_DAYS = 7
_running: set[int] = set()


def is_running(source_id: int) -> bool:
    return source_id in _running


def default_period(db: Session, source_id: int) -> tuple[date, date]:
    """Window for a run without explicit dates: since the last completed run, with overlap."""
    today = date.today()
    last = (
        db.query(InvoiceFetchRun)
        .filter(InvoiceFetchRun.source_id == source_id, InvoiceFetchRun.status == RunStatus.COMPLETED.value)
        .order_by(InvoiceFetchRun.started_at.desc())
        .first()
    )
    if last and (last.date_to or last.started_at):
        anchor = last.date_to or last.started_at.date()
        return anchor - timedelta(days=OVERLAP_DAYS), today
    return today - timedelta(days=DEFAULT_LOOKBACK_DAYS), today


async def run_source(source_id: int, date_from: date | None = None, date_to: date | None = None) -> None:
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
        d_from, d_to = default_period(db, source_id)
        run.date_from = date_from or d_from
        run.date_to = date_to or d_to
        db.add(run)
        db.commit()
        db.refresh(run)
        log(f"Period {run.date_from} to {run.date_to}")
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
                op_totp_ref=source.op_totp_ref, date_from=run.date_from, date_to=run.date_to,
                instructions=source.instructions, log=log, on_session=on_session,
            )
        else:
            if not source.gmail_token:
                raise RuntimeError("Gmail source is not connected yet")
            require_provider(providers, "llm_model", "llm_api_key")
            from .gmail_fetcher import fetch_invoices

            files = await fetch_invoices(
                providers, source.gmail_token, source.collect_description, source.gmail_query,
                run.date_from, run.date_to, log,
            )

        run.documents_found = len(files)
        new_ids: list[int] = []
        for filename, data, origin_ref in files:
            # Same bytes = same document. Rendered email bodies differ per render, so for
            # those fall back to the origin reference (portal/attachment refs are not trusted:
            # an earlier mispairing could hide a file that was never stored).
            doc = db.query(Document).filter(Document.content_hash == hashlib.sha256(data).hexdigest()).first()
            if doc is None and origin_ref.endswith(":body"):
                doc = db.query(Document).filter(Document.origin_ref == origin_ref).first()
            if doc is None:
                doc, created = ingest_document_bytes(
                    db, data, filename, "application/pdf", "purchase_invoice",
                    source_id=source.id, origin_ref=origin_ref, run_id=run.id,
                )
                if created:
                    new_ids.append(doc.id)
            if doc not in run.documents:
                run.documents.append(doc)  # the run lists everything it found, new or already stored
        db.commit()
        run.documents_new = len(new_ids)
        run_doc_ids = {d.id for d in run.documents}
        log(f"{len(new_ids)} new document(s) stored, {len(run_doc_ids)} listed for this run")

        if new_ids:
            from ..routes.documents import _process_document

            for doc_id in new_ids:
                await asyncio.to_thread(_process_document, doc_id, settings.database_url)
            log("OCR + extraction complete")
            report = match_documents_to_transactions(db)
            for amb in report.ambiguous:
                if amb.document.id in run_doc_ids:
                    opts = ", ".join(
                        f"{c.txn.transaction_date.date()} {c.txn.amount}" for c in amb.candidates
                    )
                    log(f"Needs a manual pick: {amb.document.filename} could be {opts}")
        run.documents_matched = (
            db.query(Document).filter(Document.id.in_(run_doc_ids), Document.transactions.any()).count()
        )
        log(f"{run.documents_matched} of this run's documents matched to transactions")

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


def _mark_interrupted_runs(db: Session) -> None:
    """Runs left 'running' by a restart can never finish; close them out."""
    stale = db.query(InvoiceFetchRun).filter(InvoiceFetchRun.status == RunStatus.RUNNING.value).all()
    for run in stale:
        run.status = RunStatus.FAILED.value
        run.error = "Interrupted by an application restart"
        run.finished_at = datetime.now()
        if run.source:
            run.source.last_status = RunStatus.FAILED.value
    if stale:
        db.commit()
        logger.warning(f"Marked {len(stale)} interrupted fetch run(s) as failed")


async def run_all(date_from: date | None, date_to: date | None) -> None:
    """Run every source one after another for the same period."""
    db = SessionLocal()
    try:
        ids = [s.id for s in db.query(InvoiceSource).order_by(InvoiceSource.id).all()]
    finally:
        db.close()
    for sid in ids:
        try:
            await run_source(sid, date_from, date_to)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Run-all failed for source {sid}: {e}")


async def close_interrupted_runs() -> None:
    """On startup, close runs that a restart left in 'running'. No scheduled runs: all manual."""
    await asyncio.sleep(5)
    db = SessionLocal()
    try:
        _mark_interrupted_runs(db)
    finally:
        db.close()
