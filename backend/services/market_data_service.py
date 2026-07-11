"""Market-data subscription manager (singleton).

Wraps :class:`OKXPublicWsClient` and provides reference-counted ticker
subscriptions so that multiple strategies subscribing to the same symbol
share a single underlying WebSocket channel.
"""
import asyncio
import logging

from services.okx_ws_client import OKXPublicWsClient

logger = logging.getLogger(__name__)


class MarketDataService:
    """Singleton managing public market-data WebSocket subscriptions.

    * Reference counting: when N strategies subscribe to the same symbol only
      one WebSocket ``subscribe`` is sent; the channel is unsubscribed only
      when the last subscriber leaves.
    * Per-symbol callback dispatch: each subscriber registers its own
      callback; incoming ticker data is fanned out to all callbacks for
      that symbol.
    * Ticker cache: the latest ticker dict per symbol is stored in memory
      for quick lookup via :meth:`get_latest_ticker`.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._ws_client: OKXPublicWsClient | None = None
        self._ticker_subscribers: dict[str, int] = {}          # symbol → count
        self._ticker_callbacks: dict[str, list[callable]] = {}  # symbol → callbacks
        self._ticker_cache: dict[str, dict] = {}                # symbol → latest ticker
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_client(self):
        """Lazily create and connect the public WebSocket client."""
        if self._ws_client is None:
            self._ws_client = OKXPublicWsClient(trade_mode="live")
            self._ws_client.on_ticker_update(self._on_ticker_data)
            await self._ws_client.connect()

    def _on_ticker_data(self, ticker_data: dict):
        """Global ticker callback — cache and fan out to per-symbol subscribers."""
        inst_id = ticker_data.get("instId", "")
        if not inst_id:
            return
        self._ticker_cache[inst_id] = ticker_data
        for cb in self._ticker_callbacks.get(inst_id, []):
            try:
                cb(ticker_data)
            except Exception as e:
                logger.error(f"Ticker callback error for {inst_id}: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def subscribe_ticker(self, symbol: str, callback: callable):
        """Subscribe to ticker updates for *symbol*.

        Registers *callback* to be invoked on every ticker update.  If this is
        the first subscriber for *symbol* the underlying WebSocket channel is
        subscribed; subsequent subscribers reuse the existing channel.
        """
        async with self._lock:
            await self._ensure_client()
            self._ticker_callbacks.setdefault(symbol, [])
            if callback not in self._ticker_callbacks[symbol]:
                self._ticker_callbacks[symbol].append(callback)
            count = self._ticker_subscribers.get(symbol, 0)
            if count == 0 and self._ws_client is not None:
                await self._ws_client.subscribe_ticker([symbol])
            self._ticker_subscribers[symbol] = count + 1

    async def unsubscribe_ticker(self, symbol: str, callback: callable):
        """Unsubscribe *callback* from ticker updates for *symbol*.

        Decrements the reference count only when *callback* was actually
        registered; when the count reaches zero the underlying WebSocket
        channel is unsubscribed and cached data is cleared.
        """
        async with self._lock:
            callbacks = self._ticker_callbacks.get(symbol, [])
            if callback not in callbacks:
                # Callback was never registered for this symbol — no-op.
                return
            callbacks.remove(callback)
            count = self._ticker_subscribers.get(symbol, 0)
            if count > 0:
                count -= 1
                if count == 0:
                    self._ticker_subscribers.pop(symbol, None)
                    self._ticker_callbacks.pop(symbol, None)
                    self._ticker_cache.pop(symbol, None)
                    if self._ws_client is not None:
                        await self._ws_client.unsubscribe_ticker([symbol])
                else:
                    self._ticker_subscribers[symbol] = count

    def get_latest_ticker(self, symbol: str) -> dict | None:
        """Return the latest cached ticker dict for *symbol*, or ``None``."""
        return self._ticker_cache.get(symbol)

    @property
    def is_connected(self) -> bool:
        """True if the underlying public WebSocket client is connected."""
        return self._ws_client is not None and self._ws_client.is_connected

    async def aclose(self):
        """Disconnect the public WebSocket client and clear all state."""
        if self._ws_client is not None:
            await self._ws_client.disconnect()
            self._ws_client = None
        self._ticker_subscribers.clear()
        self._ticker_callbacks.clear()
        self._ticker_cache.clear()


market_data_service = MarketDataService()
