"""Transaction management endpoints."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..logger import logger
from ..models import Document, Transaction, TransactionResponse

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _to_response(txn: Transaction) -> TransactionResponse:
    """Convert Transaction ORM object to response, including document_filename."""
    resp = TransactionResponse.model_validate(txn)
    if txn.document:
        resp.document_filename = txn.document.filename
    return resp


@router.get("/debug/db-status")
async def debug_db_status(db: Session = Depends(get_db)):
    """Debug endpoint to check database state."""
    from ..models import Account, Integration

    integrations = db.query(Integration).count()
    accounts = db.query(Account).all()
    transactions = db.query(Transaction).count()

    account_details = []
    for acc in accounts:
        txn_count = db.query(Transaction).filter(Transaction.account_id == acc.id).count()
        account_details.append({
            "id": acc.id,
            "name": acc.name,
            "monetary_account_id": acc.monetary_account_id,
            "last_synced_at": str(acc.last_synced_at) if acc.last_synced_at else None,
            "transaction_count": txn_count,
        })

    return {
        "integrations": integrations,
        "accounts": len(accounts),
        "account_details": account_details,
        "total_transactions": transactions,
    }


class TransactionSearchParams(BaseModel):
    """Search parameters for transactions."""

    query: str | None = None
    account_id: int | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    start_date: date | None = None
    end_date: date | None = None
    limit: int = 100
    offset: int = 0


class TransactionUpdate(BaseModel):
    """Schema for updating a transaction's category and tag."""

    category_id: int | None = None
    tag: str | None = None


@router.get("/filters")
async def get_filter_options(db: Session = Depends(get_db)):
    """Get available filter options for transactions."""
    from sqlalchemy import func, distinct
    from ..models import Account, Category

    # Get unique types
    types = [
        row[0] for row in
        db.query(distinct(Transaction.type))
        .filter(Transaction.type.isnot(None))
        .all()
    ]

    # Get unique sub_types
    sub_types = [
        row[0] for row in
        db.query(distinct(Transaction.sub_type))
        .filter(Transaction.sub_type.isnot(None))
        .all()
    ]

    # Get accounts with transaction counts and balance
    accounts = []
    for acc in db.query(Account).all():
        txn_count = db.query(Transaction).filter(Transaction.account_id == acc.id).count()
        # Get balance from the most recent transaction's balance_after
        latest_txn = (
            db.query(Transaction.balance_after)
            .filter(Transaction.account_id == acc.id, Transaction.balance_after.isnot(None))
            .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
            .first()
        )
        accounts.append({
            "id": acc.id,
            "name": acc.name,
            "iban": acc.iban,
            "transaction_count": txn_count,
            "balance": str(latest_txn[0]) if latest_txn else None,
        })

    # Get categories
    categories = []
    for cat in db.query(Category).all():
        categories.append({
            "id": cat.id,
            "name": cat.name,
            "color": cat.color,
        })

    return {
        "types": sorted(types),
        "sub_types": sorted(sub_types),
        "accounts": accounts,
        "categories": categories,
    }


