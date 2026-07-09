"""基础策略类积木：可钩子调用的 Block 实现。

由 ComposableStrategy 实例化并编排，不继承 BaseStrategy，
避免与原有 execute() 主循环冲突。通过 @base_strategy 装饰器
注册到 base_strategy_registry，前端可通过 kind="grid" 引用。

当前注册的基础策略：
- grid            网格策略（等差/等比）
- trend           双均线趋势（金叉/死叉）
- rsi_strategy    RSI 超买超卖
- bollinger_bands 布林带
- donchian        唐奇安通道（海龟突破）
- dca             定投策略
- martingale      马丁格尔
"""
import asyncio

from dsl.registry import base_strategy
from dsl.context import ExecutionContext


# 信号驱动型策略（trend/rsi/bollinger/donchian）下单时的默认数量。
# 这些策略的 param_schema 聚焦于信号参数，下单数量使用该默认值，
# 可在后续扩展中通过可选 order_qty 参数覆盖。
DEFAULT_ORDER_QTY = 0.001

# 马丁格尔触发加仓的逆向波动阈值（比例），无 price_step 参数时使用。
DEFAULT_MARTINGALE_STEP_PCT = 0.005


# ============================================================
# 通用计算辅助（纯 Python，避免 numpy/pandas 依赖）
# ============================================================

async def _fetch_closes(client, symbol: str, bar: str = "1H",
                        limit: str = "100") -> list[float]:
    """拉取 K 线并返回 close 序列（旧→新）。失败返回空列表。

    OKX get_candles 返回最新在前，candle[4] 为 close。
    """
    try:
        candles = await client.get_candles(symbol, bar=bar, limit=limit)
    except Exception:
        return []
    if not candles:
        return []
    closes: list[float] = []
    for c in reversed(candles):  # 反转为旧→新
        try:
            closes.append(float(c[4]))
        except (IndexError, ValueError, TypeError):
            continue
    return closes


def _sma(values: list[float], period: int) -> float | None:
    """简单移动平均。数据不足返回 None。"""
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:]) / period


def _rsi(closes: list[float], period: int) -> float | None:
    """RSI（Wilder 平滑）。数据不足返回 None。"""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-diff)
    if len(gains) < period:
        return None
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _bollinger(closes: list[float], period: int, std_mult: float):
    """布林带 (mid, upper, lower)。数据不足返回 None。"""
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = sum(window) / period
    var = sum((x - mid) ** 2 for x in window) / period
    std = var ** 0.5
    return mid, mid + std_mult * std, mid - std_mult * std


def _record(ctx: ExecutionContext, event_type: str, message: str,
            details: dict | None = None) -> None:
    """安全地通过 ctx.strategy 记录事件。"""
    strategy = getattr(ctx, "strategy", None)
    if strategy is not None and hasattr(strategy, "_record_event"):
        try:
            strategy._record_event(event_type, message, details)
        except Exception:
            pass


# ============================================================
# 1. 网格策略
# ============================================================

