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

        while self._running:
            if self._paused:
                await asyncio.sleep(1)
                continue

            try:
                candles = self.client.get_candles(symbol, bar="5m", limit=str(slow_period + 10))
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
                    self.client.place_order(
                        inst_id=symbol,
                        side=signal,
                        ord_type="market",
                        sz=str(order_qty),
                    )
                    current_price = closes[-1]
                    self.record_order(symbol, signal, "market", current_price, order_qty)
                    last_signal = signal

                balances = self.client.get_balance()
                if balances:
                    total_equity = float(balances.get("totalEq", "0"))
                    self.record_pnl(total_equity, 0, 0)

            except Exception:
                pass

            await asyncio.sleep(60)
