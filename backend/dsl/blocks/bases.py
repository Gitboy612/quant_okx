"""基础策略类积木：可钩子调用的 Block 实现。

由 ComposableStrategy 实例化并编排，不继承 BaseStrategy，
避免与原有 execute() 主循环冲突。通过 @base_strategy 装饰器
注册到 base_strategy_registry，前端可通过 kind="grid" 引用。
"""
import asyncio

from dsl.registry import base_strategy
from dsl.context import ExecutionContext


@base_strategy("grid")
class GridBlock:
    """网格基础策略的可拼接 Block（钩子式）。

    由 ComposableStrategy 实例化并编排：on_start 放初始网格，
    on_tick 监控（网格策略的 on_tick 主要用于 PnL 记录，挂单维护靠 on_order_filled），
    on_order_filled 成交后挂反向单，on_pause 撤单，on_resume 重新挂网格。
    """
    category = "基础策略"
    description = "网格交易：在价格区间内均匀布置买卖网格，高抛低吸"
    priority = "P0"
    param_schema = {
        "upper_price": {"type": "number", "required": True, "description": "价格上限"},
        "lower_price": {"type": "number", "required": True, "description": "价格下限"},
        "grid_count": {"type": "number", "required": True, "description": "网格数量"},
        "order_qty": {"type": "number", "required": True, "description": "单格交易量"},
        "symbol": {"type": "string", "required": True, "description": "交易对"},
    }

    def __init__(self, upper_price: float, lower_price: float, grid_count: int,
                 order_qty: float, symbol: str):
        self.upper_price = float(upper_price)
        self.lower_price = float(lower_price)
        self.grid_count = int(grid_count)
        self.order_qty = float(order_qty)
        self.symbol = symbol
        # 派生
        self.step = (self.upper_price - self.lower_price) / (self.grid_count - 1)
        self.levels = [self.lower_price + i * self.step for i in range(self.grid_count)]
        self.tick_size = 0.1 if "-SWAP" in symbol else 0.01
        self.tick_decimals = 1 if "-SWAP" in symbol else 2
        # 状态
        self.active_buy: dict[int, str] = {}   # grid_idx -> ordId
        self.active_sell: dict[int, str] = {}
        self._started = False

    def _round_price(self, level: float) -> float:
        return round(round(level / self.tick_size) * self.tick_size, self.tick_decimals)

    def _price_str(self, level: float) -> str:
        return f"{self._round_price(level):.{self.tick_decimals}f}"

    def get_theoretical_position(self, ctx=None) -> float:
        """当前价位下理论应持有的多头仓位（已成交的买单 - 已成交的卖单）。
        简化：基于当前价位的网格位置，理论持仓 = 当前价以下的网格数 * order_qty（做多网格）。
        """
        price = ctx.current_price if ctx and ctx.current_price else (self.lower_price + self.upper_price) / 2
        below_count = sum(1 for lvl in self.levels if lvl < price)
        return below_count * self.order_qty

    async def on_start(self, ctx: ExecutionContext) -> None:
        """放置初始网格订单：当前价以下挂买单，以上挂卖单。"""
        client = ctx.client
        symbol = self.symbol
        current_price = ctx.current_price
        if current_price <= 0:
            ticker = await client.get_ticker(symbol)
            current_price = float(ticker[0]["last"]) if ticker else (self.lower_price + self.upper_price) / 2
            ctx.current_price = current_price

        buy_orders, sell_orders = [], []
        for i, level in enumerate(self.levels):
            if level < current_price:
                buy_orders.append({"idx": i, "px": self._price_str(level)})
            elif level > current_price:
                sell_orders.append({"idx": i, "px": self._price_str(level)})

        BATCH = 20
        for batch_start in range(0, len(buy_orders), BATCH):
            batch = buy_orders[batch_start:batch_start + BATCH]
            payload = [{"instId": symbol, "side": "buy", "ordType": "limit",
                        "sz": str(self.order_qty), "px": o["px"]} for o in batch]
            resp = await client.batch_place_orders(payload)
            if resp.get("code") == "0":
                data = resp.get("data", [])
                for j, o in enumerate(batch):
                    if j < len(data) and data[j].get("sCode") == "0":
                        oid = data[j].get("ordId", "")
                        self.active_buy[o["idx"]] = oid
                        ctx.order_manager.add_order(oid, "", symbol, "buy", o["px"], str(self.order_qty), "live")
            await asyncio.sleep(0.15)

        for batch_start in range(0, len(sell_orders), BATCH):
            batch = sell_orders[batch_start:batch_start + BATCH]
            payload = [{"instId": symbol, "side": "sell", "ordType": "limit",
                        "sz": str(self.order_qty), "px": o["px"]} for o in batch]
            resp = await client.batch_place_orders(payload)
            if resp.get("code") == "0":
                data = resp.get("data", [])
                for j, o in enumerate(batch):
                    if j < len(data) and data[j].get("sCode") == "0":
                        oid = data[j].get("ordId", "")
                        self.active_sell[o["idx"]] = oid
                        ctx.order_manager.add_order(oid, "", symbol, "sell", o["px"], str(self.order_qty), "live")
            await asyncio.sleep(0.15)
        self._started = True

    async def on_order_filled(self, order_info, ctx: ExecutionContext) -> None:
        """成交后挂反向单（买单成交→挂卖单，卖单成交→挂买单）。

        核心逻辑参考 grid_strategy.py 的 _on_order_filled，区别在于：
        - 用 ctx.client 下单
        - 用 ctx.order_manager 跟踪订单
        - 用 ctx.strategy._record_event 记录事件
        - 用 ctx.strategy.add_realized_pnl 累加已实现盈亏
        """
        client = ctx.client
        order_manager = ctx.order_manager
        strategy = ctx.strategy
        symbol = self.symbol

        side = order_info.side
        px = float(order_info.px) if order_info.px else 0
        sz = float(order_info.sz) if order_info.sz else 0
        ordId = order_info.ordId

        # 按成交价匹配 grid 索引
        grid_idx = None
        for i, level in enumerate(self.levels):
            price = self._round_price(level)
            if abs(price - px) < self.tick_size * 0.6:
                grid_idx = i
                break

        if grid_idx is None:
            return

        if side == "buy":
            # 买单成交：从 active_buy 移除，挂卖单到 idx+1 的 level
            if grid_idx in self.active_buy:
                del self.active_buy[grid_idx]
            order_manager.update_order(ordId, state="filled",
                                       fillPx=str(px), fillSz=str(sz))
            strategy._record_event("order_filled",
                f"BUY 已成交: {symbol} ordId={ordId} px={px} qty={sz}",
                {"order_id": ordId, "side": "buy", "price": px, "quantity": sz})

            sell_price = self._round_price(self.levels[grid_idx] + self.step)
            sell_price_str = f"{sell_price:.{self.tick_decimals}f}"
            try:
                sell_resp = await client.place_order(
                    inst_id=symbol, side="sell", ord_type="limit",
                    sz=str(self.order_qty), px=sell_price_str,
                )
            except Exception as e:
                strategy._record_event("order_failed",
                    f"买单成交后下卖单异常: grid_idx={grid_idx} px={sell_price_str} err={e}")
                return
            if sell_resp.get("code") == "0":
                sell_ord_id = sell_resp.get("data", [{}])[0].get("ordId", "")
                self.active_sell[grid_idx + 1] = sell_ord_id
                order_manager.add_order(sell_ord_id, "", symbol, "sell",
                                        sell_price_str, str(self.order_qty), "live")
                strategy._record_event("order_placed",
                    f"SELL 挂单: {symbol} ordId={sell_ord_id} px={sell_price} qty={self.order_qty}",
                    {"order_id": sell_ord_id, "side": "sell", "price": sell_price,
                     "quantity": self.order_qty, "grid_idx": grid_idx + 1})
            else:
                strategy._record_event("order_failed",
                    f"买单成交后下卖单失败: grid_idx={grid_idx} px={sell_price_str} "
                    f"code={sell_resp.get('code')} msg={sell_resp.get('msg', '')}")

        elif side == "sell":
            # 卖单成交：从 active_sell 移除，计算 cycle_pnl，挂买单到 idx-1 的 level
            if grid_idx in self.active_sell:
                del self.active_sell[grid_idx]

            buy_px_for_pnl = self.levels[grid_idx - 1] if grid_idx > 0 else self.levels[grid_idx] - self.step
            cycle_pnl = (px - buy_px_for_pnl) * sz
            strategy.add_realized_pnl(cycle_pnl)

            order_manager.update_order(ordId, state="filled",
                                       fillPx=str(px), fillSz=str(sz))
            strategy._record_event("order_filled",
                f"SELL 已成交: {symbol} ordId={ordId} px={px} qty={sz} cycle_pnl={cycle_pnl}",
                {"order_id": ordId, "side": "sell", "price": px, "quantity": sz,
                 "cycle_pnl": cycle_pnl})

            buy_price = self._round_price(self.levels[grid_idx] - self.step)
            buy_price_str = f"{buy_price:.{self.tick_decimals}f}"
            try:
                buy_resp = await client.place_order(
                    inst_id=symbol, side="buy", ord_type="limit",
                    sz=str(self.order_qty), px=buy_price_str,
                )
            except Exception as e:
                strategy._record_event("order_failed",
                    f"卖单成交后下买单异常: grid_idx={grid_idx} px={buy_price_str} err={e}")
                return
            if buy_resp.get("code") == "0":
                buy_ord_id = buy_resp.get("data", [{}])[0].get("ordId", "")
                self.active_buy[grid_idx - 1] = buy_ord_id
                order_manager.add_order(buy_ord_id, "", symbol, "buy",
                                        buy_price_str, str(self.order_qty), "live")
                strategy._record_event("order_placed",
                    f"BUY 挂单: {symbol} ordId={buy_ord_id} px={buy_price} qty={self.order_qty}",
                    {"order_id": buy_ord_id, "side": "buy", "price": buy_price,
                     "quantity": self.order_qty, "grid_idx": grid_idx - 1})
            else:
                strategy._record_event("order_failed",
                    f"卖单成交后下买单失败: grid_idx={grid_idx} px={buy_price_str} "
                    f"code={buy_resp.get('code')} msg={buy_resp.get('msg', '')}")

    async def on_pause(self, ctx: ExecutionContext) -> None:
        """撤销所有挂单，保留持仓。"""
        await ctx.order_manager.cancel_all(self.symbol)
        self.active_buy.clear()
        self.active_sell.clear()

    async def on_resume(self, ctx: ExecutionContext) -> None:
        """重新挂网格（基于当前价）。复用 on_start 的挂单逻辑但不重置 _started。"""
        # 调用 on_start 的挂单部分（重新挂当前价以下的买单、以上的卖单）
        await self.on_start(ctx)

    async def on_tick(self, ctx: ExecutionContext) -> None:
        """PnL 记录与可选的 REST 轮询兜底。网格主要靠 on_order_filled 维护。"""
        # P0 简化：可不实现实质逻辑，PnL 记录由 ComposableStrategy 统一处理
        pass

    async def on_stop(self, ctx: ExecutionContext) -> None:
        """撤销所有挂单。"""
        await ctx.order_manager.cancel_all(self.symbol)
        self.active_buy.clear()
        self.active_sell.clear()
