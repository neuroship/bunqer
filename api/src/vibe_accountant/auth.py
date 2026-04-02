"""Authentication utilities for single-user JWT-based auth."""

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from .config import settings
from .logger import logger

# HTTP Bearer token security scheme
security = HTTPBearer(auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def create_access_token(username: str) -> str:
    """Create a JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode = {
        "sub": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_mfa_token(username: str) -> str:
    """Create a short-lived token that proves password was verified (valid 5 min)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    to_encode = {
        "sub": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "purpose": "mfa",
    }
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_mfa_token(token: str) -> str | None:
    """Verify an MFA token and return the username if valid."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("purpose") != "mfa":
            return None
        return payload.get("sub")
    except JWTError as e:
        logger.debug(f"MFA token verification failed: {e}")
        return None


def verify_token(token: str) -> str | None:
    """Verify a JWT token and return the username if valid."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        username: str = payload.get("sub")
        if username is None:
            return None
        return username
    except JWTError as e:
        logger.debug(f"JWT verification failed: {e}")
        return None


def authenticate_user(username: str, password: str) -> bool:
    """Authenticate user against configured credentials."""
    if not settings.auth_password_hash:
        logger.warning("AUTH_PASSWORD_HASH not configured - authentication disabled")
        return False

    if username != settings.auth_username:
        return False

    try:
        return verify_password(password, settings.auth_password_hash)
    except Exception as e:
        logger.error("Password verification failed")
        raise


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    """Dependency to get the current authenticated user from JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    username = verify_token(credentials.credentials)
    if username is None:
        raise credentials_exception

    return username


# Utility function to generate password hash (run once to create hash for .env)
def generate_password_hash(password: str) -> str:
    """Generate a bcrypt hash for a password. Use this to create AUTH_PASSWORD_HASH."""
    return hash_password(password)
