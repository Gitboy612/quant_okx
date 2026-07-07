import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.strategy_engine import strategy_engine

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


@router.get("/api/market/ticker/{symbol}")
def get_ticker(symbol: str):
    return {"symbol": symbol, "message": "行情数据请通过 WebSocket 实时获取"}
