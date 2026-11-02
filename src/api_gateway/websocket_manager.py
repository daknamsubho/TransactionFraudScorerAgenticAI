"""WebSocket connection manager for real-time transaction score event broadcasting."""

import logging
from dataclasses import dataclass

from fastapi import WebSocket

from api_gateway.schemas import WebSocketTransactionEvent

logger = logging.getLogger(__name__)


@dataclass
class ClientSubscription:
    """Tracks an active WebSocket connection and optional username filter."""

    websocket: WebSocket
    username: str | None = None


class ConnectionManager:
    """Manages active WebSocket clients and broadcasts transaction score events."""

    def __init__(self) -> None:
        self._connections: list[ClientSubscription] = []

    async def connect(self, websocket: WebSocket, username: str | None = None) -> None:
        """Accept a new WebSocket connection and register its subscription."""
        await websocket.accept()
        self._connections.append(ClientSubscription(websocket=websocket, username=username))
        logger.info(
            "WebSocket client connected (filter username=%s, active=%d)",
            username,
            len(self._connections),
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a disconnected WebSocket client."""
        self._connections = [sub for sub in self._connections if sub.websocket is not websocket]
        logger.info("WebSocket client disconnected (active=%d)", len(self._connections))

    async def broadcast_event(self, event: WebSocketTransactionEvent) -> None:
        """Broadcast a WebSocketTransactionEvent to all matching connected clients."""
        payload = event.model_dump(mode="json")
        stale: list[WebSocket] = []

        for sub in list(self._connections):
            if sub.username is not None and sub.username != event.username:
                continue
            try:
                await sub.websocket.send_json(payload)
            except Exception as exc:
                logger.warning("Failed to send WebSocket event to client (%s), removing connection.", exc)
                stale.append(sub.websocket)

        for ws in stale:
            self.disconnect(ws)
