"""Rule engine for automatic transaction categorization."""

import json
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from ..logger import logger
from ..models import CategoryRule, Transaction, RuleConditions, RuleCondition


def get_transaction_field_value(transaction: Transaction, field: str) -> str | Decimal | None:
    """Get the value of a transaction field for rule evaluation."""
    if field == "description":
        return transaction.description
    elif field == "counterparty_name":
        return transaction.counterparty_name
    elif field == "counterparty_iban":
        return transaction.counterparty_iban
    elif field == "account_name":
        return transaction.account.name if transaction.account else None
    elif field == "amount":
        return transaction.amount
    elif field == "direction":
        # Determine direction based on amount
        if transaction.amount is None:
            return None
        return "in" if transaction.amount > 0 else "out"
    elif field == "type":
        return transaction.type
    elif field == "sub_type":
        return transaction.sub_type
    else:
        return None


def evaluate_condition(transaction: Transaction, condition: RuleCondition) -> bool:
    """Evaluate a single condition against a transaction."""
    field_value = get_transaction_field_value(transaction, condition.field)
    
    # Handle null values
    if field_value is None:
        return False
    
    operator = condition.operator
    value = condition.value
    
    # String operations
    if operator == "contains":
        return str(value).lower() in str(field_value).lower()
    elif operator == "not_contains":
        return str(value).lower() not in str(field_value).lower()
    elif operator == "equals":
        if condition.field == "amount":
            try:
                return Decimal(str(field_value)) == Decimal(str(value))
            except (ValueError, TypeError):
                return False
        return str(field_value).lower() == str(value).lower()
    elif operator == "starts_with":
        return str(field_value).lower().startswith(str(value).lower())
    elif operator == "ends_with":
        return str(field_value).lower().endswith(str(value).lower())
    
    # Numeric operations (for amount field)
    elif operator == "greater_than":
        try:
            return Decimal(str(field_value)) > Decimal(str(value))
        except (ValueError, TypeError):
            return False
    elif operator == "less_than":
        try:
            return Decimal(str(field_value)) < Decimal(str(value))
        except (ValueError, TypeError):
            return False
    elif operator == "between":
        try:
            if not isinstance(value, list) or len(value) != 2:
                return False
            amount = Decimal(str(field_value))
            min_val = Decimal(str(value[0]))
            max_val = Decimal(str(value[1]))
            return min_val <= amount <= max_val
        except (ValueError, TypeError):
            return False
    
    return False


def evaluate_rule(transaction: Transaction, rule: CategoryRule) -> bool:
    """Check if a transaction matches all conditions of a rule."""
    try:
        # Parse conditions JSON
        conditions_data = json.loads(rule.conditions)
        conditions = RuleConditions(**conditions_data)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Invalid rule conditions for rule {rule.id}: {e}")
        return False
    
    if not conditions.rules:
        return False
    
    # Evaluate all conditions
    results = [evaluate_condition(transaction, cond) for cond in conditions.rules]
    
    # Apply match logic (all = AND, any = OR)
    if conditions.match == "all":
        return all(results)
    else:  # "any"
        return any(results)


def apply_rules_to_transaction(transaction: Transaction, rules: list[CategoryRule]) -> int | None:
    """
    Apply rules to a single transaction and return the matching category_id.
    
    Rules are evaluated in order (sorted by priority).
    Returns the category_id of the first matching rule, or None if no match.
    """
    # Sort rules by priority (lower = higher priority), id as a stable tie-break
    sorted_rules = sorted(rules, key=lambda r: (r.priority, r.id))
    
    for rule in sorted_rules:
        if not rule.is_active:
            continue
        if evaluate_rule(transaction, rule):
            logger.debug(f"Transaction {transaction.id} matched rule '{rule.name}' -> category {rule.category_id}")
            return rule.category_id
    
    return None


def apply_rules_to_uncategorized(db: Session, force: bool = False) -> dict:
    """
    Apply all active rules to uncategorized transactions.
    
    When force is True, all transactions are re-evaluated and a matching rule
    overwrites the existing category (including manually set ones).
    
    Returns a dict with stats: {categorized: int, total_uncategorized: int}
    """
    # Get all active rules
    rules = db.query(CategoryRule).filter(CategoryRule.is_active == True).all()
    
    if not rules:
        return {"categorized": 0, "total_uncategorized": 0, "message": "No active rules"}
    
    # Get the transactions to evaluate
    query = db.query(Transaction).options(joinedload(Transaction.account))
    if not force:
        query = query.filter(Transaction.category_id.is_(None))
    candidates = query.all()
    total_candidates = len(candidates)
    
    if total_candidates == 0:
        return {"categorized": 0, "total_uncategorized": 0, "message": "No transactions to categorize"}
    
    categorized_count = 0
    
    for transaction in candidates:
        category_id = apply_rules_to_transaction(transaction, rules)
        if category_id is not None and category_id != transaction.category_id:
            transaction.category_id = category_id
            categorized_count += 1
    
    if categorized_count > 0:
        db.commit()
        logger.info(f"Auto-categorized {categorized_count} of {total_candidates} transactions (force={force})")
    
    verb = "Re-categorized" if force else "Categorized"
    return {
        "categorized": categorized_count,
        "total_uncategorized": total_candidates,
        "message": f"{verb} {categorized_count} of {total_candidates} transactions",
    }


def apply_rules_to_transactions(db: Session, transactions: list[Transaction]) -> int:
    """
    Apply rules to a list of specific transactions (e.g., newly synced ones).
    Only applies to transactions without a category.
    
    Returns the number of transactions categorized.
    """
    # Get all active rules
    rules = db.query(CategoryRule).filter(CategoryRule.is_active == True).all()
    
    if not rules:
        return 0
    
    categorized_count = 0
    
    for transaction in transactions:
        # Skip if already categorized
        if transaction.category_id is not None:
            continue
        
        category_id = apply_rules_to_transaction(transaction, rules)
        if category_id is not None:
            transaction.category_id = category_id
            categorized_count += 1
    
    if categorized_count > 0:
        db.commit()
        logger.info(f"Auto-categorized {categorized_count} newly synced transactions")
    
    return categorized_count
