"""Payment endpoints (draft payments via bunq SDK)."""

import traceback
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..bunq_client import BunqClient
from ..database import get_db
from ..logger import logger
from ..models import Account, Integration, Transaction

router = APIRouter(prefix="/payments", tags=["payments"])


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
    message: str = "Draft payment created. Approve in the bunq app to execute."


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
    """Create a bunq draft payment from a local account. Confirmation happens out-of-band in the bunq app."""
    account = db.query(Account).filter(Account.id == payload.account_id).first()
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

    iban = payload.counterparty_iban.replace(" ", "").upper()
    amount_str = f"{payload.amount:.2f}"

    try:
        bunq_client = BunqClient(
            api_key=integration.secret_key,
            account_key=integration.name,
        )
        draft_id = bunq_client.create_draft_payment(
            monetary_account_id=account.monetary_account_id,
            amount_value=amount_str,
            currency=payload.currency,
            counterparty_iban=iban,
            counterparty_name=payload.counterparty_name,
            description=payload.description or "",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create draft payment: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=502, detail=f"Bunq draft payment failed: {e}"
        )

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
