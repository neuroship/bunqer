"""Category management endpoints."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Category,
    CategoryCreate,
    CategoryUpdate,
    CategoryResponse,
    CategoryRule,
    CategoryRuleCreate,
    CategoryRuleUpdate,
    CategoryRuleResponse,
    Transaction,
    CategoriesExport,
    CategoriesImport,
)

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryResponse])
async def list_categories(db: Session = Depends(get_db)):
    """List all categories."""
    categories = db.query(Category).order_by(Category.name).all()
    return categories


@router.post("", response_model=CategoryResponse, status_code=201)
async def create_category(data: CategoryCreate, db: Session = Depends(get_db)):
    """Create a new category."""
    # Check for duplicate name
    existing = db.query(Category).filter(Category.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category with this name already exists")

    category = Category(
        name=data.name,
        description=data.description,
        color=data.color,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


# ==================== Export/Import Endpoints ====================
# These must be defined before /{category_id} to avoid path conflicts


@router.get("/export", response_model=CategoriesExport)
async def export_categories(db: Session = Depends(get_db)):
    """Export all categories and their rules to JSON."""
    categories = db.query(Category).order_by(Category.name).all()

    export_data = {
        "version": "1.0",
        "exported_at": datetime.now(timezone.utc),
        "categories": [],
    }

    for category in categories:
        rules = (
            db.query(CategoryRule)
            .filter(CategoryRule.category_id == category.id)
            .order_by(CategoryRule.priority, CategoryRule.name)
            .all()
        )

        category_export = {
            "name": category.name,
            "description": category.description,
            "color": category.color,
            "rules": [
                {
                    "name": rule.name,
                    "conditions": json.loads(rule.conditions),
                    "is_active": rule.is_active,
                    "priority": rule.priority,
                }
                for rule in rules
            ],
        }
        export_data["categories"].append(category_export)

    return export_data


@router.post("/import")
async def import_categories(data: CategoriesImport, db: Session = Depends(get_db)):
    """Import categories and rules from JSON. Replaces all existing categories and rules."""
    # Clear all transactions' category references first
    db.query(Transaction).filter(Transaction.category_id.isnot(None)).update(
        {"category_id": None}
    )

    # Delete all existing rules (cascade from categories won't work here since we delete manually)
    db.query(CategoryRule).delete()

    # Delete all existing categories
    db.query(Category).delete()

    # Import new categories and rules
    imported_categories = 0
    imported_rules = 0

    for cat_data in data.categories:
        category = Category(
            name=cat_data.name,
            description=cat_data.description,
            color=cat_data.color,
        )
        db.add(category)
        db.flush()  # Get the category ID

        for rule_data in cat_data.rules:
            rule = CategoryRule(
                category_id=category.id,
                name=rule_data.name,
                conditions=json.dumps(rule_data.conditions.model_dump()),
                is_active=rule_data.is_active,
                priority=rule_data.priority,
            )
            db.add(rule)
            imported_rules += 1

        imported_categories += 1

    db.commit()

    return {
        "success": True,
        "imported_categories": imported_categories,
        "imported_rules": imported_rules,
    }


@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(category_id: int, db: Session = Depends(get_db)):
    """Get a specific category by ID."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


@router.patch("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: int, data: CategoryUpdate, db: Session = Depends(get_db)
):
    """Update a category."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    # Check for duplicate name if name is being updated
    if data.name and data.name != category.name:
        existing = db.query(Category).filter(Category.name == data.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Category with this name already exists")

    # Update fields
    if data.name is not None:
        category.name = data.name
    if data.description is not None:
        category.description = data.description
    if data.color is not None:
        category.color = data.color

    db.commit()
    db.refresh(category)
    return category


@router.delete("/{category_id}")
async def delete_category(category_id: int, db: Session = Depends(get_db)):
    """Delete a category. Returns transaction count that was using this category."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    # Count transactions using this category
    transaction_count = (
        db.query(Transaction).filter(Transaction.category_id == category_id).count()
    )

    # Clear category_id from transactions
    db.query(Transaction).filter(Transaction.category_id == category_id).update(
        {"category_id": None}
    )

    # Delete category
    db.delete(category)
    db.commit()

    return {"deleted": True, "affected_transactions": transaction_count}


# ==================== Category Rules Endpoints ====================


@router.get("/{category_id}/rules", response_model=list[CategoryRuleResponse])
async def list_category_rules(category_id: int, db: Session = Depends(get_db)):
    """List all rules for a category."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    rules = (
        db.query(CategoryRule)
        .filter(CategoryRule.category_id == category_id)
        .order_by(CategoryRule.priority, CategoryRule.name)
        .all()
    )

    # Parse conditions JSON for response
    result = []
    for rule in rules:
        rule_dict = {
            "id": rule.id,
            "category_id": rule.category_id,
            "name": rule.name,
            "conditions": json.loads(rule.conditions),
            "is_active": rule.is_active,
            "priority": rule.priority,
            "created_at": rule.created_at,
        }
        result.append(rule_dict)

    return result


@router.post("/{category_id}/rules", response_model=CategoryRuleResponse, status_code=201)
async def create_category_rule(
    category_id: int, data: CategoryRuleCreate, db: Session = Depends(get_db)
):
    """Create a new rule for a category."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    # Validate that there's at least one condition
    if not data.conditions.rules:
        raise HTTPException(status_code=400, detail="At least one condition is required")

    rule = CategoryRule(
        category_id=category_id,
        name=data.name,
        conditions=json.dumps(data.conditions.model_dump()),
        is_active=data.is_active,
        priority=data.priority,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    return {
        "id": rule.id,
        "category_id": rule.category_id,
        "name": rule.name,
        "conditions": json.loads(rule.conditions),
        "is_active": rule.is_active,
        "priority": rule.priority,
        "created_at": rule.created_at,
    }


@router.get("/rules/{rule_id}", response_model=CategoryRuleResponse)
async def get_category_rule(rule_id: int, db: Session = Depends(get_db)):
    """Get a specific rule by ID."""
    rule = db.query(CategoryRule).filter(CategoryRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    return {
        "id": rule.id,
        "category_id": rule.category_id,
        "name": rule.name,
        "conditions": json.loads(rule.conditions),
        "is_active": rule.is_active,
        "priority": rule.priority,
        "created_at": rule.created_at,
    }


@router.patch("/rules/{rule_id}", response_model=CategoryRuleResponse)
async def update_category_rule(
    rule_id: int, data: CategoryRuleUpdate, db: Session = Depends(get_db)
):
    """Update a rule."""
    rule = db.query(CategoryRule).filter(CategoryRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    if data.name is not None:
        rule.name = data.name
    if data.conditions is not None:
        if not data.conditions.rules:
            raise HTTPException(status_code=400, detail="At least one condition is required")
        rule.conditions = json.dumps(data.conditions.model_dump())
    if data.is_active is not None:
        rule.is_active = data.is_active
    if data.priority is not None:
        rule.priority = data.priority

    db.commit()
    db.refresh(rule)

    return {
        "id": rule.id,
        "category_id": rule.category_id,
        "name": rule.name,
        "conditions": json.loads(rule.conditions),
        "is_active": rule.is_active,
        "priority": rule.priority,
        "created_at": rule.created_at,
    }


@router.delete("/rules/{rule_id}")
async def delete_category_rule(rule_id: int, db: Session = Depends(get_db)):
    """Delete a rule."""
    rule = db.query(CategoryRule).filter(CategoryRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    db.delete(rule)
    db.commit()

    return {"deleted": True}
