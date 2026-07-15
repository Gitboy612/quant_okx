"""Market-data subscription manager (singleton).

Wraps :class:`OKXPublicWsClient` and provides reference-counted ticker
subscriptions so that multiple strategies subscribing to the same symbol
share a single underlying WebSocket channel.
"""
import asyncio
import logging
import time
from collections import deque

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
        # SubTask 8.1: per-symbol 价格历史环形缓冲，用于短时波动率计算
        self._price_history: dict[str, deque] = {}
        # 波动率计算默认窗口（秒）
        self._volatility_window: float = 5.0
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
        # SubTask 8.1: 追加最新价到价格历史缓冲，用于波动率计算
        last = ticker_data.get("last")
        if last:
            try:
                self._update_price_history(inst_id, float(last))
            except (TypeError, ValueError):
                pass
        for cb in self._ticker_callbacks.get(inst_id, []):
            try:
                cb(ticker_data)
            except Exception as e:
                logger.error(f"Ticker callback error for {inst_id}: {e}")

    # ------------------------------------------------------------------
    # Volatility (SubTask 8.1)
    # ------------------------------------------------------------------

    def _update_price_history(self, symbol: str, price: float):
        """追加价格到环形缓冲，自动淘汰超过默认窗口的旧数据。"""
        buf = self._price_history.get(symbol)
        if buf is None:
            buf = deque()
            self._price_history[symbol] = buf
        now = time.time()
        buf.append((now, price))
        cutoff = now - self._volatility_window
        while buf and buf[0][0] < cutoff:
            buf.popleft()

    def update_price(self, symbol: str, price: float):
        """供外部调用的价格更新接口（SubTask 8.1）。

        若策略通过 REST 轮询获得价格，可调用本方法补充到历史缓冲，
        与 WebSocket 数据合并用于波动率计算。
        """
        self._update_price_history(symbol, price)

    def get_volatility(self, symbol: str, window_seconds: float = 5.0) -> float:
        """计算指定 symbol 在窗口内的短时波动率（SubTask 8.1）。

        波动率公式：(max - min) / mean
        窗口内价格序列极差除以均值，反映价格振幅相对均值的比例。
        数据不足（少于 2 个点）或均值为 0 时返回 0.0。
        返回值是小数（0.01 = 1%）。
        """
        buf = self._price_history.get(symbol)
        if not buf:
            return 0.0
        now = time.time()
        cutoff = now - window_seconds
        prices = [p for ts, p in buf if ts >= cutoff]
        if len(prices) < 2:
            return 0.0
        pmin = min(prices)
        pmax = max(prices)
        mean = sum(prices) / len(prices)
        if mean <= 0:
            return 0.0
        return (pmax - pmin) / mean

    def get_latest_volatility(self, symbol: str) -> float:
        """便捷接口：用默认窗口计算最新波动率。"""
        return self.get_volatility(symbol, self._volatility_window)

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
                    self._price_history.pop(symbol, None)  # SubTask 8.1: 清理价格历史
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
        self._price_history.clear()


market_data_service = MarketDataService()
