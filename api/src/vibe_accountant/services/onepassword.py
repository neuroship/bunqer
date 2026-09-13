"""Resolve secrets from 1Password via a Service Account."""

from onepassword.client import Client

INTEGRATION_NAME = "Bunqer Invoice Fetcher"
INTEGRATION_VERSION = "v1.0.0"


async def resolve_login(token: str, item_ref: str) -> tuple[str, str]:
    """Resolve username and password for an item reference like op://Vault/Item."""
    ref = item_ref.strip().rstrip("/")
    if not ref.startswith("op://") or ref.count("/") < 3:
        raise ValueError("1Password reference must look like op://Vault/Item")
    client = await Client.authenticate(
        auth=token, integration_name=INTEGRATION_NAME, integration_version=INTEGRATION_VERSION
    )
    username = await client.secrets.resolve(f"{ref}/username")
    password = await client.secrets.resolve(f"{ref}/password")
    return username, password
