"""Authentication routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import authenticate_user, create_access_token, create_mfa_token, generate_password_hash
from ..config import settings
from ..database import get_db
from ..logger import logger
from ..models import WebAuthnCredential

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Login request body."""

    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response with access token."""

    access_token: str
    token_type: str = "bearer"
    username: str
    mfa_required: bool = False
    mfa_token: str | None = None


class AuthStatusResponse(BaseModel):
    """Auth status response."""

    authenticated: bool
    username: str | None = None


class HashPasswordRequest(BaseModel):
    """Hash password request body."""

    password: str


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user and return JWT token (or MFA challenge if passkeys registered)."""
    logger.info(f"Login attempt for user: {request.username}")

    try:
        if not settings.auth_password_hash:
            logger.error("AUTH_PASSWORD_HASH not configured")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication not configured. Set AUTH_PASSWORD_HASH in environment.",
            )

        if not authenticate_user(request.username, request.password):
            logger.warning(f"Failed login attempt for user: {request.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check if passkeys are registered — if so, require MFA
        has_passkeys = db.query(WebAuthnCredential).count() > 0
        if has_passkeys:
            mfa_token = create_mfa_token(request.username)
            logger.info(f"Password OK for '{request.username}', MFA required")
            return LoginResponse(
                access_token="",
                token_type="bearer",
                username=request.username,
                mfa_required=True,
                mfa_token=mfa_token,
            )

        access_token = create_access_token(request.username)
        logger.info(f"User '{request.username}' logged in successfully")

        return LoginResponse(
            access_token=access_token,
            username=request.username,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during login",
        )


@router.post("/hash-password")
async def hash_password_endpoint(request: HashPasswordRequest):
    """
    Utility endpoint to generate a password hash.
    Only available when AUTH_PASSWORD_HASH is not yet configured.
    Use the returned hash to set AUTH_PASSWORD_HASH in your .env file.
    """
    logger.info("Password hash generation requested")

    try:
        if settings.auth_password_hash:
            logger.warning("Hash-password endpoint called but auth is already configured")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password hashing endpoint disabled when auth is configured",
            )

        hashed = generate_password_hash(request.password)
        logger.info("Password hash generated successfully")
        return {
            "password_hash": hashed,
            "instruction": "Add this to your .env file as: AUTH_PASSWORD_HASH='<hash>'"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during password hashing: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during password hashing",
        )