@base_strategy("grid")
class GridBlock:
    """网格基础策略的可拼接 Block（钩子式）。

    由 ComposableStrategy 实例化并编排：on_start 放初始网格，
    on_tick 监控（网格策略的 on_tick 主要用于 PnL 记录，挂单维护靠 on_order_filled），
    on_order_filled 成交后挂反向单，on_pause 撤单，on_resume 重新挂网格。
    """
    label = "网格策略"
    category = "基础策略"
    description = "网格交易：在价格区间内均匀布置买卖网格，高抛低吸"
    priority = "P0"
    param_schema = {
        "upper_price": {"type": "number", "label": "价格上限", "required": True, "description": "价格上限"},
        "lower_price": {"type": "number", "label": "价格下限", "required": True, "description": "价格下限"},
        "grid_count": {"type": "number", "label": "网格数量", "required": True, "description": "网格数量"},
        "order_qty": {"type": "number", "label": "单格数量", "required": False, "default": 0.001, "description": "单格交易量"},
        "grid_mode": {"type": "select", "label": "网格模式", "required": False, "options": ["arithmetic", "geometric"], "option_labels": ["等差", "等比"], "default": "arithmetic", "description": "等差/等比"},
        "direction": {"type": "select", "label": "交易方向", "required": False, "options": ["long", "short", "neutral"], "option_labels": ["做多", "做空", "双向"], "default": "neutral", "description": "交易方向"},
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "交易对"},
    }

    def __init__(self, upper_price: float, lower_price: float, grid_count: int,
                 symbol: str, order_qty: float = 0.001,
                 grid_mode: str = "arithmetic", direction: str = "neutral"):
        self.upper_price = float(upper_price)
        self.lower_price = float(lower_price)
        self.grid_count = int(grid_count)
        self.order_qty = float(order_qty)
        self.grid_mode = grid_mode
        self.direction = direction
        self.symbol = symbol
        # 派生：等差步长（同时作为反向单价差兜底）与网格位
        self.step = (self.upper_price - self.lower_price) / (self.grid_count - 1)
        if self.grid_mode == "geometric" and self.lower_price > 0 and self.upper_price > 0:
            ratio = (self.upper_price / self.lower_price) ** (1.0 / (self.grid_count - 1))
            self.levels = [self.lower_price * (ratio ** i) for i in range(self.grid_count)]
        else:
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

        # direction 过滤：long 只挂买单，short 只挂卖单，neutral 双向
        place_buy = self.direction in ("long", "neutral")
        place_sell = self.direction in ("short", "neutral")

        buy_orders, sell_orders = [], []
        for i, level in enumerate(self.levels):
            if level < current_price and place_buy:
                buy_orders.append({"idx": i, "px": self._price_str(level)})
            elif level > current_price and place_sell:
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

            if grid_idx + 1 >= self.grid_count:
                return
            sell_price = self._round_price(self.levels[grid_idx + 1])
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

            if grid_idx <= 0:
                return
            buy_price = self._round_price(self.levels[grid_idx - 1])
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


# ============================================================
# 2. 双均线趋势策略
# ============================================================

