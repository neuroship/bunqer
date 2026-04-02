"""Server-Sent Events for real-time updates."""

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from ..auth import verify_token
from ..logger import logger

router = APIRouter(prefix="/events", tags=["events"])

# Global event queue for broadcasting
_event_subscribers: list[asyncio.Queue] = []


def broadcast_event(event_type: str, data: dict):
    """Broadcast an event to all connected clients."""
    event = {
        "type": event_type,
        "data": data,
        "timestamp": datetime.now().isoformat(),
    }
    logger.info(f"Broadcasting event: {event_type} - {data}")

    for queue in _event_subscribers:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # Skip if queue is full


async def event_generator() -> AsyncGenerator[str, None]:
    """Generate SSE events for a client."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _event_subscribers.append(queue)

    try:
        # Send initial connection event
        yield f"data: {json.dumps({'type': 'connected', 'message': 'Connected to event stream'})}\n\n"

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive
                yield f": keepalive\n\n"
    finally:
        _event_subscribers.remove(queue)


@router.get("/stream")
async def event_stream(request: Request):
    """SSE endpoint for real-time events.

    Accepts JWT via Authorization: Bearer header.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = auth_header[7:]  # Strip "Bearer "
    username = verify_token(token)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Helper functions for common events
def send_sync_started(account_name: str, account_id: int):
    broadcast_event("sync_started", {
        "account_name": account_name,
        "account_id": account_id,
        "message": f"Starting sync for {account_name}...",
    })


def send_sync_progress(account_name: str, fetched: int, new: int):
    broadcast_event("sync_progress", {
        "account_name": account_name,
        "fetched": fetched,
        "new": new,
        "message": f"Fetched {fetched} transactions, {new} new",
    })


def send_sync_completed(account_name: str, new_count: int):
    broadcast_event("sync_completed", {
        "account_name": account_name,
        "new_count": new_count,
        "message": f"Sync complete for {account_name}: {new_count} new transactions",
    })


def send_sync_error(account_name: str, error: str):
    broadcast_event("sync_error", {
        "account_name": account_name,
        "error": error,
        "message": f"Sync failed for {account_name}: {error}",
    })


def send_notification(message: str, level: str = "info"):
    broadcast_event("notification", {
        "message": message,
        "level": level,
    })
