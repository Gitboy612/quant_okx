import asyncio
import math
import time
import traceback
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

    async def _on_order_filled(self, order_info):
        """Handle order fill event from OrderManager (WebSocket or REST fallback)."""
        symbol = order_info.symbol
        side = order_info.side
        px = float(order_info.px) if order_info.px else 0
        sz = float(order_info.sz) if order_info.sz else 0
        ordId = order_info.ordId

        # Find grid index by matching price
        grid_idx = None
        for i, level in enumerate(self._grid_levels):
            price = round(round(level / self._grid_tick_size) * self._grid_tick_size, self._grid_tick_decimals)
            if abs(price - px) < self._grid_tick_size * 0.6:
                grid_idx = i
                break

        if grid_idx is None:
            return

        if side == "buy":
            if grid_idx in self._active_buy_orders:
                del self._active_buy_orders[grid_idx]
            self.record_order(symbol, "buy", "limit", px, sz, order_id=ordId, status="filled")

            sell_price = round(round((self._grid_levels[grid_idx] + self._grid_step) / self._grid_tick_size) * self._grid_tick_size, self._grid_tick_decimals)
            sell_price_str = f"{sell_price:.{self._grid_tick_decimals}f}"
            sell_resp = await self.client.place_order(
                inst_id=symbol, side="sell", ord_type="limit",
                sz=str(self._grid_order_qty), px=sell_price_str,
            )
            if sell_resp.get("code") == "0":
                sell_ord_id = sell_resp.get("data", [{}])[0].get("ordId", "")
                self._active_sell_orders[grid_idx + 1] = sell_ord_id
                self.record_order(symbol, "sell", "limit", sell_price,
                                  self._grid_order_qty, order_id=sell_ord_id, status="live")

        elif side == "sell":
            if grid_idx in self._active_sell_orders:
                del self._active_sell_orders[grid_idx]

            buy_px_for_pnl = self._grid_levels[grid_idx - 1] if grid_idx > 0 else self._grid_levels[grid_idx] - self._grid_step
            cycle_pnl = (px - buy_px_for_pnl) * sz
            self.add_realized_pnl(cycle_pnl)
            self.record_order(symbol, "sell", "limit", px, sz, order_id=ordId, status="filled")

            buy_price = round(round((self._grid_levels[grid_idx] - self._grid_step) / self._grid_tick_size) * self._grid_tick_size, self._grid_tick_decimals)
            buy_price_str = f"{buy_price:.{self._grid_tick_decimals}f}"
            buy_resp = await self.client.place_order(
                inst_id=symbol, side="buy", ord_type="limit",
                sz=str(self._grid_order_qty), px=buy_price_str,
            )
            if buy_resp.get("code") == "0":
                buy_ord_id = buy_resp.get("data", [{}])[0].get("ordId", "")
                self._active_buy_orders[grid_idx - 1] = buy_ord_id
                self.record_order(symbol, "buy", "limit", buy_price,
                                  self._grid_order_qty, order_id=buy_ord_id, status="live")

    def _rebuild_active_dicts(self, symbol: str):
        """Rebuild active_buy_orders and active_sell_orders from OrderManager."""
        new_buy: dict[int, str] = {}
        new_sell: dict[int, str] = {}
        for order in self.order_manager.get_active_orders():
            if order.symbol != symbol:
                continue
            px_val = float(order.px) if order.px else 0
            for i, level in enumerate(self._grid_levels):
                price = round(round(level / self._grid_tick_size) * self._grid_tick_size, self._grid_tick_decimals)
                if abs(price - px_val) < self._grid_tick_size * 0.6:
                    if order.side == "buy":
                        new_buy[i] = order.ordId
                    elif order.side == "sell":
                        new_sell[i] = order.ordId
                    break
        self._active_buy_orders = new_buy
        self._active_sell_orders = new_sell

    async def execute(self):
        try:
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

            ticker = await self.client.get_ticker(symbol)
            if not ticker:
                self.update_status("error")
                return
            current_price = float(ticker[0]["last"])

            self.update_status("running")

            # Get initial equity once at start
            try:
                balances = await self.client.get_balance()
                if balances:
                    self._initial_equity = float(balances.get("totalEq", "0"))
            except Exception:
                self._initial_equity = 0.0

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
                        self._initial_equity = latest_pnl.equity - (latest_pnl.realized_pnl or 0) - (latest_pnl.unrealized_pnl or 0)
                finally:
                    db.close()
            except Exception:
                pass

            tick_size = 0.1 if "-SWAP" in symbol else 0.01
            tick_decimals = 1 if "-SWAP" in symbol else 2

            # Store grid data as instance variables for callback access
            self._grid_levels = grid_levels
            self._grid_step = step
            self._grid_tick_size = tick_size
            self._grid_tick_decimals = tick_decimals
            self._grid_order_qty = order_qty
            self._grid_symbol = symbol
            self._active_buy_orders: dict[int, str] = {}
            self._active_sell_orders: dict[int, str] = {}

            # Register order fill callback
            self.order_manager.on("filled", self._on_order_filled)

            # Sync existing orders from DB on restart
            synced = await self.sync_orders(symbol)
            # Rebuild active orders from synced DB orders
            try:
                from models.order import Order
                db = self.db_session_factory()
                try:
                    live_orders = db.query(Order).filter(
                        Order.strategy_instance_id == self.instance_id,
                        Order.status == "live"
                    ).all()
                    for o in live_orders:
                        if not o.order_id:
                            continue
                        for i, level in enumerate(grid_levels):
                            price = round(round(level / tick_size) * tick_size, tick_decimals)
                            if abs(price - (o.price or 0)) < tick_size * 0.6:
                                if o.side == "buy":
                                    self._active_buy_orders[i] = o.order_id
                                elif o.side == "sell":
                                    self._active_sell_orders[i] = o.order_id
                                break
                finally:
                    db.close()
            except Exception:
                pass

            # Only place new orders for grid levels that don't have active orders
            buy_orders = []
            sell_orders = []
            for i, level in enumerate(grid_levels):
                price = round(round(level / tick_size) * tick_size, tick_decimals)
                price_str = f"{price:.{tick_decimals}f}"
                if level < current_price:
                    buy_orders.append({"idx": i, "level": level, "px": price_str})
                elif level > current_price:
                    sell_orders.append({"idx": i, "level": level, "px": price_str})

            BATCH_SIZE = 20
            for batch_start in range(0, len(buy_orders), BATCH_SIZE):
                batch = buy_orders[batch_start:batch_start + BATCH_SIZE]
                order_payloads = [
                    {"instId": symbol, "side": "buy", "ordType": "limit", "sz": str(order_qty), "px": o["px"]}
                    for o in batch
                ]
                resp = await self.client.batch_place_orders(order_payloads)
                if resp.get("code") == "0":
                    for j, o in enumerate(batch):
                        try:
                            data = resp.get("data", [])
                            if j < len(data) and data[j].get("sCode") == "0":
                                order_id = data[j].get("ordId", "")
                                self._active_buy_orders[o["idx"]] = order_id
                                self.record_order(symbol, "buy", "limit", o["level"], order_qty, order_id=order_id, status="live")
                            else:
                                s_code = data[j].get("sCode", "") if j < len(data) else ""
                                s_msg = data[j].get("sMsg", "") if j < len(data) else ""
                                self._record_event("order_failed",
                                                   f"批量买单失败: idx={o['idx']} px={o['px']} sCode={s_code} {s_msg}",
                                                   {"idx": o["idx"], "px": o["px"], "sCode": s_code, "sMsg": s_msg})
                        except Exception as e:
                            print(f"[GridStrategy] record buy order error: {e}")
                else:
                    self._record_event("order_failed",
                                       f"批量买单请求失败: code={resp.get('code')} msg={resp.get('msg', '')}",
                                       {"code": resp.get("code"), "msg": resp.get("msg", "")})
                await asyncio.sleep(0.15)

            for batch_start in range(0, len(sell_orders), BATCH_SIZE):
                batch = sell_orders[batch_start:batch_start + BATCH_SIZE]
                order_payloads = [
                    {"instId": symbol, "side": "sell", "ordType": "limit", "sz": str(order_qty), "px": o["px"]}
                    for o in batch
                ]
                resp = await self.client.batch_place_orders(order_payloads)
                if resp.get("code") == "0":
                    for j, o in enumerate(batch):
                        try:
                            data = resp.get("data", [])
                            if j < len(data) and data[j].get("sCode") == "0":
                                order_id = data[j].get("ordId", "")
                                self._active_sell_orders[o["idx"]] = order_id
                                self.record_order(symbol, "sell", "limit", o["level"], order_qty, order_id=order_id, status="live")
                            else:
                                s_code = data[j].get("sCode", "") if j < len(data) else ""
                                s_msg = data[j].get("sMsg", "") if j < len(data) else ""
                                self._record_event("order_failed",
                                                   f"批量卖单失败: idx={o['idx']} px={o['px']} sCode={s_code} {s_msg}",
                                                   {"idx": o["idx"], "px": o["px"], "sCode": s_code, "sMsg": s_msg})
                        except Exception as e:
                            print(f"[GridStrategy] record sell order error: {e}")
                else:
                    self._record_event("order_failed",
                                       f"批量卖单请求失败: code={resp.get('code')} msg={resp.get('msg', '')}",
                                       {"code": resp.get("code"), "msg": resp.get("msg", "")})
                await asyncio.sleep(0.15)
        except Exception as e:
            print(f"[GridStrategy] execute error: {e}\n{traceback.format_exc()}")
            self._record_event("error", f"策略执行异常: {e}", {"traceback": traceback.format_exc()})
            self.update_status("error")
            return

        last_rest_check = 0.0

        while self._running:
            if self._paused:
                await asyncio.sleep(1)
                continue

            try:
                tickers = await self.client.get_ticker(symbol)
                if not tickers:
                    await asyncio.sleep(5)
                    continue

                current_price = float(tickers[0]["last"])

                # Fallback REST polling every 15 seconds (if WebSocket is not available)
                now = time.time()
                if now - last_rest_check > 15:
                    last_rest_check = now
                    for order in self.order_manager.get_active_orders():
                        if order.symbol != symbol:
                            continue
                        try:
                            info = await self.client.get_order(symbol, order.ordId)
                            if info and len(info) > 0:
                                state = info[0].get("state", "")
                                if state != order.state:
                                    self.order_manager.update_order(
                                        order.ordId,
                                        state=state,
                                        fillPx=info[0].get("fillPx", ""),
                                        fillSz=info[0].get("fillSz", ""),
                                        fee=info[0].get("fee", ""),
                                    )
                        except Exception:
                            pass

                # Rebuild active_buy_orders and active_sell_orders from OrderManager
                self._rebuild_active_dicts(symbol)

                # Calculate unrealized PnL from active buy orders
                unrealized_pnl = 0.0
                for idx in self._active_buy_orders:
                    buy_price = self._grid_levels[idx]
                    unrealized_pnl += (current_price - buy_price) * self._grid_order_qty

                realized_pnl = self.get_realized_pnl()
                total_equity = self._initial_equity + realized_pnl + unrealized_pnl
                self.record_pnl(total_equity, unrealized_pnl, realized_pnl)

            except Exception:
                pass

            await asyncio.sleep(3)

        for _, order_id in {**self._active_buy_orders, **self._active_sell_orders}.items():
            try:
                await self.client.cancel_order(symbol, order_id)
            except Exception:
                pass