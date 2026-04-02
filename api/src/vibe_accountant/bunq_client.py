"""Bunq API client wrapper."""

import json
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from bunq import ApiEnvironmentType, Pagination
from bunq.sdk.context.api_context import ApiContext
from bunq.sdk.context.bunq_context import BunqContext
from bunq.sdk.model.generated.endpoint import (
    MonetaryAccountBankApiObject,
    PaymentApiObject,
    UserApiObject,
)
from fastapi import HTTPException

from .logger import logger
from .models import BunqTransaction


class BunqClient:
    """Client for interacting with the Bunq API."""

    def __init__(
        self,
        api_key: str | None = None,
        account_key: str = "default",
        device_description: str = "Vibe Accountant",
        environment: str = "PRODUCTION",
        parent_dir: str | None = None,
    ):
        """Initialize the Bunq client.

        Args:
            api_key: The Bunq API key. If None, will be read from environment.
            account_key: Key to identify this account, used for context file naming.
            device_description: Description of the device using the API.
            environment: 'PRODUCTION' or 'SANDBOX'.
            parent_dir: Directory for bunq config files.
        """
        if api_key is None:
            api_key = os.environ.get("BUNQ_API_KEY")
            if api_key is None:
                raise ValueError(
                    "No Bunq API key provided. Either pass api_key parameter "
                    "or set BUNQ_API_KEY environment variable."
                )

        self.api_key = api_key
        self.account_key = account_key
        self.device_description = device_description

        # Convert environment string to enum
        if environment == "SANDBOX":
            self.environment = ApiEnvironmentType.SANDBOX
        else:
            self.environment = ApiEnvironmentType.PRODUCTION

        # Set up the path for bunq configuration directory
        if parent_dir is None:
            parent_dir = os.environ.get("BUNQ_CONF_DIR")
            if parent_dir is None:
                raise ValueError(
                    "No bunq config directory provided. Either pass parent_dir parameter "
                    "or set BUNQ_CONF_DIR environment variable."
                )

        Path(parent_dir).mkdir(parents=True, exist_ok=True)
        self.context_file = f"{parent_dir}/{account_key}.conf"
        self.initialize_context()

    def get_current_user(self):
        """Get the current user from the Bunq API."""
        return UserApiObject.get().value

    def initialize_context(self):
        """Initialize the Bunq API context."""
        try:
            os.makedirs(os.path.dirname(self.context_file), exist_ok=True)

            if os.path.exists(self.context_file):
                logger.info(f"Restoring existing API context from {self.context_file}")
                api_context = ApiContext.restore(self.context_file)
            else:
                logger.info(f"Creating new API context for account_key: {self.account_key}")
                api_context = ApiContext.create(
                    self.environment, self.api_key, self.device_description
                )
                api_context.save(self.context_file)
                logger.info(f"API context saved to {self.context_file}")

            BunqContext.load_api_context(api_context)
            logger.info("API context loaded successfully")
        except Exception as e:
            stack_trace = traceback.format_exc()
            logger.error(f"Error initializing bunq context: {e}")
            logger.error(f"Stack trace: {stack_trace}")
            raise

    def _get_payments(
        self, count: int = 200, older_id: int | None = None, monetary_account_id: int | None = None
    ):
        """Get a list of payments."""
        pagination = Pagination()
        pagination.count = count

        params = pagination.url_params_count_only
        params["monetary_account_id"] = monetary_account_id
        if older_id:
            params["older_id"] = older_id

        return PaymentApiObject.list(monetary_account_id=monetary_account_id, params=params).value

    def get_payments(
        self,
        start_time: datetime | None = None,
        batch_size: int = 50,
        monetary_account_id: int | None = None,
    ):
        """Get payments with automatic pagination and time filtering."""
        logger.info(f"get_payments called: start_time={start_time}, batch_size={batch_size}, monetary_account_id={monetary_account_id}")

        all_payments = []
        older_id = None
        more_payments = True
        batch_num = 0

        while more_payments:
            batch_num += 1
            logger.info(f"  Fetching batch {batch_num} (older_id={older_id})...")

            batch = self._get_payments(
                count=batch_size,
                older_id=older_id,
                monetary_account_id=monetary_account_id,
            )

            logger.info(f"  Batch {batch_num} returned {len(batch) if batch else 0} payments")

            if not batch or len(batch) < batch_size:
                more_payments = False
            else:
                older_id = batch[-1].id_

            if start_time is not None:
                filtered_batch = [
                    payment
                    for payment in batch
                    if datetime.strptime(payment.created, "%Y-%m-%d %H:%M:%S.%f") >= start_time
                ]
                logger.info(f"  After time filtering: {len(filtered_batch)} payments (start_time={start_time})")
                all_payments.extend(filtered_batch)

                if (
                    batch
                    and datetime.strptime(batch[-1].created, "%Y-%m-%d %H:%M:%S.%f") < start_time
                ):
                    logger.info(f"  Reached payments older than start_time, stopping")
                    more_payments = False
            else:
                all_payments.extend(batch)

        logger.info(f"get_payments returning {len(all_payments)} total payments")
        return all_payments

    def get_transactions(
        self,
        start_time: datetime | None = None,
        batch_size: int = 200,
        max_results: int | None = None,
        monetary_account_id: int | None = None,
    ) -> list[BunqTransaction]:
        """Get transactions and convert to BunqTransaction objects."""
        logger.info(f"get_transactions called: start_time={start_time}, monetary_account_id={monetary_account_id}")

        if batch_size > 200:
            batch_size = 200

        raw_payments = self.get_payments(start_time, batch_size, monetary_account_id)
        logger.info(f"Got {len(raw_payments)} raw payments from API")

        transactions = []
        for i, payment in enumerate(raw_payments):
            payment_data = json.loads(payment.to_json())

            # Log first payment to see all available fields
            if i == 0:
                logger.info(f"=== BUNQ PAYMENT STRUCTURE ===")
                logger.info(f"All keys: {list(payment_data.keys())}")
                for key, value in payment_data.items():
                    if isinstance(value, dict):
                        logger.info(f"  {key}: {list(value.keys()) if value else 'empty dict'}")
                    elif isinstance(value, list) and value:
                        logger.info(f"  {key}: list with {len(value)} items, first: {type(value[0])}")
                    else:
                        logger.info(f"  {key}: {value}")
                logger.info(f"=== END STRUCTURE ===")

            transaction = BunqTransaction.from_api_response(payment_data)
            # Don't filter by monetary_account_id - the API already filters by account
            transactions.append(transaction)

            if max_results is not None and len(transactions) >= max_results:
                break

        logger.info(f"Converted to {len(transactions)} BunqTransaction objects")
        return transactions[:max_results] if max_results is not None else transactions

    def list_monetary_accounts(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        """Get list of monetary accounts from bunq API."""
        try:
            logger.info("Attempting to list monetary accounts...")

            try:
                if include_inactive:
                    raw_accounts_active = MonetaryAccountBankApiObject.list(
                        params={"status": "ACTIVE"}
                    ).value
                    raw_accounts_blocked = MonetaryAccountBankApiObject.list(
                        params={"status": "BLOCKED"}
                    ).value
                    raw_accounts_cancelled = MonetaryAccountBankApiObject.list(
                        params={"status": "CANCELLED"}
                    ).value
                    raw_accounts = raw_accounts_active + raw_accounts_blocked + raw_accounts_cancelled
                else:
                    raw_accounts = MonetaryAccountBankApiObject.list(
                        params={"status": "ACTIVE"}
                    ).value

                logger.info(f"Successfully retrieved {len(raw_accounts)} raw accounts")
            except TypeError as te:
                if "float() argument must be a string or a real number, not 'NoneType'" in str(te):
                    logger.error("Bunq API returned invalid data format")
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid bunq API key or data format issue.",
                    )
                raise te

            accounts = []
            for account_item in raw_accounts:
                account_item_json = account_item.to_json()
                try:
                    account_data = json.loads(account_item_json)

                    iban = None
                    if account_data.get("alias"):
                        for alias in account_data["alias"]:
                            if alias.get("type") == "IBAN":
                                iban = alias.get("value")
                                break

                    balance_info = account_data.get("balance", {})
                    balance_value = balance_info.get("value")
                    balance_currency = balance_info.get("currency")

                    account = {
                        "id": account_data.get("id"),
                        "description": account_data.get("description"),
                        "display_name": account_data.get("display_name"),
                        "balance": float(balance_value) if balance_value else 0.0,
                        "currency": balance_currency,
                        "type": account_item.__class__.__name__,
                        "status": account_data.get("status"),
                        "iban": iban,
                        "public_uuid": account_data.get("public_uuid"),
                        "created": account_data.get("created"),
                        "updated": account_data.get("updated"),
                    }
                    if not include_inactive and account.get("status") == "CANCELLED":
                        continue
                    accounts.append(account)
                    logger.info(
                        f"Successfully processed account: {account['display_name']} (ID: {account['id']})"
                    )

                except Exception as e:
                    logger.error(f"Error processing individual account: {e}")
                    continue

            return accounts
        except Exception as e:
            stack_trace = traceback.format_exc()
            logger.error(f"Error in list_monetary_accounts: {e}")
            logger.error(f"Stack trace: {stack_trace}")
            raise

    def get_monetary_account_by_id(self, account_id: int) -> dict[str, Any]:
        """Get a monetary account by its ID."""
        return MonetaryAccountBankApiObject.get(account_id).value
