"""Setup and onboarding endpoints for bunq integration."""

from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..bunq_client import BunqClient
from ..database import get_db
from ..logger import logger
from ..models import Account, AccountCreate, Integration, Transaction
from .events import broadcast_event

router = APIRouter(prefix="/setup", tags=["setup"])


@router.post("/sync")
async def trigger_sync(background_tasks: BackgroundTasks):
    """Manually trigger sync for all accounts."""
    background_tasks.add_task(sync_all_accounts)
    return {"status": "started", "message": "Sync started for all accounts"}


@router.post("/resync")
def resync_all_transactions(db: Session = Depends(get_db)):
    """Clear all transactions and re-sync from scratch.

    This is useful when new fields are added to capture more data.
    """
    import traceback
    from .events import send_notification

    try:
        logger.info("=== RESYNC: Clearing all transactions ===")

        # Count existing transactions
        existing_count = db.query(Transaction).count()
        logger.info(f"Deleting {existing_count} existing transactions...")

        # Delete all transactions
        db.query(Transaction).delete()

        # Reset last_synced_at for all accounts so they sync from beginning
        accounts = db.query(Account).filter(Account.monetary_account_id.isnot(None)).all()
        for account in accounts:
            account.last_synced_at = None

        db.commit()
        logger.info("Transactions cleared, starting fresh sync...")

        # Now sync all accounts
        if not accounts:
            return {"status": "no_accounts", "message": "No accounts configured"}

        results = []
        for account in accounts:
            integration = db.query(Integration).filter(Integration.id == account.integration_id).first()
            if not integration:
                results.append({"account": account.name, "error": "Integration not found"})
                continue

            try:
                bunq_client = BunqClient(
                    api_key=integration.secret_key,
                    account_key=integration.name,
                )
                new_count = sync_account_transactions_sync(db, bunq_client, account.id)
                results.append({"account": account.name, "new_transactions": new_count})
            except Exception as e:
                logger.error(f"Error syncing {account.name}: {e}")
                results.append({"account": account.name, "error": str(e)})

        total_new = sum(r.get("new_transactions", 0) for r in results)
        logger.info(f"=== RESYNC complete: {total_new} transactions imported ===")
        send_notification(f"Re-sync complete: {total_new} transactions imported", "success")

        return {
            "status": "completed",
            "deleted": existing_count,
            "imported": total_new,
            "results": results
        }

    except Exception as e:
        logger.error(f"Error in resync: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Re-sync failed due to an internal error")


@router.post("/sync-now")
def trigger_sync_now(db: Session = Depends(get_db)):
    """Synchronously sync all accounts (for debugging)."""
    import traceback

    try:
        logger.info("=== Manual sync triggered ===")
        accounts = db.query(Account).filter(Account.monetary_account_id.isnot(None)).all()
        logger.info(f"Found {len(accounts)} accounts to sync")

        if not accounts:
            broadcast_event("auto_sync_completed", {
                "message": "No accounts configured",
                "total_new": 0,
                "results": []
            })
            return {"status": "no_accounts", "message": "No accounts configured"}

        broadcast_event("auto_sync_started", {
            "message": f"Syncing {len(accounts)} account(s)...",
            "account_count": len(accounts)
        })

        results = []
        total_new = 0
        for account in accounts:
            logger.info(f"Processing account: {account.name} (ID: {account.id})")
            integration = db.query(Integration).filter(Integration.id == account.integration_id).first()
            if not integration:
                logger.warning(f"Integration not found for account {account.name}")
                results.append({"account": account.name, "error": "Integration not found"})
                continue

            try:
                logger.info(f"Initializing BunqClient for {integration.name}...")
                bunq_client = BunqClient(
                    api_key=integration.secret_key,
                    account_key=integration.name,
                )
                logger.info(f"BunqClient initialized, starting sync...")

                new_count = sync_account_transactions_sync(db, bunq_client, account.id)
                logger.info(f"Sync complete for {account.name}: {new_count} new transactions")
                results.append({"account": account.name, "new_transactions": new_count})
                total_new += new_count
            except Exception as e:
                logger.error(f"Error syncing {account.name}: {e}")
                logger.error(traceback.format_exc())
                results.append({"account": account.name, "error": str(e)})

        logger.info(f"=== Manual sync completed ===")

        if total_new > 0:
            broadcast_event("auto_sync_completed", {
                "message": f"Synced {total_new} new transactions",
                "total_new": total_new,
                "results": results
            })
        else:
            broadcast_event("auto_sync_completed", {
                "message": "All transactions up to date",
                "total_new": 0,
                "results": results
            })

        return {"status": "completed", "results": results}

    except Exception as e:
        logger.error(f"Critical error in sync-now: {e}")
        logger.error(traceback.format_exc())
        broadcast_event("auto_sync_error", {
            "message": "Sync failed due to an internal error"
        })
        raise HTTPException(status_code=500, detail="Sync failed due to an internal error")