@base_strategy("trend")
class TrendBlock:
    """双均线趋势策略：短期均线上穿长期均线（金叉）做多，下穿（死叉）做空。"""
    label = "双均线趋势"
    category = "基础策略"
    description = "短期均线上穿长期均线（金叉）做多，下穿（死叉）做空"
    priority = "P1"
    param_schema = {
        "fast_period": {"type": "integer", "label": "快均线周期", "required": True, "min": 1, "max": 50, "default": 5, "description": "快速移动平均线周期"},
        "slow_period": {"type": "integer", "label": "慢均线周期", "required": True, "min": 5, "max": 200, "default": 20, "description": "慢速移动平均线周期"},
        "direction": {"type": "select", "label": "交易方向", "required": False, "options": ["long", "short", "both"], "option_labels": ["做多", "做空", "双向"], "default": "both"},
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "如 BTC-USDT"},
    }

    def __init__(self, fast_period: int, slow_period: int, symbol: str,
                 direction: str = "both"):
        self.fast_period = int(fast_period)
        self.slow_period = int(slow_period)
        self.symbol = symbol
        self.direction = direction
        # 状态
        self.last_signal: str | None = None

    async def on_start(self, ctx: ExecutionContext) -> None:
        """初始化历史价格缓存与信号状态。"""
        self.last_signal = None
        _record(ctx, "started", f"双均线趋势策略启动: {self.symbol} fast={self.fast_period} slow={self.slow_period}")

    async def on_tick(self, ctx: ExecutionContext) -> None:
        """计算快慢均线，检测金叉/死叉并下单。"""
        limit = str(self.slow_period + 10)
        closes = await _fetch_closes(ctx.client, self.symbol, bar="1H", limit=limit)
        if len(closes) < self.slow_period + 1:
            return

        fast_ma = _sma(closes, self.fast_period)
        slow_ma = _sma(closes, self.slow_period)
        prev_fast = _sma(closes[:-1], self.fast_period)
        prev_slow = _sma(closes[:-1], self.slow_period)
        if None in (fast_ma, slow_ma, prev_fast, prev_slow):
            return

        signal = None
        # 金叉：快线从下方穿越到上方
        if prev_fast <= prev_slow and fast_ma > slow_ma:
            signal = "buy"
        # 死叉：快线从上方穿越到下方
        elif prev_fast >= prev_slow and fast_ma < slow_ma:
            signal = "sell"

        if signal is None or signal == self.last_signal:
            return

        # 方向过滤
        if signal == "buy" and self.direction == "short":
            return
        if signal == "sell" and self.direction == "long":
            return

        try:
            resp = await ctx.client.place_order(
                inst_id=self.symbol, side=signal, ord_type="market",
                sz=str(DEFAULT_ORDER_QTY),
            )
            if resp.get("code") == "0":
                self.last_signal = signal
                _record(ctx, "order_placed",
                        f"{'金叉' if signal == 'buy' else '死叉'} 下单: {self.symbol} {signal}",
                        {"side": signal, "fast_ma": fast_ma, "slow_ma": slow_ma})
        except Exception as e:
            _record(ctx, "order_failed", f"双均线下单异常: {e}")

    async def on_pause(self, ctx: ExecutionContext) -> None:
        """撤销所有挂单。"""
        await ctx.order_manager.cancel_all(self.symbol)

    async def on_resume(self, ctx: ExecutionContext) -> None:
        """恢复后重置信号缓存，重新计算。"""
        self.last_signal = None

    async def on_stop(self, ctx: ExecutionContext) -> None:
        """清理状态。"""
        await ctx.order_manager.cancel_all(self.symbol)
        self.last_signal = None


# ============================================================
# 3. RSI 超买超卖策略
# ============================================================

@base_strategy("rsi_strategy")
class RsiBlock:
    """RSI 超买超卖策略：RSI 低于超卖线买入，高于超买线卖出。"""
    label = "RSI 超买超卖"
    category = "基础策略"
    description = "RSI 低于超卖阈值时买入，高于超买阈值时卖出"
    priority = "P1"
    param_schema = {
        "period": {"type": "integer", "label": "RSI周期", "required": True, "min": 6, "max": 30, "default": 14, "description": "RSI 计算周期"},
        "oversold": {"type": "integer", "label": "超卖阈值", "required": False, "min": 10, "max": 45, "default": 30, "description": "RSI 低于该值买入"},
        "overbought": {"type": "integer", "label": "超买阈值", "required": False, "min": 55, "max": 90, "default": 70, "description": "RSI 高于该值卖出"},
        "direction": {"type": "select", "label": "交易方向", "required": False, "options": ["long", "short", "both"], "option_labels": ["做多", "做空", "双向"], "default": "both"},
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "如 BTC-USDT"},
    }

    def __init__(self, period: int, symbol: str, oversold: int = 30,
                 overbought: int = 70, direction: str = "both"):
        self.period = int(period)
        self.oversold = int(oversold)
        self.overbought = int(overbought)
        self.symbol = symbol
        self.direction = direction
        self.last_signal: str | None = None

    async def on_start(self, ctx: ExecutionContext) -> None:
        """初始化信号状态。"""
        self.last_signal = None
        _record(ctx, "started", f"RSI 策略启动: {self.symbol} period={self.period}")

    async def on_tick(self, ctx: ExecutionContext) -> None:
        """计算 RSI，超卖买入，超买卖出。"""
        closes = await _fetch_closes(ctx.client, self.symbol, bar="1H",
                                     limit=str(self.period + 2))
        rsi = _rsi(closes, self.period)
        if rsi is None:
            return

        signal = None
        if rsi < self.oversold:
            signal = "buy"
        elif rsi > self.overbought:
            signal = "sell"

        if signal is None or signal == self.last_signal:
            return

        # 方向过滤
        if signal == "buy" and self.direction == "short":
            return
        if signal == "sell" and self.direction == "long":
            return

        try:
            resp = await ctx.client.place_order(
                inst_id=self.symbol, side=signal, ord_type="market",
                sz=str(DEFAULT_ORDER_QTY),
            )
            if resp.get("code") == "0":
                self.last_signal = signal
                _record(ctx, "order_placed",
                        f"RSI={rsi:.2f} {'超卖' if signal == 'buy' else '超买'} 下单: {self.symbol} {signal}",
                        {"side": signal, "rsi": rsi})
        except Exception as e:
            _record(ctx, "order_failed", f"RSI 下单异常: {e}")

    async def on_pause(self, ctx: ExecutionContext) -> None:
        await ctx.order_manager.cancel_all(self.symbol)

    async def on_resume(self, ctx: ExecutionContext) -> None:
        self.last_signal = None

    async def on_stop(self, ctx: ExecutionContext) -> None:
        await ctx.order_manager.cancel_all(self.symbol)
        self.last_signal = None


