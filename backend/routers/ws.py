import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.strategy_engine import strategy_engine
from services.market_data_service import market_data_service

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, key: str, ws: WebSocket):
        await ws.accept()
        if key not in self._connections:
            self._connections[key] = []
        self._connections[key].append(ws)

    def disconnect(self, key: str, ws: WebSocket):
        if key in self._connections:
            self._connections[key].remove(ws)

    async def broadcast(self, key: str, message: dict):
        if key in self._connections:
            for ws in self._connections[key]:
                try:
                    await ws.send_json(message)
                except Exception:
                    pass


manager = ConnectionManager()


@router.websocket("/ws/strategy/{instance_id}")
async def strategy_ws(ws: WebSocket, instance_id: int):
    key = f"strategy_{instance_id}"
    await manager.connect(key, ws)
    try:
        while True:
            data = await ws.receive_text()
            status = strategy_engine.get_strategy_status(instance_id)
            await manager.broadcast(key, {"instance_id": instance_id, "status": status, "data": data})
    except WebSocketDisconnect:
        manager.disconnect(key, ws)


@router.websocket("/ws/dashboard")
async def dashboard_ws(ws: WebSocket):
    key = "dashboard"
    await manager.connect(key, ws)
    try:
        while True:
            await ws.receive_text()
            running_ids = strategy_engine.get_running_ids()
            await manager.broadcast(key, {
                "type": "dashboard",
                "running_strategies": running_ids,
                "active_count": len(running_ids),
            })
    except WebSocketDisconnect:
        manager.disconnect(key, ws)


@router.websocket("/ws/market/{symbol}")
async def market_ws(ws: WebSocket, symbol: str):
    """Push real-time ticker updates for *symbol* via the public WebSocket.

    On connect: subscribes to the symbol's ticker through
    :class:`MarketDataService`.  Incoming ticker data is pushed to the client
    as JSON messages.  On disconnect: unsubscribes (reference-counted).
    """
    await ws.accept()
    queue: asyncio.Queue = asyncio.Queue()
    push_task: asyncio.Task | None = None

    def _on_ticker(ticker_data: dict):
        try:
            queue.put_nowait(ticker_data)
        except Exception:
            pass

    try:
        await market_data_service.subscribe_ticker(symbol, _on_ticker)

        # Send the latest cached ticker immediately (if available).
        cached = market_data_service.get_latest_ticker(symbol)
        if cached:
            await ws.send_json({"type": "ticker", "symbol": symbol, "data": cached})

        # Concurrent task: consume the queue and send to the client.
        async def _push_loop():
            while True:
                ticker = await queue.get()
                await ws.send_json({"type": "ticker", "symbol": symbol, "data": ticker})

        push_task = asyncio.create_task(_push_loop())

        # Main loop: keep the connection alive, handle client pings.
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if push_task is not None:
            push_task.cancel()
            try:
                await push_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await market_data_service.unsubscribe_ticker(symbol, _on_ticker)
        except Exception:
            pass


@router.get("/api/market/ticker/{symbol}")
def get_ticker(symbol: str):
    return {"symbol": symbol, "message": "行情数据请通过 WebSocket 实时获取"}
