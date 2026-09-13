"""Resolve secrets from 1Password via a Service Account."""

from onepassword.client import Client

INTEGRATION_NAME = "Bunqer Invoice Fetcher"
INTEGRATION_VERSION = "v1.0.0"


def _check_ref(ref: str) -> str:
    ref = ref.strip()
    if not ref.startswith("op://") or ref.count("/") < 4:
        raise ValueError(f"1Password reference must look like op://Vault/Item/field, got '{ref}'")
    return ref


async def resolve_login(token: str, username_ref: str, password_ref: str) -> tuple[str, str]:
    """Resolve username and password from two secret references (op://Vault/Item/field)."""
    username_ref, password_ref = _check_ref(username_ref), _check_ref(password_ref)
    client = await Client.authenticate(
        auth=token, integration_name=INTEGRATION_NAME, integration_version=INTEGRATION_VERSION
    )
    username = await client.secrets.resolve(username_ref)
    password = await client.secrets.resolve(password_ref)
    return username, password
