import asyncio
from strategies.base_strategy import BaseStrategy


class TrendStrategy(BaseStrategy):
    async def validate_params(self) -> bool:
        required = ["fast_ma_period", "slow_ma_period", "order_qty", "symbol"]
        for key in required:
            if key not in self.params:
                return False
        if self.params["fast_ma_period"] >= self.params["slow_ma_period"]:
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

        self.record_order(symbol, side, "market", px, sz, order_id=order_info.ordId, status="filled")

    async def execute(self):
        if not await self.validate_params():
            self.update_status("error")
            return

        fast_period = self.params["fast_ma_period"]
        slow_period = self.params["slow_ma_period"]
        order_qty = self.params["order_qty"]
        symbol = self.params["symbol"]

        last_signal = None
        self.update_status("running")

        # Get initial equity once at start
        try:
            balances = await self.client.get_balance()
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
                    self.record_order(symbol, signal, "market", current_price, order_qty)
                    last_signal = signal

                # Calculate unrealized PnL from position
                current_price = closes[-1]
                if self._position != 0:
                    unrealized_pnl = (current_price - self._avg_entry_price) * self._position
                    # Deduct estimated close fee
                    estimated_close_fee = abs(self._position) * current_price * self._fee_rate
                    unrealized_pnl -= estimated_close_fee
                else:
                    unrealized_pnl = 0.0

                realized_pnl = self.get_realized_pnl()
                total_pnl = unrealized_pnl + realized_pnl

                # Get equity for recording (fallback to initial_equity + pnl)
                total_equity = self._initial_equity + total_pnl

                if self._should_record_pnl(total_pnl):
                    self.record_pnl(total_equity, unrealized_pnl, realized_pnl)
                    self._mark_pnl_recorded(total_pnl)

            except Exception:
                pass

            await asyncio.sleep(60)