# ============================================================
# 4. 布林带策略
# ============================================================

@base_strategy("bollinger_bands")
class BollingerBlock:
    """布林带策略：价格跌破下轨买入，突破上轨卖出。"""
    label = "布林带"
    category = "基础策略"
    description = "价格跌破布林带下轨买入，突破上轨卖出，回归中轨"
    priority = "P1"
    param_schema = {
        "period": {"type": "integer", "label": "计算周期", "required": True, "min": 10, "max": 50, "default": 20, "description": "布林带计算周期"},
        "std_multiplier": {"type": "number", "label": "标准差倍数", "required": False, "min": 1.0, "max": 3.5, "default": 2.0, "description": "标准差倍数"},
        "direction": {"type": "select", "label": "交易方向", "required": False, "options": ["long", "short", "both"], "option_labels": ["做多", "做空", "双向"], "default": "both"},
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "如 BTC-USDT"},
    }

    def __init__(self, period: int, symbol: str, std_multiplier: float = 2.0,
                 direction: str = "both"):
        self.period = int(period)
        self.std_multiplier = float(std_multiplier)
        self.symbol = symbol
        self.direction = direction
        self.last_signal: str | None = None

    async def on_start(self, ctx: ExecutionContext) -> None:
        self.last_signal = None
        _record(ctx, "started", f"布林带策略启动: {self.symbol} period={self.period} std={self.std_multiplier}")

    async def on_tick(self, ctx: ExecutionContext) -> None:
        """计算布林带上下轨，价格<下轨买入，价格>上轨卖出。"""
        closes = await _fetch_closes(ctx.client, self.symbol, bar="1H",
                                     limit=str(self.period + 2))
        bands = _bollinger(closes, self.period, self.std_multiplier)
        if bands is None or not closes:
            return
        mid, upper, lower = bands
        price = closes[-1]

        signal = None
        if price < lower:
            signal = "buy"
        elif price > upper:
            signal = "sell"

        if signal is None or signal == self.last_signal:
            return

        if signal == "buy" and self.direction == "short":
            return
        if signal == "sell" and self.direction == "long":
            return

        try:
            resp = await ctx.client.place_order(
                inst_id=self.symbol, side=signal, ord_type="market",
                sz=str(DEFAULT_ORDER_QTY),
            )
            if resp.get("code") == "0":
                self.last_signal = signal
                _record(ctx, "order_placed",
                        f"布林带 {'触下轨' if signal == 'buy' else '触上轨'} 下单: {self.symbol} {signal} price={price}",
                        {"side": signal, "price": price, "upper": upper, "lower": lower})
        except Exception as e:
            _record(ctx, "order_failed", f"布林带下单异常: {e}")

    async def on_pause(self, ctx: ExecutionContext) -> None:
        await ctx.order_manager.cancel_all(self.symbol)

    async def on_resume(self, ctx: ExecutionContext) -> None:
        self.last_signal = None

    async def on_stop(self, ctx: ExecutionContext) -> None:
        await ctx.order_manager.cancel_all(self.symbol)
        self.last_signal = None


