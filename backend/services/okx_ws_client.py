import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time

import websockets
from websockets.asyncio.client import ClientConnection

logger = logging.getLogger(__name__)

WS_DEMO_URL = "wss://wspap.okx.com:8443/ws/v5/private"
WS_LIVE_URL = "wss://ws.okx.com:8443/ws/v5/private"


def _ws_timestamp() -> int:
    """Unix timestamp in seconds for WebSocket login, matching OKX V5 spec."""
    return int(time.time())


def _sign(timestamp: int, secret_key: str) -> str:
    message = str(timestamp) + "GET" + "/users/self/verify"
    mac = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


class OKXWsClient:
    def __init__(self, api_key: str, secret_key: str, passphrase: str, trade_mode: str = "demo"):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.trade_mode = trade_mode

        self._ws_url = os.getenv("OKX_WS_URL", WS_DEMO_URL if trade_mode == "demo" else WS_LIVE_URL)
        self._ws: ClientConnection | None = None
        self._connected = False
        self._disconnected_at: float | None = None
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 30.0
        self._should_reconnect = True
        self._message_task: asyncio.Task | None = None
        self._order_callbacks: list[callable] = []
        self._subscriptions: list[dict] = []
        self._login_event = asyncio.Event()

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def fallback_to_rest(self) -> bool:
        if self._connected:
            return False
        if self._disconnected_at is None:
            return False
        return (time.time() - self._disconnected_at) > 30.0

    def on_order_update(self, callback: callable):
        """Register a callback for order updates.
        Callback signature: callback(ordId: str, state: str, order_data: dict)
        """
        self._order_callbacks.append(callback)

    async def connect(self):
        """Connect to OKX WebSocket, login, and start message loop."""
        self._should_reconnect = True
        self._reconnect_delay = 1.0
        await self._connect_and_login()

    async def _connect_and_login(self):
        logger.info(f"Connecting to OKX WebSocket: {self._ws_url}")
        try:
            self._ws = await websockets.connect(self._ws_url, ping_interval=None)
            self._connected = True
            self._disconnected_at = None
            logger.info("WebSocket connected, sending login...")

            await self._login()

            login_success = await self._wait_for_login(timeout=10.0)
            if not login_success:
                logger.error("Login failed or timed out")
                await self._ws.close()
                self._connected = False
                self._disconnected_at = time.time()
                return

            logger.info("Login successful, re-subscribing to channels...")
            for sub in self._subscriptions:
                await self._subscribe(sub["instType"], sub["instId"])

            self._message_task = asyncio.create_task(self._message_loop())
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._connected = False
            self._disconnected_at = time.time()
            if self._should_reconnect:
                asyncio.create_task(self._reconnect())

    async def _login(self):
        timestamp = _ws_timestamp()
        sign = _sign(timestamp, self.secret_key)
        login_msg = {
            "op": "login",
            "args": [{
                "apiKey": self.api_key,
                "passphrase": self.passphrase,
                "timestamp": timestamp,
                "sign": sign,
            }]
        }
        await self._ws.send(json.dumps(login_msg))

    async def _wait_for_login(self, timeout: float = 10.0) -> bool:
        try:
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                msg = json.loads(raw)
                event = msg.get("event", "")
                if event == "login":
                    code = msg.get("code", "")
                    if code == "0":
                        return True
                    logger.error(f"Login rejected: code={code} msg={msg.get('msg', '')}")
                    return False
                elif event == "error":
                    logger.error(f"Error during login: {msg}")
            return False
        except Exception as e:
            logger.error(f"Exception waiting for login: {e}")
            return False

    async def subscribe_orders(self, inst_type: str, inst_id: str):
        """Subscribe to orders channel for a specific instrument."""
        sub = {"instType": inst_type, "instId": inst_id}
        if sub not in self._subscriptions:
            self._subscriptions.append(sub)
        if self._connected:
            await self._subscribe(inst_type, inst_id)

    async def _subscribe(self, inst_type: str, inst_id: str):
        sub_msg = {
            "op": "subscribe",
            "args": [{
                "channel": "orders",
                "instType": inst_type,
                "instId": inst_id,
            }]
        }
        await self._ws.send(json.dumps(sub_msg))
        logger.info(f"Subscribed to orders: {inst_type} {inst_id}")

    async def disconnect(self):
        """Close WebSocket connection."""
        self._should_reconnect = False
        if self._message_task:
            self._message_task.cancel()
            try:
                await self._message_task
            except asyncio.CancelledError:
                pass
            self._message_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._connected = False
        self._disconnected_at = time.time()
        logger.info("WebSocket disconnected")

    async def _reconnect(self):
        while self._should_reconnect and not self._connected:
            delay = min(self._reconnect_delay, self._max_reconnect_delay)
            logger.info(f"Reconnecting in {delay:.1f}s...")
            await asyncio.sleep(delay)
            self._reconnect_delay *= 2
            await self._connect_and_login()
        if self._connected:
            self._reconnect_delay = 1.0

    async def _message_loop(self):
        """Internal: read messages from WebSocket."""
        try:
            while self._connected:
                try:
                    raw = await self._ws.recv()
                except websockets.ConnectionClosed:
                    logger.warning("WebSocket connection closed")
                    break
                except asyncio.CancelledError:
                    break

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON received: {raw[:200]}")
                    continue

                if "event" in msg:
                    await self._handle_event(msg)
                elif "arg" in msg and "data" in msg:
                    await self._handle_data(msg)
                else:
                    logger.debug(f"Unknown message: {msg}")

        except Exception as e:
            logger.error(f"Message loop error: {e}")
        finally:
            self._connected = False
            self._disconnected_at = time.time()
            if self._should_reconnect:
                asyncio.create_task(self._reconnect())

    async def _handle_event(self, msg: dict):
        event = msg.get("event", "")
        if event == "subscribe":
            arg = msg.get("arg", {})
            logger.info(f"Subscribed: channel={arg.get('channel')} instId={arg.get('instId')}")
        elif event == "error":
            logger.error(f"WS error: code={msg.get('code')} msg={msg.get('msg')}")
        elif event == "login":
            pass  # handled in _wait_for_login
        else:
            logger.debug(f"Event: {event} {msg}")

    async def _handle_data(self, msg: dict):
        arg = msg.get("arg", {})
        channel = arg.get("channel", "")
        data_list = msg.get("data", [])

        if channel == "orders":
            for item in data_list:
                ord_id = item.get("ordId", "")
                state = item.get("state", "")
                logger.info(f"Order update: ordId={ord_id} instId={item.get('instId')} state={state} "
                            f"side={item.get('side')} px={item.get('px')} sz={item.get('sz')} "
                            f"fillPx={item.get('fillPx')} fillSz={item.get('fillSz')}")
                for cb in self._order_callbacks:
                    try:
                        cb(ord_id, state, item)
                    except Exception as e:
                        logger.error(f"Order callback error: {e}")