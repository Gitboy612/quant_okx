import asyncio
from strategies.base_strategy import BaseStrategy
from services.market_data_service import market_data_service


class TrendStrategy(BaseStrategy):
    async def validate_params(self) -> bool:
        # Bug 8: 统一为 fast_period / slow_period，兼容旧参数名 fast_ma_period / slow_ma_period
        fast_period = self.params.get("fast_period", self.params.get("fast_ma_period"))
        slow_period = self.params.get("slow_period", self.params.get("slow_ma_period"))
        if fast_period is None or slow_period is None:
            return False
        if "order_qty" not in self.params or "symbol" not in self.params:
            return False
        if fast_period >= slow_period:
            return False
        if self.params["order_qty"] <= 0:
            return False
        return True

    async def _on_order_filled(self, order_info):
        """Handle order fill event for position tracking."""
        symbol = order_info.symbol
        side = order_info.side
        px = float(order_info.px) if order_info.px else 0
        sz = float(order_info.sz) if order_info.sz else 0

        if side == "buy":
            if self._position < 0:
                # Closing short position → realized PnL
                close_qty = min(sz, abs(self._position))
                realized = (self._avg_entry_price - px) * close_qty
                self.add_realized_pnl(realized)
                remaining = sz - close_qty
                if remaining > 0:
                    self._position = remaining
                    self._avg_entry_price = px
                else:
                    self._position += sz
                    if self._position >= 0:
                        self._avg_entry_price = px
            else:
                # Opening/adding to long position
                new_total = self._position + sz
                self._avg_entry_price = (self._avg_entry_price * self._position + px * sz) / new_total if new_total > 0 else px
                self._position = new_total
        elif side == "sell":
            if self._position > 0:
                # Closing long position → realized PnL
                close_qty = min(sz, self._position)
                realized = (px - self._avg_entry_price) * close_qty
                self.add_realized_pnl(realized)
                remaining = sz - close_qty
                if remaining > 0:
                    self._position = -remaining
                    self._avg_entry_price = px
                else:
                    self._position -= sz
                    if self._position <= 0:
                        self._avg_entry_price = px
            else:
                # Opening/adding to short position
                new_total = abs(self._position) + sz
                self._avg_entry_price = (self._avg_entry_price * abs(self._position) + px * sz) / new_total if new_total > 0 else px
                self._position = -new_total

        await self.record_order(symbol, side, "market", px, sz, order_id=order_info.ordId, status="filled")

    def _on_ticker_update(self, ticker_data: dict):
        """WebSocket ticker callback — update cached latest price."""
        try:
            last = ticker_data.get("last")
            if last:
                self._latest_price = float(last)
        except Exception as e:
            print(f"[TrendStrategy] _on_ticker_update error: {e}")

    async def execute(self):
        if not await self.validate_params():
            self.update_status("error")
            return

        # Bug 8: 统一读取 fast_period / slow_period，兼容旧参数名 fast_ma_period / slow_ma_period
        fast_period = self.params.get("fast_period", self.params["fast_ma_period"])
        slow_period = self.params.get("slow_period", self.params["slow_ma_period"])
        order_qty = self.params["order_qty"]
        symbol = self.params["symbol"]

        last_signal = None
        consecutive_errors = 0
        self.update_status("running")

        # Subscribe to WebSocket ticker for real-time price updates.
        self._latest_price = 0.0
        try:
            await market_data_service.subscribe_ticker(symbol, self._on_ticker_update)
        except Exception as e:
            print(f"[TrendStrategy] WS ticker subscribe failed, using REST fallback: {e}")

        # Get initial equity once at start (use shared cache to reduce API calls)
        try:
            from services.strategy_engine import strategy_engine
            balances = await strategy_engine.get_shared_balance(self.account_id)
            if balances:
                self._initial_equity = float(balances.get("totalEq", "0"))
        except Exception:
            self._initial_equity = 0.0

        # Register order fill callback for position tracking
        self.order_manager.on("filled", self._on_order_filled)
        self._position = 0.0  # net position
        self._avg_entry_price = 0.0  # average entry price

        # Restore realized PnL from latest DB record
        try:
            from models.pnl import PnlRecord
            db = self.db_session_factory()
            try:
                latest_pnl = db.query(PnlRecord).filter(
                    PnlRecord.strategy_instance_id == self.instance_id
                ).order_by(PnlRecord.recorded_at.desc()).first()
                if latest_pnl:
                    self.restore_realized_pnl(latest_pnl.realized_pnl or 0)
            finally:
                db.close()
        except Exception:
            pass

        while self._running:
            if self._paused:
                await asyncio.sleep(1)
                continue

            try:
                candles = await self.client.get_candles(symbol, bar="5m", limit=str(slow_period + 10))
                if not candles or len(candles) < slow_period:
                    await asyncio.sleep(5)
                    continue

                closes = [float(c[4]) for c in reversed(candles)]

                fast_ma = sum(closes[-fast_period:]) / fast_period
                slow_ma = sum(closes[-slow_period:]) / slow_period
                prev_fast_ma = sum(closes[-fast_period - 1:-1]) / fast_period
                prev_slow_ma = sum(closes[-slow_period - 1:-1]) / slow_period

                signal = None
                if prev_fast_ma <= prev_slow_ma and fast_ma > slow_ma:
                    signal = "buy"
                elif prev_fast_ma >= prev_slow_ma and fast_ma < slow_ma:
                    signal = "sell"

                if signal and signal != last_signal:
                    await self.client.place_order(
                        inst_id=symbol,
                        side=signal,
                        ord_type="market",
                        sz=str(order_qty),
                    )
                    current_price = closes[-1]
                    await self.record_order(symbol, signal, "market", current_price, order_qty)
                    last_signal = signal

                consecutive_errors = 0

            except Exception as e:
                # Bug 2: 替换静默 pass，记录错误日志 + 指数退避（参考 grid_strategy 实现）
                consecutive_errors += 1
                error_msg = str(e)
                is_network_error = any(kw in error_msg.lower() for kw in [
                    "winerror 64", "winerror 10054", "winerror 10060", "winerror 10061",
                    "timed out", "connection refused", "ssl", "eof", "network", "connect",
                    "timeout", "unreachable"
                ])

                if is_network_error:
                    backoff = min(2 ** consecutive_errors, 60)
                    print(f"[TrendStrategy] Network error #{consecutive_errors}, backing off {backoff}s: {e}")
                    self._record_event("error", f"网络异常 (第{consecutive_errors}次)，退避 {backoff}s: {error_msg[:200]}")

                    if consecutive_errors >= 10:
                        print(f"[TrendStrategy] Too many network errors ({consecutive_errors}), stopping strategy")
                        self._record_event("error", f"连续网络异常 {consecutive_errors} 次，自动停止策略")
                        self.record_final_pnl()
                        self.update_status("stopped")
                        self._running = False
                        break

                    await asyncio.sleep(backoff)
                    continue
                else:
                    backoff = min(3 * consecutive_errors, 30)
                    print(f"[TrendStrategy] Non-network error #{consecutive_errors}, backing off {backoff}s: {e}")
                    self._record_event("error", f"策略异常 (第{consecutive_errors}次)，退避 {backoff}s: {error_msg[:200]}")

                    if consecutive_errors >= 20:
                        print(f"[TrendStrategy] Too many non-network errors ({consecutive_errors}), stopping strategy")
                        self._record_event("error", f"连续策略异常 {consecutive_errors} 次，自动停止策略: {error_msg[:200]}")
                        self.record_final_pnl()
                        self.update_status("stopped")
                        self._running = False
                        break

                    await asyncio.sleep(backoff)
                    continue

            await asyncio.sleep(60)

        # Unsubscribe from WebSocket ticker on exit.
        try:
            await market_data_service.unsubscribe_ticker(symbol, self._on_ticker_update)
        except Exception:
            pass
