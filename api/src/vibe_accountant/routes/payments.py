"""Payment endpoints (draft payments via bunq SDK)."""

import concurrent.futures
import traceback
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from bunq.sdk.exception.api_exception import ApiException
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..bunq_client import BunqClient
from ..database import get_db
from ..logger import logger
from ..models import Account, Integration, Transaction
from ..services import approval_watcher
from .passkeys import PasskeyAssertion, verify_passkey_assertion

RecurrenceUnit = Literal["HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"]

router = APIRouter(prefix="/payments", tags=["payments"])


def _raise_bunq_http_error(e: Exception, action: str) -> None:
    """Translate a bunq SDK error into an HTTPException with a status the edge
    won't mask. Cloudflare replaces any origin 5xx with its own error page, so a
    bunq client error (4xx, e.g. invalid IBAN) returned as 502 hides the real
    message. Map bunq 4xx -> 400 so the actual reason reaches the user; keep 5xx
    as 502.
    """
    if isinstance(e, ApiException) and 400 <= e.response_code < 500:
        message = str(e).split("Error message:", 1)[-1].strip() or str(e)
        raise HTTPException(status_code=400, detail=f"Bunq rejected the {action}: {message}")
    raise HTTPException(status_code=502, detail=f"Bunq {action} failed: {e}")


class DraftPaymentRequest(BaseModel):
    """Request to create a bunq draft payment."""

    account_id: int = Field(..., description="Local Account ID (DB id) to send from")
    amount: Decimal = Field(..., gt=0, description="Positive amount to send")
    currency: str = Field("EUR", min_length=3, max_length=3)
    counterparty_iban: str = Field(..., min_length=4, max_length=50)
    counterparty_name: str = Field(..., min_length=1, max_length=255)
    description: str = Field("", max_length=140)


class DraftPaymentResponse(BaseModel):
    """Response after creating a draft payment."""

    draft_payment_id: int
    account_id: int
    monetary_account_id: int
    amount: str
    currency: str
    counterparty_iban: str
    counterparty_name: str
    description: str
    status: str = "AWAITING_APPROVAL"
    message: str = "Draft payment created. Approve it in bunqer or the bunq app to execute."


class CounterpartySuggestion(BaseModel):
    """Counterparty suggestion for autocomplete."""

    name: str
    iban: str
    transaction_count: int


@router.get("/counterparties", response_model=list[CounterpartySuggestion])
def list_counterparties(db: Session = Depends(get_db), limit: int = 200):
    """List unique past counterparties (name + IBAN) sorted by usage frequency.

    Pulls from Transaction.receiver_name/receiver_iban for outgoing payments
    so the suggestions match what the user typically pays.
    """
    rows = (
        db.query(
            Transaction.receiver_name.label("name"),
            Transaction.receiver_iban.label("iban"),
            func.count(Transaction.id).label("cnt"),
        )
        .filter(Transaction.amount < 0)
        .filter(Transaction.receiver_iban.isnot(None))
        .filter(Transaction.receiver_iban != "")
        .filter(Transaction.receiver_name.isnot(None))
        .filter(Transaction.receiver_name != "")
        .group_by(Transaction.receiver_name, Transaction.receiver_iban)
        .order_by(func.count(Transaction.id).desc())
        .limit(limit)
        .all()
    )
    return [
        CounterpartySuggestion(name=r.name, iban=r.iban, transaction_count=r.cnt)
        for r in rows
    ]


