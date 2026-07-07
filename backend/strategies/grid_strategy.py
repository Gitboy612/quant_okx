import asyncio
import math
from strategies.base_strategy import BaseStrategy


class GridStrategy(BaseStrategy):
    async def validate_params(self) -> bool:
        required = ["upper_price", "lower_price", "grid_count", "order_qty", "symbol"]
        for key in required:
            if key not in self.params:
                return False
        if self.params["upper_price"] <= self.params["lower_price"]:
            return False
        if self.params["grid_count"] < 2:
            return False
        if self.params["order_qty"] <= 0:
            return False
        return True

    async def execute(self):
        if not await self.validate_params():
            self.update_status("error")
            return

        upper = self.params["upper_price"]
        lower = self.params["lower_price"]
        grid_count = self.params["grid_count"]
        order_qty = self.params["order_qty"]
        symbol = self.params["symbol"]

        step = (upper - lower) / (grid_count - 1)
        grid_levels = [lower + i * step for i in range(grid_count)]

        ticker = self.client.get_ticker(symbol)
        if not ticker:
            self.update_status("error")
            return
        current_price = float(ticker[0]["last"])

        self.update_status("running")

        tick_size = 0.1 if "-SWAP" in symbol else 0.01
        tick_decimals = 1 if "-SWAP" in symbol else 2

        active_buy_orders: dict[int, str] = {}
        active_sell_orders: dict[int, str] = {}

        for i, level in enumerate(grid_levels):
            price = round(round(level / tick_size) * tick_size, tick_decimals)
            price_str = f"{price:.{tick_decimals}f}"
            if level < current_price:
                resp = self.client.place_order(
                    inst_id=symbol,
                    side="buy",
                    ord_type="limit",
                    sz=str(order_qty),
                    px=price_str,
                )
                if resp.get("code") == "0":
                    ord_data = resp.get("data", [{}])[0]
                    order_id = ord_data.get("ordId", "")
                    active_buy_orders[i] = order_id
                    self.record_order(symbol, "buy", "limit", level, order_qty, order_id=order_id, status="live")
            elif level > current_price:
                resp = self.client.place_order(
                    inst_id=symbol,
                    side="sell",
                    ord_type="limit",
                    sz=str(order_qty),
                    px=price_str,
                )
                if resp.get("code") == "0":
                    ord_data = resp.get("data", [{}])[0]
                    order_id = ord_data.get("ordId", "")
                    active_sell_orders[i] = order_id
                    self.record_order(symbol, "sell", "limit", level, order_qty, order_id=order_id, status="live")

        last_check_price = current_price

        while self._running:
            if self._paused:
                await asyncio.sleep(1)
                continue

            try:
                tickers = self.client.get_ticker(symbol)
                if not tickers:
                    await asyncio.sleep(5)
                    continue

                current_price = float(tickers[0]["last"])

                filled_buy_indices = []
                for i, order_id in list(active_buy_orders.items()):
                    order_info = self.client.get_order(symbol, order_id)
                    if order_info and order_info[0].get("state") == "filled":
                        filled_buy_indices.append(i)
                        self.record_order(symbol, "buy", "limit", grid_levels[i], order_qty, order_id=order_id, status="filled")
                        grd_price = str(round(grid_levels[i], 4))
                        sell_resp = self.client.place_order(
                            inst_id=symbol, side="sell", ord_type="limit",
                            sz=str(order_qty), px=str(round(grid_levels[i] + step, 4)),
                        )
                        if sell_resp.get("code") == "0":
                            sell_ord_id = sell_resp.get("data", [{}])[0].get("ordId", "")
                            active_sell_orders[i + 1] = sell_ord_id
                            self.record_order(symbol, "sell", "limit", grid_levels[i] + step,
                                              order_qty, order_id=sell_ord_id, status="live")

                for i in filled_buy_indices:
                    if i in active_buy_orders:
                        del active_buy_orders[i]

                filled_sell_indices = []
                for i, order_id in list(active_sell_orders.items()):
                    order_info = self.client.get_order(symbol, order_id)
                    if order_info and order_info[0].get("state") == "filled":
                        filled_sell_indices.append(i)
                        self.record_order(symbol, "sell", "limit", grid_levels[i], order_qty, order_id=order_id, status="filled")
                        grd_price = str(round(grid_levels[i], 4))
                        buy_resp = self.client.place_order(
                            inst_id=symbol, side="buy", ord_type="limit",
                            sz=str(order_qty), px=str(round(grid_levels[i] - step, 4)),
                        )
                        if buy_resp.get("code") == "0":
                            buy_ord_id = buy_resp.get("data", [{}])[0].get("ordId", "")
                            active_buy_orders[i - 1] = buy_ord_id
                            self.record_order(symbol, "buy", "limit", grid_levels[i] - step,
                                              order_qty, order_id=buy_ord_id, status="live")

                for i in filled_sell_indices:
                    if i in active_sell_orders:
                        del active_sell_orders[i]

                balances = self.client.get_balance()
                if balances:
                    total_equity = 0.0
                    try:
                        total_equity = float(balances.get("totalEq", "0"))
                    except Exception:
                        pass
                    self.record_pnl(total_equity, 0, 0)

            except Exception:
                pass

            await asyncio.sleep(3)

        for _, order_id in {**active_buy_orders, **active_sell_orders}.items():
            try:
                self.client.cancel_order(symbol, order_id)
            except Exception:
                pass
