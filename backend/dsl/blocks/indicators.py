"""P0 指标积木库。

每个指标类通过 `@indicator(kind)` 装饰器自动注册到 `indicator_registry`。
使用前需在 ComposableStrategy 首次使用前导入一次（如 `import dsl.blocks.indicators`）。

所有指标共享 `compute_indicator(ref, ctx)` 解析函数，带同 tick 缓存，
供条件库与执行器复用。
"""
from dsl.registry import indicator, indicator_registry
from dsl.schema import IndicatorRef
from dsl.context import ExecutionContext


async def compute_indicator(ref: IndicatorRef, ctx: ExecutionContext):
    """根据 IndicatorRef 实例化指标并计算，带同 tick 缓存。供条件库与执行器复用。"""
    key = (ref.kind, tuple(sorted(ref.args.items())))
    if key in ctx.indicator_cache:
        return ctx.indicator_cache[key]
    cls = indicator_registry.get(ref.kind)
    if cls is None:
        raise ValueError(f"未知指标 kind: {ref.kind}")
    inst = cls(**ref.args)
    value = await inst.compute(ctx)
    ctx.indicator_cache[key] = value
    return value


def _window_to_bar(window: str) -> str:
    """将用户友好的窗口串转为 OKX bar 参数。

    OKX bar 参数大小写敏感：分钟小写 m，小时大写 H，天大写 D。
    例：'1h' -> '1H'，'5m' -> '5m'，'1d' -> '1D'。
    """
    window = window.strip()
    if not window:
        return "1H"
    unit = window[-1]
    num = window[:-1]
    mapping = {"h": "H", "H": "H", "m": "m", "M": "m", "d": "D", "D": "D"}
    return f"{num}{mapping.get(unit, unit)}"


# ============================================================
# 行情·价格
# ============================================================

@indicator("price_last")
class PriceLast:
    """最新价指标。"""

    category = "行情·价格"
    label = "最新价"
    description = "获取指定交易对的最新成交价"
    output_type = float
    priority = "P0"
    param_schema = {
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "交易对，如 BTC-USDT"},
    }

    def __init__(self, **args):
        self.symbol = args["symbol"]

    async def compute(self, ctx: ExecutionContext) -> float:
        # symbol 为空时回退到 ctx.symbol（实例级交易对）
        symbol = self.symbol or ctx.symbol
        if not symbol:
            return 0.0
        # 若 symbol == ctx.symbol 且 current_price > 0，直接用缓存价避免重复请求
        if symbol == ctx.symbol and ctx.current_price > 0:
            return float(ctx.current_price)
        try:
            data = await ctx.client.get_ticker(symbol)
        except Exception:
            return 0.0
        if not data:
            return 0.0
        return float(data[0]["last"])


@indicator("price_change_pct")
class PriceChangePct:
    """价格涨跌幅指标（指定窗口）。"""

    category = "行情·价格"
    label = "涨跌幅"
    description = "计算指定时间窗口内的价格涨跌幅（小数，0.05=5%）"
    output_type = float
    priority = "P0"
    param_schema = {
        "window": {
            "type": "select",
            "label": "时间窗口",
            "required": True,
            "options": ["1m", "5m", "15m", "1h", "4h", "1d"],
            "option_labels": ["1分钟", "5分钟", "15分钟", "1小时", "4小时", "1天"],
            "default": "1h",
            "description": "K线时间窗口",
        },
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "交易对"},
    }

    def __init__(self, **args):
        self.window = args["window"]
        self.symbol = args["symbol"]

    async def compute(self, ctx: ExecutionContext) -> float:
        symbol = self.symbol or ctx.symbol
        if not symbol:
            return 0.0
        bar = _window_to_bar(self.window)
        try:
            candles = await ctx.client.get_candles(symbol, bar=bar, limit="2")
        except Exception:
            return 0.0
        if not candles or len(candles) < 2:
            return 0.0
        try:
            # OKX 返回最新在前，candles[1] 是上一根（已完成）K线，[4] 是 close
            ref = float(candles[1][4])
        except (IndexError, ValueError, TypeError):
            return 0.0
        if ref == 0:
            return 0.0
        # 当前价：优先用 ctx.current_price（若 symbol==ctx.symbol），否则请求 ticker
        if self.symbol == ctx.symbol and ctx.current_price > 0:
            current = float(ctx.current_price)
        else:
            try:
                data = await ctx.client.get_ticker(symbol)
                current = float(data[0]["last"])
            except Exception:
                return 0.0
        return (current - ref) / ref


# ============================================================
# 行情·技术指标
# ============================================================