# ============================================================
# 5. 唐奇安通道策略
# ============================================================

@base_strategy("donchian")
class DonchianBlock:
    """唐奇安通道策略（海龟法则）：突破入场周期最高价做多，跌破离场周期最低价平多。"""
    label = "唐奇安通道"
    category = "基础策略"
    description = "突破入场周期最高价做多，跌破离场周期最低价平多"
    priority = "P1"
    param_schema = {
        "entry_period": {"type": "integer", "label": "入场周期", "required": True, "min": 10, "max": 60, "default": 20, "description": "突破入场回溯周期"},
        "exit_period": {"type": "integer", "label": "离场周期", "required": False, "min": 5, "max": 30, "default": 10, "description": "离场回溯周期"},
        "direction": {"type": "select", "label": "交易方向", "required": False, "options": ["long", "short", "both"], "option_labels": ["做多", "做空", "双向"], "default": "both"},
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "如 BTC-USDT"},
    }

    def __init__(self, entry_period: int, symbol: str, exit_period: int = 10,
                 direction: str = "both"):
        self.entry_period = int(entry_period)
        self.exit_period = int(exit_period)
        self.symbol = symbol
        self.direction = direction
        self.position_side: str | None = None  # 当前持仓方向

    async def on_start(self, ctx: ExecutionContext) -> None:
        self.position_side = None
        _record(ctx, "started", f"唐奇安通道策略启动: {self.symbol} entry={self.entry_period} exit={self.exit_period}")

    async def on_tick(self, ctx: ExecutionContext) -> None:
        """计算通道高低点，突破入场最高价做多，跌破离场最低价平多。"""
        lookback = max(self.entry_period, self.exit_period) + 2
        closes = await _fetch_closes(ctx.client, self.symbol, bar="1H",
                                     limit=str(lookback))
        if len(closes) < self.entry_period + 1:
            return

        # 入场信号使用前 entry_period 根（不含当前）
        entry_window = closes[-(self.entry_period + 1):-1]
        entry_high = max(entry_window) if entry_window else 0.0
        entry_low = min(entry_window) if entry_window else 0.0
        # 离场信号使用前 exit_period 根（不含当前）
        exit_window = closes[-(self.exit_period + 1):-1] if len(closes) >= self.exit_period + 1 else entry_window
        exit_low = min(exit_window) if exit_window else 0.0
        exit_high = max(exit_window) if exit_window else 0.0

        price = closes[-1]

        # 做多逻辑：突破入场最高价开多，跌破离场最低价平多
        if price > entry_high and self.position_side != "long":
            if self.direction in ("long", "both"):
                side = "buy"
                try:
                    resp = await ctx.client.place_order(
                        inst_id=self.symbol, side=side, ord_type="market",
                        sz=str(DEFAULT_ORDER_QTY),
                    )
                    if resp.get("code") == "0":
                        self.position_side = "long"
                        _record(ctx, "order_placed",
                                f"突破入场高点做多: {self.symbol} price={price} > entry_high={entry_high}",
                                {"side": side, "price": price, "entry_high": entry_high})
                except Exception as e:
                    _record(ctx, "order_failed", f"唐奇安开多异常: {e}")

        elif self.position_side == "long" and price < exit_low:
            try:
                resp = await ctx.client.place_order(
                    inst_id=self.symbol, side="sell", ord_type="market",
                    sz=str(DEFAULT_ORDER_QTY),
                )
                if resp.get("code") == "0":
                    self.position_side = None
                    _record(ctx, "order_placed",
                            f"跌破离场低点平多: {self.symbol} price={price} < exit_low={exit_low}",
                            {"side": "sell", "price": price, "exit_low": exit_low})
            except Exception as e:
                _record(ctx, "order_failed", f"唐奇安平多异常: {e}")

        # 做空逻辑（双向时）：跌破入场最低价开空，突破离场最高价平空
        if self.direction in ("short", "both") and price < entry_low and self.position_side != "short":
            try:
                resp = await ctx.client.place_order(
                    inst_id=self.symbol, side="sell", ord_type="market",
                    sz=str(DEFAULT_ORDER_QTY),
                )
                if resp.get("code") == "0":
                    self.position_side = "short"
                    _record(ctx, "order_placed",
                            f"跌破入场低点做空: {self.symbol} price={price} < entry_low={entry_low}",
                            {"side": "sell", "price": price, "entry_low": entry_low})
            except Exception as e:
                _record(ctx, "order_failed", f"唐奇安开空异常: {e}")
        elif self.position_side == "short" and price > exit_high:
            try:
                resp = await ctx.client.place_order(
                    inst_id=self.symbol, side="buy", ord_type="market",
                    sz=str(DEFAULT_ORDER_QTY),
                )
                if resp.get("code") == "0":
                    self.position_side = None
                    _record(ctx, "order_placed",
                            f"突破离场高点平空: {self.symbol} price={price} > exit_high={exit_high}",
                            {"side": "buy", "price": price, "exit_high": exit_high})
            except Exception as e:
                _record(ctx, "order_failed", f"唐奇安平空异常: {e}")

    async def on_pause(self, ctx: ExecutionContext) -> None:
        await ctx.order_manager.cancel_all(self.symbol)

    async def on_resume(self, ctx: ExecutionContext) -> None:
        # 恢复后保持持仓方向，等待新的突破信号
        pass

    async def on_stop(self, ctx: ExecutionContext) -> None:
        await ctx.order_manager.cancel_all(self.symbol)
        self.position_side = None