class TransactionListResponse(BaseModel):
    """Response schema for paginated transaction list."""

    items: list[TransactionResponse]
    total: int


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    account_id: int | None = Query(None),
    category_id: str | None = Query(None, description="Filter by category ID, or 'none' for uncategorized"),
    query: str | None = Query(None, description="Search in description or counterparty"),
    min_amount: Decimal | None = Query(None),
    max_amount: Decimal | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    type: str | None = Query(None, description="Filter by payment type (e.g., IDEAL, BUNQ)"),
    sub_type: str | None = Query(None, description="Filter by sub type (e.g., REQUEST, PAYMENT)"),
    direction: str | None = Query(None, description="Filter by direction: 'in' or 'out'"),
    has_document: str | None = Query(None, description="Filter by document match: 'yes' or 'no'"),
    sort_by: str | None = Query(None, description="Sort by field: 'amount', 'date'"),
    sort_order: str | None = Query(None, description="Sort order: 'asc' or 'desc'"),
    limit: int = Query(50, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List transactions with optional filtering and search."""
    q = db.query(Transaction).options(joinedload(Transaction.document))

    # Apply filters
    if account_id:
        q = q.filter(Transaction.account_id == account_id)

    if category_id:
        if category_id == "none":
            q = q.filter(Transaction.category_id.is_(None))
        else:
            try:
                q = q.filter(Transaction.category_id == int(category_id))
            except ValueError:
                pass  # Invalid category_id, ignore

    if query:
        search_term = f"%{query}%"
        text_filters = [
            Transaction.description.ilike(search_term),
            Transaction.counterparty_name.ilike(search_term),
            Transaction.counterparty_iban.ilike(search_term),
        ]
        # Also match on amount (support both . and , as decimal separator)
        try:
            amount_value = Decimal(query.replace(",", "."))
            text_filters.append(Transaction.amount == amount_value)
            text_filters.append(Transaction.amount == -amount_value)
        except Exception:
            pass
        q = q.filter(or_(*text_filters))

    if min_amount is not None:
        q = q.filter(Transaction.amount >= min_amount)

    if max_amount is not None:
        q = q.filter(Transaction.amount <= max_amount)

    if start_date:
        q = q.filter(Transaction.transaction_date >= start_date)

    if end_date:
        q = q.filter(Transaction.transaction_date <= end_date)

    if type:
        q = q.filter(Transaction.type == type)

    if sub_type:
        q = q.filter(Transaction.sub_type == sub_type)

    if direction:
        if direction == 'in':
            q = q.filter(Transaction.amount > 0)
        elif direction == 'out':
            q = q.filter(Transaction.amount < 0)

    if has_document:
        if has_document == 'yes':
            q = q.filter(Transaction.document_id.isnot(None))
        elif has_document == 'no':
            q = q.filter(Transaction.document_id.is_(None))

    # Get total count before pagination
    total_count = q.count()

    # Apply sorting
    sort_column = Transaction.transaction_date
    if sort_by == "amount":
        sort_column = Transaction.amount

    if sort_order == "asc":
        q = q.order_by(sort_column.asc())
    else:
        q = q.order_by(sort_column.desc())

    # Apply pagination
    transactions = q.offset(offset).limit(limit).all()

    logger.info(f"GET /transactions: total={total_count}, returning {len(transactions)} (limit={limit}, offset={offset})")

    return TransactionListResponse(items=[_to_response(t) for t in transactions], total=total_count)


@router.get("/stats")
async def get_transaction_stats(
    account_id: int | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: Session = Depends(get_db),
):
    """Get transaction statistics including category breakdown."""
    from sqlalchemy import func, case

    from ..models import Category

    q = db.query(Transaction)

    if account_id:
        q = q.filter(Transaction.account_id == account_id)

    if start_date:
        q = q.filter(Transaction.transaction_date >= start_date)

    if end_date:
        q = q.filter(Transaction.transaction_date <= end_date)

    # Calculate stats
    total_count = q.count()

    income = (
        q.filter(Transaction.amount > 0).with_entities(func.sum(Transaction.amount)).scalar()
        or Decimal("0")
    )

    expenses = (
        q.filter(Transaction.amount < 0).with_entities(func.sum(Transaction.amount)).scalar()
        or Decimal("0")
    )

    # Category breakdown - join with categories to get name and color
    category_stats = (
        q.outerjoin(Category, Transaction.category_id == Category.id)
        .with_entities(
            Transaction.category_id,
            Category.name,
            Category.color,
            func.sum(Transaction.amount).label("total"),
            func.sum(case((Transaction.amount > 0, Transaction.amount), else_=0)).label("income"),
            func.sum(case((Transaction.amount < 0, Transaction.amount), else_=0)).label("expenses"),
            func.count(Transaction.id).label("count"),
        )
        .group_by(Transaction.category_id, Category.name, Category.color)
        .all()
    )

    by_category = [
        {
            "category_id": row.category_id,
            "category_name": row.name or "Uncategorized",
            "category_color": row.color,
            "total": str(row.total or 0),
            "income": str(row.income or 0),
            "expenses": str(abs(row.expenses or 0)),
            "count": row.count,
        }
        for row in category_stats
    ]

    return {
        "total_count": total_count,
        "total_income": str(income),
        "total_expenses": str(abs(expenses)),
        "net_balance": str(income + expenses),
        "by_category": by_category,
    }


@router.post("/apply-rules")
async def apply_categorization_rules(db: Session = Depends(get_db)):
    """Apply all active categorization rules to uncategorized transactions."""
    from ..services import apply_rules_to_uncategorized

    result = apply_rules_to_uncategorized(db)
    return result


@router.post("/match-documents")
async def match_documents(db: Session = Depends(get_db)):
    """Match documents to transactions by reference or amount+name."""
    from ..services import match_documents_to_transactions

    matched = match_documents_to_transactions(db)
    return {
        "matched": matched,
        "message": f"Matched {matched} document(s) to transactions" if matched else "No new matches found",
    }


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(transaction_id: int, db: Session = Depends(get_db)):
    """Get a specific transaction by ID."""
    transaction = (
        db.query(Transaction)
        .options(joinedload(Transaction.document))
        .filter(Transaction.id == transaction_id)
        .first()
    )
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _to_response(transaction)


@router.patch("/{transaction_id}", response_model=TransactionResponse)
async def update_transaction(
    transaction_id: int, data: TransactionUpdate, db: Session = Depends(get_db)
):
    """Update a transaction's category_id and/or tag."""
    transaction = (
        db.query(Transaction)
        .options(joinedload(Transaction.document))
        .filter(Transaction.id == transaction_id)
        .first()
    )
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Update category_id if provided (can be set to null)
    if "category_id" in data.model_dump(exclude_unset=True):
        # Validate category exists if not null
        if data.category_id is not None:
            from ..models import Category
            category = db.query(Category).filter(Category.id == data.category_id).first()
            if not category:
                raise HTTPException(status_code=400, detail="Category not found")
        transaction.category_id = data.category_id

    # Update tag if provided (can be set to null/empty)
    if "tag" in data.model_dump(exclude_unset=True):
        transaction.tag = data.tag if data.tag else None

    db.commit()
    db.refresh(transaction)
    return _to_response(transaction)


@router.get("/{transaction_id}/raw")
async def get_transaction_raw_json(transaction_id: int, db: Session = Depends(get_db)):
    """Get the raw JSON from bunq API for a transaction."""
    from fastapi import HTTPException
    from fastapi.responses import JSONResponse
    import json

    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if not transaction.raw_json:
        raise HTTPException(status_code=404, detail="Raw JSON not available for this transaction")

    try:
        raw_data = json.loads(transaction.raw_json)
        return JSONResponse(content=raw_data)
    except json.JSONDecodeError:
        return JSONResponse(content={"raw": transaction.raw_json})
