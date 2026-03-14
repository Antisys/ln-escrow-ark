"""
WebSocket support for real-time deal updates.
Replaces client-side polling with server-push notifications.
"""
import logging
import re
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

# UUID-v4 pattern for deal_id validation
_DEAL_ID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


class ConnectionManager:
    """Manages WebSocket connections per deal."""

    _MAX_CONNECTIONS_PER_DEAL = 20  # Prevent connection flooding

    def __init__(self):
        # deal_id -> set of active WebSocket connections
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, deal_id: str, ws: WebSocket) -> bool:
        """Accept and register a WebSocket connection. Returns False if rejected."""
        existing = self._connections.get(deal_id, set())
        if len(existing) >= self._MAX_CONNECTIONS_PER_DEAL:
            await ws.close(code=1008, reason="Too many connections for this deal")
            logger.warning("[WS] Rejected connection to deal %s... (limit %d reached)",
                           deal_id[:8], self._MAX_CONNECTIONS_PER_DEAL)
            return False
        await ws.accept()
        if deal_id not in self._connections:
            self._connections[deal_id] = set()
        self._connections[deal_id].add(ws)
        logger.info("[WS] Client connected to deal %s... (%d total)", deal_id[:8], len(self._connections[deal_id]))
        return True

    def disconnect(self, deal_id: str, ws: WebSocket):
        if deal_id in self._connections:
            self._connections[deal_id].discard(ws)
            if not self._connections[deal_id]:
                del self._connections[deal_id]

    async def broadcast(self, deal_id: str, event: str, data: dict = None):
        """Send event to all clients watching a deal."""
        conns = self._connections.get(deal_id, set())
        if not conns:
            return
        message = {"event": event}
        if data:
            message["data"] = data
        dead = []
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            conns.discard(ws)

    def has_subscribers(self, deal_id: str) -> bool:
        return bool(self._connections.get(deal_id))


# Singleton manager — imported by deals.py to broadcast events
manager = ConnectionManager()


@router.websocket("/ws/deals/{deal_id}")
async def deal_websocket(websocket: WebSocket, deal_id: str):
    """
    WebSocket endpoint for real-time deal updates.
    Client connects and receives JSON events like:
      {"event": "deal:updated", "data": {...}}
      {"event": "deal:funded"}
      {"event": "invoice:paid"}
    """
    # Validate deal_id format to prevent dict key pollution
    if not _DEAL_ID_RE.match(deal_id):
        await websocket.close(code=1008, reason="Invalid deal ID format")
        return

    accepted = await manager.connect(deal_id, websocket)
    if not accepted:
        return
    try:
        while True:
            # Keep alive — client can send pings or we just wait
            msg = await websocket.receive_text()
            # Client can send "ping", we reply "pong"
            if msg == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(deal_id, websocket)
    except Exception:
        manager.disconnect(deal_id, websocket)
