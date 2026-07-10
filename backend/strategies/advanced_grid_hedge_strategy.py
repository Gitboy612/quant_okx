import asyncio
from strategies.base_strategy import BaseStrategy


class AdvancedGridHedgeStrategy(BaseStrategy):
    async def validate_params(self) -> bool:
        required = ["y", "n", "order_qty", "grid_count", "safe_usdt", "symbol"]
        for key in required:
            if key not in self.params:
                return False
        if not (0 < self.params["y"] <= 100):
            return False
        if not (0 < self.params["n"] <= 100):
            return False
        if self.params["order_qty"] <= 0:
            return False
        if self.params["grid_count"] < 2:
            return False
        return True

    async def execute(self):
        if not await self.validate_params():
            self.update_status("error")
            return

        y_pct = self.params["y"] / 100
        n_pct = self.params["n"] / 100
        order_qty = self.params["order_qty"]
        grid_count = self.params["grid_count"]
        safe_usdt = self.params["safe_usdt"]
        symbol = self.params["symbol"]

        self.update_status("running")

        ref_price = None
        hedged = False

        while self._running:
            if self._paused:
                await asyncio.sleep(1)
                continue

            try:
                tickers = await self.client.get_ticker(symbol)
                if not tickers:
                    await asyncio.sleep(3)
                    continue

                current_price = float(tickers[0]["last"])

                if ref_price is None:
                    ref_price = current_price
                    await asyncio.sleep(10)
                    continue

                change_pct = (current_price - ref_price) / ref_price

                if change_pct >= y_pct and not hedged:
                    hedge_qty = order_qty * n_pct
                    await self.client.place_order(
                        inst_id=symbol,
                        side="sell",
                        ord_type="market",
                        sz=str(round(hedge_qty, 6)),
                    )
                    hedged = True
                    self.record_order(
                        symbol, "sell", "market", current_price, round(hedge_qty, 6),
                        status="hedge_open",
                    )
                    ref_price = current_price

                elif change_pct <= -y_pct and hedged:
                    await self.client.place_order(
                        inst_id=symbol,
                        side="buy",
                        ord_type="market",
                        sz=str(round(order_qty * n_pct, 6)),
                    )
                    hedged = False
                    self.record_order(
                        symbol, "buy", "market", current_price, round(order_qty * n_pct, 6),
                        status="hedge_close",
                    )
                    ref_price = current_price

                    positions = await self.client.get_positions()
                    if positions:
                        for pos in positions:
                            if pos.get("instId") == symbol:
                                margin_ratio = float(pos.get("mgnRatio", "1"))
                                if margin_ratio > 0.8:
                                    rescue_qty = safe_usdt / current_price
                                    await self.client.place_order(
                                        inst_id=symbol,
                                        side="buy",
                                        ord_type="market",
                                        sz=str(round(rescue_qty, 6)),
                                    )
                                    self.record_order(
                                        symbol, "buy", "market", current_price, round(rescue_qty, 6),
                                        status="emergency_margin",
                                    )
                                    break

                balances = await self.client.get_balance()
                if balances:
                    total_equity = float(balances.get("totalEq", "0"))
                    if self._initial_equity == 0.0:
                        self._initial_equity = total_equity
                    strategy_pnl = total_equity - self._initial_equity
                    if self._should_record_pnl(strategy_pnl):
                        self.record_pnl(total_equity, 0, strategy_pnl)
                        self._mark_pnl_recorded(strategy_pnl)

            except Exception:
                pass

            await asyncio.sleep(5)
