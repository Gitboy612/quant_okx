import asyncio
from strategies.base_strategy import BaseStrategy


class ArbitrageStrategy(BaseStrategy):
    async def validate_params(self) -> bool:
        required = ["spot_symbol", "futures_symbol", "spread_threshold", "order_qty"]
        for key in required:
            if key not in self.params:
                return False
        if self.params["spread_threshold"] <= 0:
            return False
        if self.params["order_qty"] <= 0:
            return False
        return True

    async def execute(self):
        if not await self.validate_params():
            self.update_status("error")
            return

        spot_symbol = self.params["spot_symbol"]
        futures_symbol = self.params["futures_symbol"]
        spread_threshold = self.params["spread_threshold"]
        order_qty = self.params["order_qty"]

        position_open = False
        self.update_status("running")

        while self._running:
            if self._paused:
                await asyncio.sleep(1)
                continue

            try:
                spot_ticker = await self.client.get_ticker(spot_symbol)
                futures_ticker = await self.client.get_ticker(futures_symbol)

                if not spot_ticker or not futures_ticker:
                    await asyncio.sleep(3)
                    continue

                spot_price = float(spot_ticker[0]["last"])
                futures_price = float(futures_ticker[0]["last"])
                spread_pct = (futures_price - spot_price) / spot_price * 100

                if not position_open and abs(spread_pct) > spread_threshold:
                    if spread_pct > 0:
                        await self.client.place_order(inst_id=futures_symbol, side="sell", ord_type="market", sz=str(order_qty))
                        await self.client.place_order(inst_id=spot_symbol, side="buy", ord_type="market", sz=str(order_qty))
                        await self.record_order(futures_symbol, "sell", "market", futures_price, order_qty)
                        await self.record_order(spot_symbol, "buy", "market", spot_price, order_qty)
                    else:
                        await self.client.place_order(inst_id=futures_symbol, side="buy", ord_type="market", sz=str(order_qty))
                        await self.client.place_order(inst_id=spot_symbol, side="sell", ord_type="market", sz=str(order_qty))
                        await self.record_order(futures_symbol, "buy", "market", futures_price, order_qty)
                        await self.record_order(spot_symbol, "sell", "market", spot_price, order_qty)
                    position_open = True

                elif position_open and abs(spread_pct) < spread_threshold * 0.3:
                    await self.client.place_order(inst_id=futures_symbol, side="buy" if spread_pct > 0 else "sell", ord_type="market", sz=str(order_qty))
                    await self.client.place_order(inst_id=spot_symbol, side="sell" if spread_pct > 0 else "buy", ord_type="market", sz=str(order_qty))
                    await self.record_order(futures_symbol, "buy", "market", futures_price, order_qty, status="close")
                    await self.record_order(spot_symbol, "sell", "market", spot_price, order_qty, status="close")
                    position_open = False

                balances = await self.client.get_balance()
                if balances:
                    total_equity = float(balances.get("totalEq", "0"))

            except Exception:
                pass

            await asyncio.sleep(5)
