"""S3 storage service for document uploads."""

import uuid

import boto3
from botocore.config import Config as BotoConfig

from ..config import settings
from ..logger import logger


def _get_client():
    """Create S3 client from settings."""
    return boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        endpoint_url=settings.aws_s3_endpoint_url,
        region_name=settings.aws_default_region,
        config=BotoConfig(signature_version="s3v4"),
    )


def upload_document(file_bytes: bytes, filename: str, content_type: str) -> str:
    """Upload document to S3. Returns the S3 key."""
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    s3_key = f"documents/{uuid.uuid4().hex}.{ext}"

    client = _get_client()
    client.put_object(
        Bucket=settings.aws_s3_bucket_name,
        Key=s3_key,
        Body=file_bytes,
        ContentType=content_type,
    )
    logger.info(f"Uploaded document to s3://{settings.aws_s3_bucket_name}/{s3_key}")
    return s3_key


def get_presigned_url(s3_key: str, expires_in: int = 3600) -> str:
    """Generate presigned URL for viewing a document."""
    client = _get_client()
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.aws_s3_bucket_name, "Key": s3_key},
        ExpiresIn=expires_in,
    )
    return url


def delete_document(s3_key: str) -> None:
    """Delete document from S3."""
    client = _get_client()
    client.delete_object(Bucket=settings.aws_s3_bucket_name, Key=s3_key)
    logger.info(f"Deleted document s3://{settings.aws_s3_bucket_name}/{s3_key}")
