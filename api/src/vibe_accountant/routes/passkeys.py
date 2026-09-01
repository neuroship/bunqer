"""Passkey (WebAuthn) authentication routes."""

import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from ..auth import create_access_token, get_current_user, security, verify_token
from ..config import settings
from ..database import get_db
from ..logger import logger
from ..models import WebAuthnCredential, WebAuthnCredentialResponse

router = APIRouter(prefix="/auth/passkeys", tags=["passkeys"])

# In-memory challenge store with TTL (single-user app, so this is fine)
_challenges: dict[str, tuple[bytes, float]] = {}
_CHALLENGE_TTL = 300  # 5 minutes


def _store_challenge(key: str, challenge: bytes) -> None:
    _challenges[key] = (challenge, time.time())


def _pop_challenge(key: str) -> bytes | None:
    entry = _challenges.pop(key, None)
    if entry is None:
        return None
    challenge, ts = entry
    if time.time() - ts > _CHALLENGE_TTL:
        return None
    return challenge


# ── Registration (signed-in user, or enrollment token when no passkey exists) ──


async def require_registration_access(
    x_enrollment_token: str | None = Header(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> str:
    """
    Allow passkey registration for a signed-in user.

    When no passkey is registered yet (fresh install or lost-all-devices recovery),
    accept the PASSKEY_ENROLLMENT_TOKEN instead so the first passkey can be enrolled.
    """
    if credentials is not None:
        username = verify_token(credentials.credentials)
        if username is not None:
            return username

    if db.query(WebAuthnCredential).count() > 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not settings.passkey_enrollment_token:
        logger.error("Enrollment attempted but PASSKEY_ENROLLMENT_TOKEN is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No passkeys registered and PASSKEY_ENROLLMENT_TOKEN is not configured.",
        )

    if not x_enrollment_token or not secrets.compare_digest(
        x_enrollment_token, settings.passkey_enrollment_token
    ):
        logger.warning("Passkey enrollment rejected: invalid enrollment token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid enrollment token",
        )

    logger.info("Passkey enrollment authorized via enrollment token")
    return settings.auth_username


@router.get("/status")
async def passkey_status(db: Session = Depends(get_db)):
    """Public: whether any passkey is registered, and whether enrollment is open."""
    count = db.query(WebAuthnCredential).count()
    return {
        "registered": count > 0,
        "enrollment_available": count == 0 and bool(settings.passkey_enrollment_token),
    }


class RegisterPasskeyRequest(BaseModel):
    """Attestation response from the browser."""
    id: str
    rawId: str
    type: str
    response: dict
    name: str | None = None


@router.get("/register-options")
async def register_options(
    username: str = Depends(require_registration_access),
    db: Session = Depends(get_db),
):
    """Generate registration options for a new passkey."""
    existing = db.query(WebAuthnCredential).all()
    exclude_credentials = [
        PublicKeyCredentialDescriptor(id=c.credential_id)
        for c in existing
    ]

    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=username.encode(),
        user_name=username,
        user_display_name=username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        supported_pub_key_algs=[
            COSEAlgorithmIdentifier.ECDSA_SHA_256,
            COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
        ],
        exclude_credentials=exclude_credentials,
    )

    _store_challenge("registration", options.challenge)

    # Serialize to JSON-friendly dict
    return {
        "challenge": urlsafe_b64encode(options.challenge).decode().rstrip("="),
        "rp": {"id": options.rp.id, "name": options.rp.name},
        "user": {
            "id": urlsafe_b64encode(options.user.id).decode().rstrip("="),
            "name": options.user.name,
            "displayName": options.user.display_name,
        },
        "pubKeyCredParams": [
            {"type": "public-key", "alg": p.alg.value} for p in options.pub_key_cred_params
        ],
        "timeout": options.timeout,
        "excludeCredentials": [
            {
                "type": "public-key",
                "id": urlsafe_b64encode(c.id).decode().rstrip("="),
            }
            for c in (options.exclude_credentials or [])
        ],
        "authenticatorSelection": {
            "residentKey": options.authenticator_selection.resident_key.value
            if options.authenticator_selection
            else "preferred",
            "userVerification": options.authenticator_selection.user_verification.value
            if options.authenticator_selection
            else "preferred",
        },
        "attestation": options.attestation.value if options.attestation else "none",
    }


@router.post("/register")
async def register_passkey(
    body: RegisterPasskeyRequest,
    username: str = Depends(require_registration_access),
    db: Session = Depends(get_db),
):
    """Verify and store a new passkey registration."""
    challenge = _pop_challenge("registration")
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration challenge expired or missing. Please try again.",
        )

    try:
        verification = verify_registration_response(
            credential=body.model_dump(),
            expected_challenge=challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
        )
    except Exception as e:
        logger.error(f"Passkey registration verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passkey registration verification failed",
        )

    credential = WebAuthnCredential(
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        name=body.name or "Passkey",
    )
    db.add(credential)
    db.commit()
    db.refresh(credential)

    logger.info(f"Passkey registered for user '{username}': {credential.name}")
    return WebAuthnCredentialResponse.model_validate(credential)


