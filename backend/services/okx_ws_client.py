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
from websockets.protocol import State

logger = logging.getLogger(__name__)

WS_DEMO_URL = "wss://wspap.okx.com:8443/ws/v5/private"
WS_LIVE_URL = "wss://ws.okx.com:8443/ws/v5/private"
WS_PUBLIC_DEMO_URL = "wss://wspap.okx.com:8443/ws/v5/public"
WS_PUBLIC_LIVE_URL = "wss://ws.okx.com:8443/ws/v5/public"

# Circuit breaker states for the WebSocket reconnect logic.
CIRCUIT_CLOSED = "closed"
CIRCUIT_OPEN = "open"

# Mapping from short interval labels to OKX candle channel names.
CANDLE_INTERVALS = {
    "1m": "candle1m",
    "5m": "candle5m",
    "15m": "candle15m",
    "1H": "candle1H",
    "4H": "candle4H",
    "1D": "candle1D",
}


def _ws_timestamp() -> int:
    """Unix timestamp in seconds for WebSocket login, matching OKX V5 spec."""
    return int(time.time())


def _sign(timestamp: int, secret_key: str) -> str:
    message = str(timestamp) + "GET" + "/users/self/verify"
    mac = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


def _get_proxy() -> str | None:
    """Return the first available proxy URL from the environment, or None.

    Checks ``HTTPS_PROXY``, ``ALL_PROXY``, ``HTTP_PROXY`` in that order.
    """
    for var in ("HTTPS_PROXY", "ALL_PROXY", "HTTP_PROXY"):
        value = os.getenv(var)
        if value:
            return value
    return None


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

        # Circuit breaker state for the reconnect logic.
        self._circuit_state = CIRCUIT_CLOSED
        self._reconnect_count = 0
        self._max_reconnect = 20
        self._probe_task: asyncio.Task | None = None

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

    @property
    def is_healthy(self) -> bool:
        """True only when the circuit breaker is closed AND the underlying
        WebSocket connection is alive (open).
        """
        if self._circuit_state != CIRCUIT_CLOSED:
            return False
        return self._ws is not None and self._ws.state == State.OPEN

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
            connect_kwargs = {"ping_interval": None}
            proxy = _get_proxy()
            if proxy:
                connect_kwargs["proxy"] = proxy
                logger.info(f"Using proxy for WebSocket connection: {proxy}")
            self._ws = await websockets.connect(self._ws_url, **connect_kwargs)
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
            # Reconnect is managed solely by the _reconnect() while loop (and
            # _probe_reconnect() once the circuit is open). Spawning a new
            # reconnect task here would cause duplicate coroutines to multiply
            # exponentially on repeated failures.

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
                # Successfully reconnected: reset failure counter and backoff.
                self._reconnect_count = 0
                self._reconnect_delay = 1.0
                break
            # Failed attempt - count toward the circuit breaker threshold.
            self._reconnect_count += 1
            if self._reconnect_count >= self._max_reconnect:
                logger.error(
                    f"Circuit breaker opened after {self._reconnect_count} "
                    f"failed reconnect attempts; entering probe mode"
                )
                self._circuit_state = CIRCUIT_OPEN
                self._probe_task = asyncio.create_task(self._probe_reconnect())
                break

    async def _probe_reconnect(self):
        """Background probe used while the circuit is open.

        Every 60 seconds, attempts a single reconnect. On success the circuit
        is closed and counters reset; on failure the probe keeps looping.
        Exits when ``_should_reconnect`` becomes False or the circuit was
        already closed by another path.
        """
        logger.info("Circuit open: starting 60s reconnect probe")
        while self._should_reconnect and self._circuit_state == CIRCUIT_OPEN:
            await asyncio.sleep(60)
            if not self._should_reconnect or self._circuit_state != CIRCUIT_OPEN:
                break
            logger.info("Probe: attempting reconnect...")
            try:
                await self._connect_and_login()
            except Exception as e:
                logger.error(f"Probe reconnect attempt failed: {e}")
            if self._connected:
                self._circuit_state = CIRCUIT_CLOSED
                self._reconnect_count = 0
                self._reconnect_delay = 1.0
                logger.info("Probe reconnect succeeded - circuit closed")
                return
            logger.info("Probe reconnect failed, will retry in 60s")

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


