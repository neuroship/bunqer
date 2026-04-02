"""FastAPI application entry point."""

import traceback
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .auth import get_current_user
from .config import settings
from .logger import logger
from .routes import auth, categories, events, health, integrations, invoices, passkeys, settings as settings_routes, setup, transactions


def run_migrations():
    """Run database migrations using Alembic."""
    # Get the path to alembic.ini relative to the api directory
    # main.py is at api/src/vibe_accountant/main.py, so 3 parents up to api/
    api_dir = Path(__file__).parent.parent.parent
    alembic_ini = api_dir / "alembic.ini"

    if not alembic_ini.exists():
        logger.warning(f"alembic.ini not found at {alembic_ini}, skipping migrations")
        return

    logger.info("Running database migrations...")
    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(alembic_cfg, "head")
    logger.info("Database migrations completed")

# Create FastAPI app
app = FastAPI(
    title="Vibe Accountant API",
    description="Accounting web app with bunq integration",
    version="0.1.0",
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler that logs all unhandled exceptions."""
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
    logger.error(f"Traceback:\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Auth dependency for protected routes
auth_dependency = [Depends(get_current_user)]

# Include public routers (no auth required)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(events.router)  # SSE handles auth via query param (EventSource limitation)
app.include_router(passkeys.router)  # Mixed auth: login endpoints public, management endpoints use Depends

# Include protected routers (auth required)
app.include_router(integrations.router, dependencies=auth_dependency)
app.include_router(setup.router, dependencies=auth_dependency)
app.include_router(transactions.router, dependencies=auth_dependency)
app.include_router(invoices.router, dependencies=auth_dependency)
app.include_router(categories.router, dependencies=auth_dependency)
app.include_router(settings_routes.router, dependencies=auth_dependency)


@app.on_event("startup")
async def startup_event():
    """Run migrations, sync accounts, and log startup message."""
    import asyncio
    logger.info("Vibe Accountant API starting up...")
    run_migrations()

    # Auto-sync all accounts on startup (run in background to not block startup)
    async def background_sync():
        # Small delay to let the server fully start
        await asyncio.sleep(2)
        from .routes.setup import auto_sync_all_accounts
        try:
            auto_sync_all_accounts()
        except Exception as e:
            logger.error(f"Failed to sync accounts on startup: {e}")

    asyncio.create_task(background_sync())


@app.on_event("shutdown")
async def shutdown_event():
    """Log shutdown message."""
    logger.info("Vibe Accountant API shutting down...")