# ── Login (public — passkey is the only credential) ─────────────────


def _authentication_options(db: Session, challenge_key: str) -> dict:
    """Generate WebAuthn authentication options and store the challenge under challenge_key."""
    credentials = db.query(WebAuthnCredential).all()
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No passkeys registered.",
        )

    allow_credentials = [
        PublicKeyCredentialDescriptor(id=c.credential_id)
        for c in credentials
    ]

    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    _store_challenge(challenge_key, options.challenge)

    return {
        "challenge": urlsafe_b64encode(options.challenge).decode().rstrip("="),
        "rpId": settings.webauthn_rp_id,
        "timeout": options.timeout,
        "allowCredentials": [
            {
                "type": "public-key",
                "id": urlsafe_b64encode(c.id).decode().rstrip("="),
            }
            for c in allow_credentials
        ],
        "userVerification": options.user_verification.value
        if options.user_verification
        else "preferred",
    }


class PasskeyAssertion(BaseModel):
    """Passkey assertion from the browser (navigator.credentials.get)."""
    id: str
    rawId: str
    type: str
    response: dict


def verify_passkey_assertion(
    db: Session, body: PasskeyAssertion, challenge_key: str
) -> WebAuthnCredential:
    """Verify an assertion against the challenge stored under challenge_key.

    Raises HTTPException on an expired challenge, unknown passkey or bad signature.
    """
    challenge = _pop_challenge(challenge_key)
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passkey challenge expired or missing. Please try again.",
        )

    # Find the credential by ID
    raw_id = urlsafe_b64decode(body.rawId + "==")
    credential = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.credential_id == raw_id)
        .first()
    )
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown passkey.",
        )

    try:
        verification = verify_authentication_response(
            credential={
                "id": body.id,
                "rawId": body.rawId,
                "type": body.type,
                "response": body.response,
            },
            expected_challenge=challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
            credential_public_key=credential.public_key,
            credential_current_sign_count=credential.sign_count,
        )
    except Exception as e:
        logger.error(f"Passkey verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Passkey verification failed",
        )

    # Update sign count
    credential.sign_count = verification.new_sign_count
    db.commit()
    return credential


@router.get("/login-options")
async def login_options(db: Session = Depends(get_db)):
    """Generate authentication options for passkey login."""
    return _authentication_options(db, "login")


class PasskeyLoginResponse(BaseModel):
    """Login response after successful passkey verification."""
    access_token: str
    token_type: str = "bearer"
    username: str


@router.post("/login", response_model=PasskeyLoginResponse)
async def passkey_login(
    body: PasskeyAssertion,
    db: Session = Depends(get_db),
):
    """Verify a passkey assertion and return a JWT token."""
    credential = verify_passkey_assertion(db, body, "login")

    username = settings.auth_username
    access_token = create_access_token(username)
    logger.info(f"Passkey login successful for '{username}' via '{credential.name}'")

    return PasskeyLoginResponse(
        access_token=access_token,
        username=username,
    )


# ── Step-up verification (requires auth) ────────────────────────────


@router.get("/verify-options")
async def verify_options(
    username: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Authentication options to re-verify the signed-in user before a sensitive action.

    The resulting assertion is consumed by the action endpoint (e.g. draft payment approval).
    """
    return _authentication_options(db, "verify")


# ── Management (requires auth) ──────────────────────────────────────


@router.get("", response_model=list[WebAuthnCredentialResponse])
async def list_passkeys(
    username: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all registered passkeys."""
    credentials = db.query(WebAuthnCredential).order_by(WebAuthnCredential.created_at.desc()).all()
    return [WebAuthnCredentialResponse.model_validate(c) for c in credentials]


@router.delete("/{passkey_id}")
async def delete_passkey(
    passkey_id: int,
    username: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a registered passkey."""
    credential = db.query(WebAuthnCredential).filter(WebAuthnCredential.id == passkey_id).first()
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passkey not found",
        )

    # Passkeys are the only credential — deleting the last one locks the account out
    if db.query(WebAuthnCredential).count() == 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your only passkey. Register another one first.",
        )

    db.delete(credential)
    db.commit()
    logger.info(f"Passkey '{credential.name}' (id={passkey_id}) deleted by '{username}'")
    return {"detail": "Passkey deleted"}