class BunqSetupStartRequest(BaseModel):
    """Request to start bunq setup."""

    integration_id: int
    include_inactive: bool = False


class BunqSetupStartResponse(BaseModel):
    """Response for bunq setup start."""

    status: str
    message: str
    accounts: list[dict] = []


class BunqAccountSetupRequest(BaseModel):
    """Request to setup selected bunq accounts."""

    integration_id: int
    monetary_accounts: list[int]


@router.post("/bunq/start", response_model=BunqSetupStartResponse)
async def start_bunq_setup(
    request: BunqSetupStartRequest,
    db: Session = Depends(get_db),
):
    """Verify bunq connection and fetch monetary accounts."""
    try:
        integration = db.query(Integration).filter(Integration.id == request.integration_id).first()
        if not integration:
            raise HTTPException(
                status_code=404,
                detail=f"Integration with id {request.integration_id} not found.",
            )

        if integration.type != "bank" or integration.sub_type != "bunq":
            raise HTTPException(
                status_code=400,
                detail="Integration is not a bunq bank integration",
            )

        # Initialize bunq client
        bunq_client = BunqClient(
            api_key=integration.secret_key,
            account_key=integration.name,
        )

        # Fetch monetary accounts
        monetary_accounts = bunq_client.list_monetary_accounts(
            include_inactive=request.include_inactive
        )

        logger.info(f"Successfully fetched {len(monetary_accounts)} monetary accounts")

        return BunqSetupStartResponse(
            status="success",
            message=f"Found {len(monetary_accounts)} monetary accounts",
            accounts=monetary_accounts,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting bunq setup: {e}")
        raise HTTPException(status_code=500, detail="Failed to connect to bunq")


@router.post("/bunq/accounts")
def setup_bunq_accounts(
    request: BunqAccountSetupRequest,
    db: Session = Depends(get_db),
):
    """Set up selected bunq accounts and fetch transactions synchronously."""
    from .events import send_notification

    try:
        integration = db.query(Integration).filter(Integration.id == request.integration_id).first()
        if not integration:
            raise HTTPException(
                status_code=404,
                detail=f"Integration with id {request.integration_id} not found.",
            )

        logger.info(f"=== Setting up bunq accounts for integration: {integration.name} ===")

        # Initialize bunq client
        bunq_client = BunqClient(
            api_key=integration.secret_key,
            account_key=integration.name,
        )

        # Fetch monetary accounts to get details
        monetary_accounts = bunq_client.list_monetary_accounts()
        monetary_accounts_dict = {acc["id"]: acc for acc in monetary_accounts}

        results = []
        for monetary_account_id in request.monetary_accounts:
            account_data = monetary_accounts_dict.get(monetary_account_id)
            if not account_data:
                logger.warning(f"Monetary account {monetary_account_id} not found in bunq")
                results.append({"monetary_account_id": monetary_account_id, "error": "Not found in bunq"})
                continue

            account_name = account_data.get("display_name") or account_data.get("description")
            logger.info(f"Processing account: {account_name} (monetary_id: {monetary_account_id})")

            # Check if account already exists
            existing = (
                db.query(Account)
                .filter(Account.monetary_account_id == monetary_account_id)
                .first()
            )

            if existing:
                logger.info(f"Account already exists in DB: {existing.name} (ID: {existing.id})")
                db_account = existing
            else:
                # Create account in database
                db_account = Account(
                    name=account_name,
                    iban=account_data.get("iban"),
                    tag=f"bunq-{integration.name}",
                    integration_id=integration.id,
                    monetary_account_id=monetary_account_id,
                )
                db.add(db_account)
                db.commit()
                db.refresh(db_account)
                logger.info(f"Created account: {db_account.name} (ID: {db_account.id})")

            # Sync transactions for this account
            try:
                new_count = sync_account_transactions_sync(db, bunq_client, db_account.id)
                results.append({
                    "account_id": db_account.id,
                    "account_name": db_account.name,
                    "new_transactions": new_count,
                    "status": "success"
                })
            except Exception as e:
                import traceback
                logger.error(f"Error syncing account {db_account.name}: {e}")
                logger.error(traceback.format_exc())
                results.append({
                    "account_id": db_account.id,
                    "account_name": db_account.name,
                    "error": str(e),
                    "status": "error"
                })

        # Calculate totals
        total_new = sum(r.get("new_transactions", 0) for r in results)
        success_count = sum(1 for r in results if r.get("status") == "success")

        logger.info(f"=== Import complete: {success_count} accounts, {total_new} new transactions ===")
        send_notification(f"Import complete: {total_new} new transactions", "success")

        return {
            "status": "completed",
            "message": f"Imported {total_new} transactions from {success_count} accounts",
            "total_new_transactions": total_new,
            "results": results,
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Error setting up bunq accounts: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to set up bunq accounts")


def sync_account_transactions_sync(db, bunq_client: BunqClient, account_id: int) -> int:
    """Sync transactions for a single account (synchronous version)."""
    import traceback
    import sys
    from .events import send_sync_started, send_sync_progress, send_sync_completed, send_sync_error
    from ..services import apply_rules_to_transactions

    account_name = f"Account {account_id}"  # Default name for error messages

    def log(msg):
        """Log to both logger and stderr for visibility."""
        logger.info(msg)
        print(f"[SYNC] {msg}", file=sys.stderr, flush=True)

    try:
        log(f"sync_account_transactions_sync called for account_id={account_id}")

        account = db.query(Account).filter(Account.id == account_id).first()
        if not account or not account.monetary_account_id:
            log(f"Account {account_id} not found or has no monetary_account_id")
            return 0

        account_name = account.name
        log(f"=== Starting sync for account: {account.name} (ID: {account.id}) ===")
        log(f"    Monetary account ID: {account.monetary_account_id}")
        log(f"    Last synced at: {account.last_synced_at}")

        send_sync_started(account.name, account.id)

        # Determine start time: last sync or 365 days ago for initial sync
        # Subtract 2 hours buffer to handle timezone differences between local time and bunq API (UTC)
        if account.last_synced_at:
            start_time = account.last_synced_at - timedelta(hours=2)
            log(f"    Incremental sync from: {start_time} (last_synced_at: {account.last_synced_at}, with 2h buffer)")
        else:
            start_time = datetime.now() - timedelta(days=365)
            log(f"    Initial sync, fetching from: {start_time}")

        log(f"    Calling bunq API to get transactions...")
        transactions = bunq_client.get_transactions(
            start_time=start_time,
            batch_size=200,
            max_results=None,
            monetary_account_id=account.monetary_account_id,
        )

        log(f"    Bunq API returned {len(transactions)} transactions")

        if len(transactions) == 0:
            log(f"    No transactions returned from bunq API")
            send_sync_progress(account.name, 0, 0)
            account.last_synced_at = datetime.now()
            db.commit()
            send_sync_completed(account.name, 0)
            return 0

        # Get all existing bunq_ids in one query (much faster than checking one by one)
        log(f"    Checking for existing transactions...")
        existing_bunq_ids = set(
            row[0] for row in db.query(Transaction.bunq_id)
            .filter(Transaction.account_id == account.id)
            .filter(Transaction.bunq_id.isnot(None))
            .all()
        )
        log(f"    Found {len(existing_bunq_ids)} existing transactions in DB")

        # Filter to only new transactions
        new_transactions = [txn for txn in transactions if txn.id not in existing_bunq_ids]
        skipped_count = len(transactions) - len(new_transactions)
        log(f"    {len(new_transactions)} new, {skipped_count} already exist")

        if len(new_transactions) == 0:
            log(f"    No new transactions to import")
            account.last_synced_at = datetime.now()
            db.commit()
            send_sync_completed(account.name, 0)
            return 0

        # Save transactions in batches
        new_count = 0
        batch_size = 100
        saved_transactions = []

        log(f"    Starting to save {len(new_transactions)} transactions...")

        for i, txn in enumerate(new_transactions):
            db_transaction = Transaction(
                bunq_id=txn.id,
                account_id=account.id,
                amount=txn.amount,
                currency=txn.currency,
                sender_name=txn.sender_name,
                sender_iban=txn.sender_iban,
                receiver_name=txn.receiver_name,
                receiver_iban=txn.receiver_iban,
                counterparty_name=txn.counterparty_name,
                counterparty_iban=txn.counterparty_iban,
                description=txn.description,
                type=txn.type,
                sub_type=txn.sub_type,
                balance_after=txn.balance_after,
                geo_latitude=txn.geo_latitude,
                geo_longitude=txn.geo_longitude,
                batch_id=txn.batch_id,
                scheduled_id=txn.scheduled_id,
                request_reference_split_the_bill=txn.request_reference_split_the_bill,
                transaction_date=txn.created,
                raw_json=txn.raw_json,
            )
            db.add(db_transaction)
            saved_transactions.append(db_transaction)
            new_count += 1

            # Commit in batches and send progress
            if new_count % batch_size == 0:
                log(f"    Committing batch... ({new_count}/{len(new_transactions)})")
                db.commit()
                send_sync_progress(account.name, new_count, len(new_transactions))

        # Final commit for remaining transactions
        log(f"    Final commit... ({new_count} total)")
        account.last_synced_at = datetime.now()
        db.commit()
        log(f"    Commit successful!")

        # Apply categorization rules to newly synced transactions
        try:
            categorized_count = apply_rules_to_transactions(db, saved_transactions)
            if categorized_count > 0:
                log(f"    Auto-categorized {categorized_count} transactions")
        except Exception as e:
            log(f"    Warning: Failed to apply categorization rules: {e}")

        # Verify transactions were saved
        saved_count = db.query(Transaction).filter(Transaction.account_id == account.id).count()
        log(f"    Verification: {saved_count} transactions in DB for this account")

        log(f"=== Sync completed for {account.name} ===")
        log(f"    Total from API: {len(transactions)}")
        log(f"    New transactions: {new_count}")
        log(f"    Skipped (duplicates): {skipped_count}")
        log(f"    Total in database: {saved_count}")

        send_sync_completed(account.name, new_count)
        return new_count

    except Exception as e:
        err_msg = f"Error syncing transactions for {account_name}: {e}"
        tb = traceback.format_exc()
        logger.error(err_msg)
        logger.error(f"Traceback: {tb}")
        print(f"[SYNC ERROR] {err_msg}", file=sys.stderr, flush=True)
        print(f"[SYNC TRACEBACK] {tb}", file=sys.stderr, flush=True)
        try:
            send_sync_error(account_name, str(e))
        except:
            pass
        return 0


def sync_all_accounts():
    """Sync transactions for all configured accounts."""
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        accounts = db.query(Account).filter(Account.monetary_account_id.isnot(None)).all()

        if not accounts:
            logger.info("No accounts configured, skipping sync")
            return 0

        logger.info(f"Starting sync for {len(accounts)} accounts...")

        total_new = 0
        integration_accounts: dict[int, list[Account]] = {}
        for account in accounts:
            if account.integration_id not in integration_accounts:
                integration_accounts[account.integration_id] = []
            integration_accounts[account.integration_id].append(account)

        for integration_id, accts in integration_accounts.items():
            integration = db.query(Integration).filter(Integration.id == integration_id).first()
            if not integration:
                continue

            try:
                bunq_client = BunqClient(
                    api_key=integration.secret_key,
                    account_key=integration.name,
                )

                for account in accts:
                    new_count = sync_account_transactions_sync(db, bunq_client, account.id)
                    total_new += new_count

            except Exception as e:
                logger.error(f"Error syncing integration {integration.name}: {e}")
                continue

        logger.info(f"Account sync completed: {total_new} new transactions")
        return total_new

    finally:
        db.close()


def auto_sync_all_accounts():
    """Auto-sync on startup: sync all accounts and notify user via events."""
    from .events import send_notification, broadcast_event
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        accounts = db.query(Account).filter(Account.monetary_account_id.isnot(None)).all()

        if not accounts:
            logger.info("No accounts configured, skipping auto-sync")
            return

        logger.info(f"=== Auto-sync starting for {len(accounts)} accounts ===")
        broadcast_event("auto_sync_started", {
            "message": f"Syncing {len(accounts)} account(s)...",
            "account_count": len(accounts)
        })

        total_new = 0
        results = []

        # Group by integration
        integration_accounts: dict[int, list[Account]] = {}
        for account in accounts:
            if account.integration_id not in integration_accounts:
                integration_accounts[account.integration_id] = []
            integration_accounts[account.integration_id].append(account)

        for integration_id, accts in integration_accounts.items():
            integration = db.query(Integration).filter(Integration.id == integration_id).first()
            if not integration:
                continue

            try:
                logger.info(f"Initializing bunq client for {integration.name}...")
                bunq_client = BunqClient(
                    api_key=integration.secret_key,
                    account_key=integration.name,
                )

                for account in accts:
                    new_count = sync_account_transactions_sync(db, bunq_client, account.id)
                    total_new += new_count
                    results.append({
                        "account": account.name,
                        "new_transactions": new_count
                    })

            except Exception as e:
                logger.error(f"Error syncing integration {integration.name}: {e}")
                results.append({
                    "account": integration.name,
                    "error": str(e)
                })
                continue

        # Send completion event
        logger.info(f"=== Auto-sync completed: {total_new} new transactions ===")

        if total_new > 0:
            broadcast_event("auto_sync_completed", {
                "message": f"Synced {total_new} new transactions",
                "total_new": total_new,
                "results": results
            })
            send_notification(f"Synced {total_new} new transactions", "success")
        else:
            broadcast_event("auto_sync_completed", {
                "message": "All transactions up to date",
                "total_new": 0,
                "results": results
            })
            send_notification("All transactions up to date", "info")

    except Exception as e:
        import traceback
        logger.error(f"Auto-sync failed: {e}")
        logger.error(traceback.format_exc())
        broadcast_event("auto_sync_error", {
            "message": f"Sync failed: {str(e)}",
            "error": str(e)
        })

    finally:
        db.close()