# ============================================================
# 6. 定投策略
# ============================================================

@base_strategy("dca")
class DcaBlock:
    """定投策略：固定时间、固定金额买入，平摊成本。"""
    label = "定投策略"
    category = "基础策略"
    description = "按固定频率和金额定时买入，平摊持仓成本"
    priority = "P1"
    param_schema = {
        "amount": {"type": "number", "label": "每期金额", "required": True, "min": 0.0001, "default": 100, "description": "每期投资金额（计价货币）"},
        "frequency": {"type": "select", "label": "定投频率", "required": False, "options": ["daily", "weekly", "monthly"], "option_labels": ["每日", "每周", "每月"], "default": "daily"},
        "day_of_week": {"type": "integer", "label": "星期几", "required": False, "min": 0, "max": 6, "default": 1, "description": "每周定投的星期（0=周日）"},
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "如 BTC-USDT"},
    }

    def __init__(self, amount: float, symbol: str, frequency: str = "daily",
                 day_of_week: int = 1):
        self.amount = float(amount)
        self.symbol = symbol
        self.frequency = frequency
        self.day_of_week = int(day_of_week)
        # 状态
        self.last_execute_date: str | None = None  # YYYY-MM-DD

    def _should_execute(self, now) -> bool:
        """根据频率与当前时间判断是否到达定投时点。返回 True 且尚未执行。"""
        date_str = now.strftime("%Y-%m-%d")
        if date_str == self.last_execute_date:
            return False
        if self.frequency == "daily":
            return True
        if self.frequency == "weekly":
            # now.weekday(): 周一=0 ... 周日=6；day_of_week 用 0=周日 与 Python 反向
            py_weekday = (self.day_of_week - 1) % 7  # 周日(0)->6, 周一(1)->0
            return now.weekday() == py_weekday
        if self.frequency == "monthly":
            return now.day == 1
        return False

    async def on_start(self, ctx: ExecutionContext) -> None:
        """记录上次执行时间。"""
        self.last_execute_date = None
        _record(ctx, "started", f"定投策略启动: {self.symbol} amount={self.amount} freq={self.frequency}")

    async def on_tick(self, ctx: ExecutionContext) -> None:
        """检查是否到定投时点，是则按金额市价买入。"""
        now = ExecutionContext.now_utc()
        if not self._should_execute(now):
            return

        # 获取当前价计算买入数量
        price = ctx.current_price
        if price <= 0:
            try:
                ticker = await ctx.client.get_ticker(self.symbol)
                price = float(ticker[0]["last"]) if ticker else 0.0
            except Exception:
                price = 0.0
        if price <= 0:
            return

        qty = self.amount / price
        if qty <= 0:
            return

        try:
            resp = await ctx.client.place_order(
                inst_id=self.symbol, side="buy", ord_type="market",
                sz=str(qty),
            )
            if resp.get("code") == "0":
                self.last_execute_date = now.strftime("%Y-%m-%d")
                _record(ctx, "order_placed",
                        f"定投买入: {self.symbol} amount={self.amount} price={price} qty={qty}",
                        {"side": "buy", "amount": self.amount, "price": price, "quantity": qty})
        except Exception as e:
            _record(ctx, "order_failed", f"定投下单异常: {e}")

    async def on_pause(self, ctx: ExecutionContext) -> None:
        await ctx.order_manager.cancel_all(self.symbol)

    async def on_resume(self, ctx: ExecutionContext) -> None:
        pass

    async def on_stop(self, ctx: ExecutionContext) -> None:
        await ctx.order_manager.cancel_all(self.symbol)
        self.last_execute_date = None