@indicator("rsi")
class RSI:
    """RSI 相对强弱指标（标准 Wilder 平滑）。"""

    category = "行情·技术指标"
    label = "RSI"
    description = "计算 RSI 指标（Wilder 平滑），返回 [0, 100]"
    output_type = float
    priority = "P0"
    param_schema = {
        "period": {"type": "integer", "label": "RSI周期", "required": True, "description": "RSI 周期，如 14"},
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "交易对"},
    }

    def __init__(self, **args):
        self.period = int(args["period"])
        self.symbol = args["symbol"]

    async def compute(self, ctx: ExecutionContext) -> float:
        period = self.period
        symbol = self.symbol or ctx.symbol
        if not symbol:
            return 50.0
        try:
            candles = await ctx.client.get_candles(
                symbol, bar="1H", limit=str(period + 1)
            )
        except Exception:
            return 50.0
        if not candles or len(candles) < period + 1:
            return 50.0
        # OKX 返回最新在前，reverse 为时间正序（旧→新）
        candles = list(reversed(candles))
        try:
            closes = [float(c[4]) for c in candles]
        except (IndexError, ValueError, TypeError):
            return 50.0

        # 计算涨跌幅序列
        gains = []
        losses = []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            if diff > 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(-diff)

        if len(gains) < period:
            return 50.0

        # 首次平均：前 period 个涨跌的简单平均
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        # Wilder 平滑后续值（若有更多数据）
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi


# ============================================================
# 账户·持仓
# ============================================================

@indicator("position_qty")
class PositionQty:
    """持仓量指标。"""

    category = "账户·持仓"
    label = "持仓数量"
    description = "获取指定交易对的持仓量（正多负空）"
    output_type = float
    priority = "P0"
    param_schema = {
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "交易对"},
    }

    def __init__(self, **args):
        self.symbol = args["symbol"]

    async def compute(self, ctx: ExecutionContext) -> float:
        symbol = self.symbol or ctx.symbol
        if not symbol:
            return 0.0
        try:
            positions = await ctx.client.get_positions()
        except Exception:
            return 0.0
        for pos in positions:
            if pos.get("instId") == symbol:
                try:
                    return float(pos.get("pos", "0"))
                except (ValueError, TypeError):
                    return 0.0
        return 0.0


@indicator("position_pnl")
class PositionPnl:
    """持仓未实现盈亏指标。"""

    category = "账户·持仓"
    label = "持仓盈亏"
    description = "获取指定交易对持仓的未实现盈亏（upl）"
    output_type = float
    priority = "P0"
    param_schema = {
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "交易对"},
    }

    def __init__(self, **args):
        self.symbol = args["symbol"]

    async def compute(self, ctx: ExecutionContext) -> float:
        symbol = self.symbol or ctx.symbol
        if not symbol:
            return 0.0
        try:
            positions = await ctx.client.get_positions()
        except Exception:
            return 0.0
        for pos in positions:
            if pos.get("instId") == symbol:
                try:
                    return float(pos.get("upl", "0"))
                except (ValueError, TypeError):
                    return 0.0
        return 0.0


@indicator("account_equity")
class AccountEquity:
    """账户净值指标。"""

    category = "账户·持仓"
    label = "账户净值"
    description = "获取账户总净值（totalEq）"
    output_type = float
    priority = "P0"
    param_schema = {}

    def __init__(self, **args):
        pass

    async def compute(self, ctx: ExecutionContext) -> float:
        try:
            data = await ctx.client.get_balance()
        except Exception:
            return 0.0
        try:
            return float(data.get("totalEq", "0"))
        except (ValueError, TypeError):
            return 0.0


# ============================================================
# 策略·内部状态
# ============================================================

@indicator("realized_pnl")
class RealizedPnl:
    """已实现盈亏指标（来自执行器同步的 ctx.realized_pnl）。"""

    category = "策略·内部状态"
    label = "已实现盈亏"
    description = "策略已实现盈亏（由执行器从 strategy._realized_pnl 同步）"
    output_type = float
    priority = "P0"
    param_schema = {}

    def __init__(self, **args):
        pass

    async def compute(self, ctx: ExecutionContext) -> float:
        return float(ctx.realized_pnl)


@indicator("unrealized_pnl")
class UnrealizedPnl:
    """未实现盈亏指标。

    优先从持仓 upl 获取；若无持仓且 symbol==ctx.symbol，P0 简化为 0.0。
    """

    category = "策略·内部状态"
    label = "未实现盈亏"
    description = "未实现盈亏（优先用持仓 upl，无持仓返回 0.0）"
    output_type = float
    priority = "P0"
    param_schema = {
        "symbol": {"type": "string", "label": "交易对", "required": False, "description": "交易对，默认用 ctx.symbol"},
    }

    def __init__(self, **args):
        self.symbol = args.get("symbol")  # 可选，可能为 None

    async def compute(self, ctx: ExecutionContext) -> float:
        sym = self.symbol or ctx.symbol
        try:
            positions = await ctx.client.get_positions()
        except Exception:
            return 0.0
        for pos in positions:
            if pos.get("instId") == sym:
                try:
                    return float(pos.get("upl", "0"))
                except (ValueError, TypeError):
                    return 0.0
        # 无持仓，P0 简化为 0.0
        return 0.0