class OKXPublicWsClient(OKXWsClient):
    """WebSocket client for OKX public market-data channels (no auth required).

    Reuses the parent's reconnect / circuit-breaker / message-loop logic by
    overriding ``_connect_and_login`` to skip the login handshake and use the
    public endpoint.  Supports the ``tickers``, ``candle*`` and ``books``
    channels.
    """

    def __init__(self, trade_mode: str = "live"):
        # Public channels need no credentials — pass empty strings to parent.
        super().__init__(
            api_key="",
            secret_key="",
            passphrase="",
            trade_mode=trade_mode,
        )
        self._ws_url = os.getenv(
            "OKX_WS_PUBLIC_URL",
            WS_PUBLIC_DEMO_URL if trade_mode == "demo" else WS_PUBLIC_LIVE_URL,
        )
        self._ticker_callbacks: list[callable] = []
        self._candle_callbacks: list[callable] = []
        self._books_callbacks: list[callable] = []
        # Track public subscriptions separately from the parent's private
        # ``_subscriptions`` (orders) so they are re-subscribed on reconnect.
        self._public_subscriptions: list[dict] = []

    # ------------------------------------------------------------------
    # Connection (override — no login for public channels)
    # ------------------------------------------------------------------

    async def _connect_and_login(self):
        """Connect to the public WebSocket endpoint without logging in."""
        logger.info(f"Connecting to OKX public WebSocket: {self._ws_url}")
        try:
            connect_kwargs = {"ping_interval": None}
            proxy = _get_proxy()
            if proxy:
                connect_kwargs["proxy"] = proxy
                logger.info(f"Using proxy for public WebSocket: {proxy}")
            self._ws = await websockets.connect(self._ws_url, **connect_kwargs)
            self._connected = True
            self._disconnected_at = None
            logger.info("Public WebSocket connected")

            # Re-subscribe to all public channels after (re)connect.
            for sub in self._public_subscriptions:
                await self._send_subscribe(sub)

            self._message_task = asyncio.create_task(self._message_loop())
        except Exception as e:
            logger.error(f"Public WebSocket connection failed: {e}")
            self._connected = False
            self._disconnected_at = time.time()

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_ticker_update(self, callback: callable):
        """Register a callback for ticker updates.

        Callback signature: callback(ticker_data: dict)
        ``ticker_data`` is the raw OKX ticker dict (includes ``instId``,
        ``last``, ``bidPx``, ``askPx`` etc.).
        """
        self._ticker_callbacks.append(callback)

    def on_candle_update(self, callback: callable):
        """Register a callback for candle updates.

        Callback signature: callback(inst_id: str, interval: str, candle: list)
        """
        self._candle_callbacks.append(callback)

    def on_books_update(self, callback: callable):
        """Register a callback for order-book updates.

        Callback signature: callback(inst_id: str, books: dict)
        """
        self._books_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Subscribe / unsubscribe
    # ------------------------------------------------------------------

    async def subscribe_ticker(self, symbols: list[str]):
        """Subscribe to the ``tickers`` channel for the given symbols."""
        for symbol in symbols:
            sub = {"channel": "tickers", "instId": symbol}
            if sub not in self._public_subscriptions:
                self._public_subscriptions.append(sub)
            if self._connected:
                await self._send_subscribe(sub)
                logger.info(f"Subscribed to tickers: {symbol}")

    async def subscribe_candle(self, symbols: list[str], interval: str = "1m"):
        """Subscribe to a candle channel for the given symbols.

        ``interval`` is a short label such as ``"1m"``, ``"5m"``, ``"1H"``;
        it is mapped to the OKX channel name (``candle1m`` etc.) via
        :data:`CANDLE_INTERVALS`.
        """
        channel = CANDLE_INTERVALS.get(interval, f"candle{interval}")
        for symbol in symbols:
            sub = {"channel": channel, "instId": symbol}
            if sub not in self._public_subscriptions:
                self._public_subscriptions.append(sub)
            if self._connected:
                await self._send_subscribe(sub)
                logger.info(f"Subscribed to {channel}: {symbol}")

    async def subscribe_books(self, symbols: list[str]):
        """Subscribe to the ``books`` channel for the given symbols."""
        for symbol in symbols:
            sub = {"channel": "books", "instId": symbol}
            if sub not in self._public_subscriptions:
                self._public_subscriptions.append(sub)
            if self._connected:
                await self._send_subscribe(sub)
                logger.info(f"Subscribed to books: {symbol}")

    async def unsubscribe_ticker(self, symbols: list[str]):
        """Unsubscribe from the ``tickers`` channel for the given symbols."""
        for symbol in symbols:
            sub = {"channel": "tickers", "instId": symbol}
            if sub in self._public_subscriptions:
                self._public_subscriptions.remove(sub)
            if self._connected:
                await self._send_unsubscribe(sub)
                logger.info(f"Unsubscribed from tickers: {symbol}")

    async def _send_subscribe(self, sub: dict):
        msg = {"op": "subscribe", "args": [sub]}
        await self._ws.send(json.dumps(msg))

    async def _send_unsubscribe(self, sub: dict):
        msg = {"op": "unsubscribe", "args": [sub]}
        await self._ws.send(json.dumps(msg))

    # ------------------------------------------------------------------
    # Data dispatch
    # ------------------------------------------------------------------

    async def _handle_data(self, msg: dict):
        arg = msg.get("arg", {})
        channel = arg.get("channel", "")
        data_list = msg.get("data", [])

        if channel == "tickers":
            for item in data_list:
                for cb in self._ticker_callbacks:
                    try:
                        cb(item)
                    except Exception as e:
                        logger.error(f"Ticker callback error: {e}")
        elif channel.startswith("candle"):
            inst_id = arg.get("instId", "")
            for candle in data_list:
                for cb in self._candle_callbacks:
                    try:
                        cb(inst_id, channel, candle)
                    except Exception as e:
                        logger.error(f"Candle callback error: {e}")
        elif channel in ("books", "books5", "bbo-tbt", "books-tbt"):
            inst_id = arg.get("instId", "")
            for item in data_list:
                for cb in self._books_callbacks:
                    try:
                        cb(inst_id, item)
                    except Exception as e:
                        logger.error(f"Books callback error: {e}")
        else:
            logger.debug(f"Unhandled public channel: {channel} {msg}")