"""Integration management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..logger import logger
from ..models import Integration, IntegrationCreate, IntegrationResponse

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", response_model=list[IntegrationResponse])
async def list_integrations(db: Session = Depends(get_db)):
    """List all integrations."""
    integrations = db.query(Integration).all()
    return integrations


@router.get("/{integration_id}", response_model=IntegrationResponse)
async def get_integration(integration_id: int, db: Session = Depends(get_db)):
    """Get a specific integration by ID."""
    integration = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration


@router.post("", response_model=IntegrationResponse)
async def create_integration(
    integration: IntegrationCreate, db: Session = Depends(get_db)
):
    """Create a new integration (bunq connection)."""
    db_integration = Integration(
        name=integration.name,
        type=integration.type,
        sub_type=integration.sub_type,
        secret_key=integration.secret_key,
    )
    db.add(db_integration)
    db.commit()
    db.refresh(db_integration)
    logger.info(f"Created integration: {db_integration.name} (ID: {db_integration.id})")
    return db_integration


@router.delete("/{integration_id}")
async def delete_integration(integration_id: int, db: Session = Depends(get_db)):
    """Delete an integration."""
    integration = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    db.delete(integration)
    db.commit()
    logger.info(f"Deleted integration: {integration.name} (ID: {integration_id})")
    return {"status": "deleted", "id": integration_id}
