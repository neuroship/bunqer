"""Resolve secrets from 1Password via a Service Account."""

from onepassword.client import Client

INTEGRATION_NAME = "Bunqer Invoice Fetcher"
INTEGRATION_VERSION = "v1.0.0"


def _check_ref(ref: str) -> str:
    ref = ref.strip()
    if not ref.startswith("op://") or ref.count("/") < 4:
        raise ValueError(f"1Password reference must look like op://Vault/Item/field, got '{ref}'")
    return ref


async def _client(token: str) -> Client:
    return await Client.authenticate(
        auth=token, integration_name=INTEGRATION_NAME, integration_version=INTEGRATION_VERSION
    )


async def resolve_login(token: str, username_ref: str, password_ref: str) -> tuple[str, str]:
    """Resolve username and password from two secret references (op://Vault/Item/field)."""
    username_ref, password_ref = _check_ref(username_ref), _check_ref(password_ref)
    client = await _client(token)
    username = await client.secrets.resolve(username_ref)
    password = await client.secrets.resolve(password_ref)
    return username, password


async def resolve_totp(token: str, totp_ref: str) -> str:
    """Resolve the current one-time code for a TOTP field reference.

    Resolved right before use so the code is fresh. Accepts a plain field ref and
    appends ?attribute=otp when missing.
    """
    ref = _check_ref(totp_ref)
    if "?attribute=otp" not in ref:
        ref += "?attribute=otp"
    client = await _client(token)
    return await client.secrets.resolve(ref)