@router.post("/draft", response_model=DraftPaymentResponse)
def create_draft_payment(payload: DraftPaymentRequest, db: Session = Depends(get_db)):
    """Create a bunq draft payment from a local account. Approval happens under pending drafts or in the bunq app."""
    logger.info(
        f"POST /payments/draft: account_id={payload.account_id}, "
        f"amount={payload.amount} {payload.currency}, to={payload.counterparty_name}"
    )

    account, bunq_client = _get_account_and_client(db, payload.account_id)

    iban = payload.counterparty_iban.replace(" ", "").upper()
    amount_str = f"{payload.amount:.2f}"

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(
                bunq_client.create_draft_payment,
                monetary_account_id=account.monetary_account_id,
                amount_value=amount_str,
                currency=payload.currency,
                counterparty_iban=iban,
                counterparty_name=payload.counterparty_name,
                description=payload.description or "",
            )
            draft_id = future.result(timeout=45)
    except concurrent.futures.TimeoutError:
        logger.error("Bunq draft payment call timed out after 45s")
        raise HTTPException(
            status_code=504, detail="Bunq draft payment timed out after 45s"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create draft payment: {e}")
        logger.error(traceback.format_exc())
        _raise_bunq_http_error(e, "draft payment")
    logger.info(f"POST /payments/draft done: id={draft_id}")

    try:
        approval_watcher.refresh_pending_approvals(db)
    except Exception as e:
        logger.warning(f"Could not refresh pending approvals after create: {e}")

    return DraftPaymentResponse(
        draft_payment_id=draft_id,
        account_id=account.id,
        monetary_account_id=account.monetary_account_id,
        amount=amount_str,
        currency=payload.currency,
        counterparty_iban=iban,
        counterparty_name=payload.counterparty_name,
        description=payload.description or "",
    )


@router.get("/approvals/pending")
def list_pending_approvals(refresh: bool = False, db: Session = Depends(get_db)):
    """List draft payments and incoming requests awaiting approval across all bunq-linked accounts.

    Serves the background watcher's cache unless refresh=true (or nothing is cached yet).
    """
    if not refresh:
        cached = approval_watcher.get_cached_pending()
        if cached is not None:
            return cached
    try:
        return approval_watcher.refresh_pending_approvals(db)
    except Exception as e:
        logger.error(f"Failed to list pending approvals: {e}")
        _raise_bunq_http_error(e, "approvals listing")


class DraftActionRequest(BaseModel):
    """Reject a pending draft payment."""

    account_id: int = Field(..., description="Local Account ID (DB id) the draft belongs to")
    previous_updated_timestamp: str = Field(
        ..., description="The draft's 'updated' value as last seen; bunq refuses stale updates"
    )


class DraftApproveRequest(DraftActionRequest):
    """Approve a pending draft payment; requires a fresh passkey assertion."""

    passkey: PasskeyAssertion


def _respond_to_draft(
    db: Session, draft_id: int, payload: DraftActionRequest, new_status: str
) -> dict:
    account, bunq_client = _get_account_and_client(db, payload.account_id)
    try:
        bunq_client.update_draft_payment_status(
            monetary_account_id=account.monetary_account_id,
            draft_id=draft_id,
            status=new_status,
            previous_updated_timestamp=payload.previous_updated_timestamp,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set draft payment {draft_id} to {new_status}: {e}")
        logger.error(traceback.format_exc())
        _raise_bunq_http_error(e, f"draft {new_status.lower()}")

    _refresh_after(db, new_status)
    return {"draft_payment_id": draft_id, "status": new_status}


def _refresh_after(db: Session, action: str) -> None:
    try:
        approval_watcher.refresh_pending_approvals(db)
    except Exception as e:
        logger.warning(f"Could not refresh pending approvals after {action}: {e}")


@router.post("/draft/{draft_id}/approve")
def approve_draft_payment(
    draft_id: int, payload: DraftApproveRequest, db: Session = Depends(get_db)
):
    """Approve a pending draft payment. Money moves, so a passkey re-verification is required."""
    verify_passkey_assertion(db, payload.passkey, "verify")
    logger.info(f"POST /payments/draft/{draft_id}/approve: account_id={payload.account_id}")
    return _respond_to_draft(db, draft_id, payload, "ACCEPTED")


@router.post("/draft/{draft_id}/reject")
def reject_draft_payment(
    draft_id: int, payload: DraftActionRequest, db: Session = Depends(get_db)
):
    """Reject a pending draft payment."""
    logger.info(f"POST /payments/draft/{draft_id}/reject: account_id={payload.account_id}")
    return _respond_to_draft(db, draft_id, payload, "REJECTED")


class RequestActionRequest(BaseModel):
    """Reject an incoming payment request."""

    account_id: int = Field(..., description="Local Account ID (DB id) the request was sent to")


class RequestApproveRequest(RequestActionRequest):
    """Accept an incoming payment request; requires a fresh passkey assertion."""

    passkey: PasskeyAssertion


def _respond_to_request(
    db: Session, request_id: int, payload: RequestActionRequest, new_status: str
) -> dict:
    account, bunq_client = _get_account_and_client(db, payload.account_id)
    try:
        bunq_client.update_request_response_status(
            monetary_account_id=account.monetary_account_id,
            request_response_id=request_id,
            status=new_status,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to set request {request_id} to {new_status}: {e}")
        logger.error(traceback.format_exc())
        _raise_bunq_http_error(e, f"request {new_status.lower()}")

    _refresh_after(db, new_status)
    return {"request_response_id": request_id, "status": new_status}


@router.post("/request/{request_id}/approve")
def approve_request(
    request_id: int, payload: RequestApproveRequest, db: Session = Depends(get_db)
):
    """Accept an incoming payment request for the full amount. Requires passkey re-verification."""
    verify_passkey_assertion(db, payload.passkey, "verify")
    logger.info(f"POST /payments/request/{request_id}/approve: account_id={payload.account_id}")
    return _respond_to_request(db, request_id, payload, "ACCEPTED")


@router.post("/request/{request_id}/reject")
def reject_request(
    request_id: int, payload: RequestActionRequest, db: Session = Depends(get_db)
):
    """Reject an incoming payment request."""
    logger.info(f"POST /payments/request/{request_id}/reject: account_id={payload.account_id}")
    return _respond_to_request(db, request_id, payload, "REJECTED")


@router.get("/draft/{draft_id}")
def get_draft_payment(draft_id: int, account_id: int, db: Session = Depends(get_db)):
    """Get current status of a draft payment from bunq."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account or not account.monetary_account_id:
        raise HTTPException(status_code=404, detail="Account not found")

    integration = (
        db.query(Integration).filter(Integration.id == account.integration_id).first()
    )
    if not integration:
        raise HTTPException(status_code=400, detail="Integration not found")

    try:
        bunq_client = BunqClient(
            api_key=integration.secret_key,
            account_key=integration.name,
        )
        return bunq_client.get_draft_payment(account.monetary_account_id, draft_id)
    except Exception as e:
        logger.error(f"Failed to fetch draft payment {draft_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Bunq fetch failed: {e}")


class SchedulePaymentRequest(BaseModel):
    """Request to create a recurring scheduled payment."""

    account_id: int = Field(..., description="Local Account ID to send from")
    amount: Decimal = Field(..., gt=0)
    currency: str = Field("EUR", min_length=3, max_length=3)
    counterparty_iban: str = Field(..., min_length=4, max_length=50)
    counterparty_name: str = Field(..., min_length=1, max_length=255)
    description: str = Field("", max_length=140)
    time_start: datetime = Field(..., description="First execution datetime (UTC)")
    recurrence_unit: RecurrenceUnit = Field(...)
    recurrence_size: int = Field(1, ge=1, le=365)
    time_end: datetime | None = Field(None, description="Optional end datetime (UTC)")


class SchedulePaymentResponse(BaseModel):
    schedule_payment_id: int
    account_id: int
    monetary_account_id: int
    amount: str
    currency: str
    counterparty_iban: str
    counterparty_name: str
    description: str
    time_start: str
    time_end: str | None
    recurrence_unit: str
    recurrence_size: int


def _get_account_and_client(
    db: Session, account_id: int
) -> tuple[Account, BunqClient]:
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if not account.monetary_account_id:
        raise HTTPException(
            status_code=400,
            detail="Account is not linked to a bunq monetary account",
        )
    integration = (
        db.query(Integration).filter(Integration.id == account.integration_id).first()
    )
    if not integration:
        raise HTTPException(status_code=400, detail="Account integration not found")
    if integration.sub_type != "bunq":
        raise HTTPException(
            status_code=400, detail="Account is not connected to a bunq integration"
        )
    return account, BunqClient(api_key=integration.secret_key, account_key=integration.name)


def _fmt_bunq_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


@router.post("/schedule", response_model=SchedulePaymentResponse)
def create_schedule_payment(payload: SchedulePaymentRequest, db: Session = Depends(get_db)):
    """Create a recurring scheduled payment. Auto-executes per schedule, no in-app approval."""
    logger.info(
        f"POST /payments/schedule: account_id={payload.account_id}, amount={payload.amount} {payload.currency}, "
        f"start={payload.time_start.isoformat()}, end={payload.time_end.isoformat() if payload.time_end else None}, "
        f"every {payload.recurrence_size} {payload.recurrence_unit}"
    )

    now_utc = datetime.now(timezone.utc)
    start_aware = (
        payload.time_start
        if payload.time_start.tzinfo
        else payload.time_start.replace(tzinfo=timezone.utc)
    )
    if start_aware <= now_utc:
        raise HTTPException(
            status_code=400,
            detail="time_start must be in the future (UTC).",
        )

    account, bunq_client = _get_account_and_client(db, payload.account_id)

    iban = payload.counterparty_iban.replace(" ", "").upper()
    amount_str = f"{payload.amount:.2f}"

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(
                bunq_client.create_schedule_payment,
                monetary_account_id=account.monetary_account_id,
                amount_value=amount_str,
                currency=payload.currency,
                counterparty_iban=iban,
                counterparty_name=payload.counterparty_name,
                description=payload.description or "",
                time_start=_fmt_bunq_dt(payload.time_start),
                recurrence_unit=payload.recurrence_unit,
                recurrence_size=payload.recurrence_size,
                time_end=_fmt_bunq_dt(payload.time_end) if payload.time_end else None,
            )
            schedule_payment_id = future.result(timeout=45)
    except concurrent.futures.TimeoutError:
        logger.error("Bunq schedule payment call timed out after 45s")
        raise HTTPException(
            status_code=504, detail="Bunq schedule payment timed out after 45s"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create schedule payment: {e}")
        logger.error(traceback.format_exc())
        _raise_bunq_http_error(e, "schedule payment")
    logger.info(f"POST /payments/schedule done: id={schedule_payment_id}")

    return SchedulePaymentResponse(
        schedule_payment_id=schedule_payment_id,
        account_id=account.id,
        monetary_account_id=account.monetary_account_id,
        amount=amount_str,
        currency=payload.currency,
        counterparty_iban=iban,
        counterparty_name=payload.counterparty_name,
        description=payload.description or "",
        time_start=payload.time_start.isoformat(),
        time_end=payload.time_end.isoformat() if payload.time_end else None,
        recurrence_unit=payload.recurrence_unit,
        recurrence_size=payload.recurrence_size,
    )


@router.get("/schedule")
def list_schedule_payments(account_id: int, db: Session = Depends(get_db)):
    """List existing scheduled payments for an account."""
    account, bunq_client = _get_account_and_client(db, account_id)
    try:
        items = bunq_client.list_schedule_payments(account.monetary_account_id)
    except Exception as e:
        logger.error(f"Failed to list schedule payments: {e}")
        raise HTTPException(status_code=502, detail=f"Bunq list failed: {e}")

    out = []
    for sp in items:
        payment = sp.get("payment") or {}
        schedule = sp.get("schedule") or {}
        amount = payment.get("amount") or {}
        counterparty = payment.get("counterparty_alias") or {}
        # raw bunq JSON returns the LabelMonetaryAccount directly; the SDK
        # to_json shape nested it under label_monetary_account
        cp_label = counterparty.get("label_monetary_account") or counterparty
        out.append({
            "id": sp.get("id"),
            "status": sp.get("status"),
            "amount": amount.get("value"),
            "currency": amount.get("currency"),
            "description": payment.get("description"),
            "counterparty_name": cp_label.get("display_name") or cp_label.get("label_user", {}).get("display_name"),
            "counterparty_iban": cp_label.get("iban"),
            "time_start": schedule.get("time_start"),
            "time_end": schedule.get("time_end"),
            "recurrence_unit": schedule.get("recurrence_unit"),
            "recurrence_size": schedule.get("recurrence_size"),
        })
    return out


@router.delete("/schedule/{schedule_payment_id}")
def delete_schedule_payment(
    schedule_payment_id: int, account_id: int, db: Session = Depends(get_db)
):
    """Cancel a scheduled payment."""
    account, bunq_client = _get_account_and_client(db, account_id)
    try:
        bunq_client.delete_schedule_payment(
            account.monetary_account_id, schedule_payment_id
        )
    except Exception as e:
        logger.error(f"Failed to delete schedule payment {schedule_payment_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Bunq delete failed: {e}")
    return {"deleted": True, "schedule_payment_id": schedule_payment_id}
