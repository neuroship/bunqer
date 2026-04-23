"""Application configuration loaded from environment variables."""

import secrets

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings from environment variables."""

    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/vibe_accountant"

    # API Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Bunq
    bunq_api_key: str | None = None
    bunq_environment: str = "PRODUCTION"

    # Frontend base URL (used for CORS)
    frontend_url: str = "http://localhost:5173"

    # Authentication
    auth_username: str = "admin"
    auth_password_hash: str | None = None  # bcrypt hash of password
    jwt_secret_key: str = secrets.token_urlsafe(32)  # Auto-generate if not set
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    # WebAuthn / Passkey
    webauthn_rp_id: str = "localhost"  # Relying party ID (domain name)
    webauthn_rp_name: str = "Vibe Accountant"
    webauthn_origin: str = "http://localhost:5173"  # Expected origin for verification

    # AWS S3
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_s3_bucket_name: str | None = None
    aws_s3_endpoint_url: str | None = None
    aws_default_region: str = "eu-west-1"

    # Mistral AI
    mistral_api_key: str | None = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