# ============================================================
# 7. 马丁格尔策略
# ============================================================

@base_strategy("martingale")
class MartingaleBlock:
    """马丁格尔策略：亏损后按倍数加仓，一次盈利覆盖全部亏损并平仓重置。"""
    label = "马丁格尔"
    category = "基础策略"
    description = "亏损后按倍数加仓，盈利后全平重置，达到最大层级停止"
    priority = "P1"
    param_schema = {
        "initial_size": {"type": "number", "label": "初始数量", "required": True, "min": 0.0001, "default": 0.001, "description": "初始交易数量"},
        "multiplier": {"type": "number", "label": "加仓倍数", "required": False, "min": 1.1, "max": 3.0, "default": 2.0, "description": "亏损后加仓倍数"},
        "max_levels": {"type": "integer", "label": "最大层级", "required": False, "min": 2, "max": 20, "default": 5, "description": "最大加仓层级"},
        "direction": {"type": "select", "label": "交易方向", "required": False, "options": ["long", "short"], "option_labels": ["做多", "做空"], "default": "long"},
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "如 BTC-USDT"},
    }

    def __init__(self, initial_size: float, symbol: str, multiplier: float = 2.0,
                 max_levels: int = 5, direction: str = "long"):
        self.initial_size = float(initial_size)
        self.multiplier = float(multiplier)
        self.max_levels = int(max_levels)
        self.direction = direction
        self.symbol = symbol
        # 状态
        self.level = 0            # 当前已加仓层级（0=未开仓）
        self.total_size = 0.0     # 累计持仓数量
        self.avg_price = 0.0      # 加权平均成本
        self.last_size = 0.0      # 上一笔加仓数量

    async def _place_entry(self, ctx: ExecutionContext, side: str, size: float) -> bool:
        """市价开/加仓，更新加权成本与层级。返回是否成功。"""
        try:
            resp = await ctx.client.place_order(
                inst_id=self.symbol, side=side, ord_type="market", sz=str(size),
            )
        except Exception as e:
            _record(ctx, "order_failed", f"马丁格尔下单异常: {e}")
            return False
        if resp.get("code") != "0":
            _record(ctx, "order_failed", f"马丁格尔下单失败: code={resp.get('code')} msg={resp.get('msg', '')}")
            return False

        # 更新加权平均成本
        price = ctx.current_price
        if price <= 0:
            try:
                ticker = await ctx.client.get_ticker(self.symbol)
                price = float(ticker[0]["last"]) if ticker else 0.0
            except Exception:
                price = 0.0
        if self.total_size > 0 and price > 0:
            self.avg_price = (self.avg_price * self.total_size + price * size) / (self.total_size + size)
        elif price > 0:
            self.avg_price = price
        self.total_size += size
        self.last_size = size
        self.level += 1
        _record(ctx, "order_placed",
                f"马丁格尔加仓 level={self.level}: {self.symbol} {side} size={size} avg={self.avg_price}",
                {"side": side, "size": size, "level": self.level, "avg_price": self.avg_price})
        return True

    async def _close_all(self, ctx: ExecutionContext) -> None:
        """全平台仓并重置。"""
        if self.total_size <= 0:
            return
        close_side = "sell" if self.direction == "long" else "buy"
        try:
            resp = await ctx.client.place_order(
                inst_id=self.symbol, side=close_side, ord_type="market",
                sz=str(self.total_size),
            )
            if resp.get("code") == "0":
                price = ctx.current_price
                if price <= 0:
                    try:
                        ticker = await ctx.client.get_ticker(self.symbol)
                        price = float(ticker[0]["last"]) if ticker else 0.0
                    except Exception:
                        price = 0.0
                pnl = (price - self.avg_price) * self.total_size if self.direction == "long" \
                    else (self.avg_price - price) * self.total_size
                if ctx.strategy is not None and hasattr(ctx.strategy, "add_realized_pnl"):
                    ctx.strategy.add_realized_pnl(pnl)
                _record(ctx, "order_placed",
                        f"马丁格尔全平重置: {self.symbol} pnl={pnl} level={self.level}",
                        {"side": close_side, "size": self.total_size, "pnl": pnl})
                self.level = 0
                self.total_size = 0.0
                self.avg_price = 0.0
                self.last_size = 0.0
        except Exception as e:
            _record(ctx, "order_failed", f"马丁格尔平仓异常: {e}")

    async def on_start(self, ctx: ExecutionContext) -> None:
        """下初始单。"""
        self.level = 0
        self.total_size = 0.0
        self.avg_price = 0.0
        self.last_size = 0.0
        side = "buy" if self.direction == "long" else "sell"
        await self._place_entry(ctx, side, self.initial_size)

    async def on_tick(self, ctx: ExecutionContext) -> None:
        """检测亏损则按倍数加仓，达到 max_levels 停止；盈利则全平重置。"""
        if self.total_size <= 0 or self.avg_price <= 0:
            return

        price = ctx.current_price
        if price <= 0:
            try:
                ticker = await ctx.client.get_ticker(self.symbol)
                price = float(ticker[0]["last"]) if ticker else 0.0
            except Exception:
                return
        if price <= 0:
            return

        # 计算未实现盈亏与方向
        if self.direction == "long":
            unrealized = (price - self.avg_price) * self.total_size
            adverse = self.avg_price - price
            add_side = "buy"
        else:
            unrealized = (self.avg_price - price) * self.total_size
            adverse = price - self.avg_price
            add_side = "sell"

        # 盈利则全平重置
        if unrealized > 0:
            await self._close_all(ctx)
            return

        # 亏损且达到逆向波动阈值且未达最大层级，按倍数加仓
        if self.level >= self.max_levels:
            return
        if self.avg_price > 0 and adverse / self.avg_price < DEFAULT_MARTINGALE_STEP_PCT:
            return

        next_size = self.last_size * self.multiplier
        await self._place_entry(ctx, add_side, next_size)

    async def on_pause(self, ctx: ExecutionContext) -> None:
        await ctx.order_manager.cancel_all(self.symbol)

    async def on_resume(self, ctx: ExecutionContext) -> None:
        # 恢复后保持持仓状态，等待下一个 tick
        pass

    async def on_stop(self, ctx: ExecutionContext) -> None:
        await ctx.order_manager.cancel_all(self.symbol)
        self.level = 0
        self.total_size = 0.0
        self.avg_price = 0.0
        self.last_size = 0.0
