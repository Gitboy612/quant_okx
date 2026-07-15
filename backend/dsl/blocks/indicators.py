"""P0 指标积木库。

每个指标类通过 `@indicator(kind)` 装饰器自动注册到 `indicator_registry`。
使用前需在 ComposableStrategy 首次使用前导入一次（如 `import dsl.blocks.indicators`）。

所有指标共享 `compute_indicator(ref, ctx)` 解析函数，带同 tick 缓存，
供条件库与执行器复用。
"""
import asyncio

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


def _ema_series(values: list[float], period: int) -> list[float]:
    """计算 EMA 序列（以首个值为种子，period 仅决定平滑系数）。

    返回与 values 等长的 EMA 序列；空输入返回空列表。
    """
    if not values or period <= 0:
        return []
    k = 2.0 / (period + 1)
    ema_values = [values[0]]
    for v in values[1:]:
        ema_values.append(v * k + ema_values[-1] * (1.0 - k))
    return ema_values


async def _fetch_closes(ctx: ExecutionContext, symbol: str, bar: str, limit: int) -> list[float]:
    """拉取 K 线并返回 close 序列（旧→新），失败或数据不足返回空列表。

    用 5s 超时包裹 get_candles，避免 OKX 客户端内部重试阻塞条件求值。
    超时返回空列表，使依赖该数据的指标（EMA/RSI 等）返回 0.0，
    让 or(gt/lt) 等 fallback 条件仍可触发。
    """
    try:
        candles = await asyncio.wait_for(
            ctx.client.get_candles(symbol, bar=bar, limit=str(limit)), timeout=5.0
        )
    except (asyncio.TimeoutError, Exception):
        return []
    if not candles:
        return []
    candles = list(reversed(candles))  # OKX 返回最新在前，reverse 为旧→新
    try:
        return [float(c[4]) for c in candles]
    except (IndexError, ValueError, TypeError):
        return []


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
        # 若 symbol == ctx.symbol，直接用 ctx.current_price（无论 0 或 >0）：
        # 主循环每 tick 已通过 _refresh_price 尝试刷新（含 5s 超时兜底），
        # 这里复用缓存价避免重复网络调用阻塞条件求值。
        if symbol == ctx.symbol:
            return float(ctx.current_price)
        try:
            data = await asyncio.wait_for(
                ctx.client.get_ticker(symbol), timeout=5.0
            )
        except (asyncio.TimeoutError, Exception):
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


# ============================================================
# 行情·技术指标（P1 扩展）
# ============================================================

_WINDOW_OPTIONS = ["1m", "5m", "15m", "1h", "4h", "1d"]
_WINDOW_OPTION_LABELS = ["1分钟", "5分钟", "15分钟", "1小时", "4小时", "1天"]


def _window_param_schema(description: str = "K线时间窗口") -> dict:
    """构造标准 window 参数 schema（含 options / option_labels / default）。"""
    return {
        "type": "select",
        "label": "时间窗口",
        "required": True,
        "options": _WINDOW_OPTIONS,
        "option_labels": _WINDOW_OPTION_LABELS,
        "default": "1h",
        "description": description,
    }


@indicator("macd")
class MACD:
    """MACD 指标：返回 MACD 柱状值（2*(DIF-DEA)）。

    DIF = EMA(close, fast) - EMA(close, slow)
    DEA = EMA(DIF, signal)
    MACD 柱 = 2 * (DIF - DEA)
    """

    category = "行情·技术指标"
    label = "MACD"
    description = "计算 MACD 柱状值（2*(DIF-DEA)）"
    output_type = float
    priority = "P1"
    param_schema = {
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "交易对"},
        "period_fast": {"type": "integer", "label": "快线周期", "required": True, "default": 12, "description": "快 EMA 周期，默认 12"},
        "period_slow": {"type": "integer", "label": "慢线周期", "required": True, "default": 26, "description": "慢 EMA 周期，默认 26"},
        "period_signal": {"type": "integer", "label": "信号线周期", "required": True, "default": 9, "description": "信号 EMA 周期，默认 9"},
        "window": _window_param_schema(),
    }

    def __init__(self, **args):
        self.symbol = args["symbol"]
        self.period_fast = int(args.get("period_fast", 12))
        self.period_slow = int(args.get("period_slow", 26))
        self.period_signal = int(args.get("period_signal", 9))
        self.window = args.get("window", "1h")

    async def compute(self, ctx: ExecutionContext) -> float:
        symbol = self.symbol or ctx.symbol
        if not symbol:
            return 0.0
        bar = _window_to_bar(self.window)
        # 需要 slow + signal 根 K 线以保证 EMA 收敛
        limit = self.period_slow + self.period_signal
        closes = await _fetch_closes(ctx, symbol, bar, limit)
        if not closes or len(closes) < self.period_slow + 1:
            return 0.0
        ema_fast = _ema_series(closes, self.period_fast)
        ema_slow = _ema_series(closes, self.period_slow)
        # DIF 序列
        dif = [f - s for f, s in zip(ema_fast, ema_slow)]
        # DEA = EMA(DIF, signal)
        dea = _ema_series(dif, self.period_signal)
        if not dea:
            return 0.0
        # MACD 柱 = 2 * (DIF - DEA)
        return 2.0 * (dif[-1] - dea[-1])


@indicator("ema")
class EMA:
    """EMA 指数移动平均线指标。"""

    category = "行情·技术指标"
    label = "EMA均线"
    description = "计算 EMA 指数移动平均线"
    output_type = float
    priority = "P1"
    param_schema = {
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "交易对"},
        "period": {"type": "integer", "label": "周期", "required": True, "default": 20, "description": "EMA 周期，默认 20"},
        "window": _window_param_schema(),
    }

    def __init__(self, **args):
        self.symbol = args["symbol"]
        self.period = int(args.get("period", 20))
        self.window = args.get("window", "1h")

    async def compute(self, ctx: ExecutionContext) -> float:
        symbol = self.symbol or ctx.symbol
        if not symbol:
            return 0.0
        bar = _window_to_bar(self.window)
        closes = await _fetch_closes(ctx, symbol, bar, self.period)
        if not closes:
            return 0.0
        ema_series = _ema_series(closes, self.period)
        if not ema_series:
            return 0.0
        return ema_series[-1]


@indicator("kdj")
class KDJ:
    """KDJ 随机指标：返回 J 值。

    RSV = (close - lowest_low) / (highest_high - lowest_low) * 100
    K = 2/3 * K_prev + 1/3 * RSV
    D = 2/3 * D_prev + 1/3 * K
    J = 3 * K - 2 * D
    """

    category = "行情·技术指标"
    label = "KDJ"
    description = "计算 KDJ 随机指标，返回 J 值"
    output_type = float
    priority = "P1"
    param_schema = {
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "交易对"},
        "period": {"type": "integer", "label": "周期", "required": True, "default": 9, "description": "KDJ 周期，默认 9"},
        "window": _window_param_schema(),
    }

    def __init__(self, **args):
        self.symbol = args["symbol"]
        self.period = int(args.get("period", 9))
        self.window = args.get("window", "1h")

    async def compute(self, ctx: ExecutionContext) -> float:
        symbol = self.symbol or ctx.symbol
        if not symbol:
            return 50.0
        bar = _window_to_bar(self.window)
        try:
            candles = await ctx.client.get_candles(symbol, bar=bar, limit=str(self.period))
        except Exception:
            return 50.0
        if not candles or len(candles) < self.period:
            return 50.0
        candles = list(reversed(candles))  # 旧→新
        try:
            highs = [float(c[2]) for c in candles]
            lows = [float(c[3]) for c in candles]
            closes = [float(c[4]) for c in candles]
        except (IndexError, ValueError, TypeError):
            return 50.0

        # K/D 初值取 50（业界惯例）
        k = 50.0
        d = 50.0
        for i in range(self.period - 1, len(closes)):
            lowest_low = min(lows[i - self.period + 1: i + 1])
            highest_high = max(highs[i - self.period + 1: i + 1])
            if highest_high == lowest_low:
                rsv = 50.0
            else:
                rsv = (closes[i] - lowest_low) / (highest_high - lowest_low) * 100.0
            k = 2.0 / 3.0 * k + 1.0 / 3.0 * rsv
            d = 2.0 / 3.0 * d + 1.0 / 3.0 * k
        j = 3.0 * k - 2.0 * d
        return j


@indicator("volatility")
class Volatility:
    """波动率指标：收益率标准差。"""

    category = "行情·技术指标"
    label = "波动率"
    description = "计算指定周期内收益率的标准差（波动率）"
    output_type = float
    priority = "P1"
    param_schema = {
        "symbol": {"type": "string", "label": "交易对", "required": True, "description": "交易对"},
        "period": {"type": "integer", "label": "周期", "required": True, "default": 20, "description": "波动率周期，默认 20"},
        "window": _window_param_schema(),
    }

    def __init__(self, **args):
        self.symbol = args["symbol"]
        self.period = int(args.get("period", 20))
        self.window = args.get("window", "1h")

    async def compute(self, ctx: ExecutionContext) -> float:
        symbol = self.symbol or ctx.symbol
        if not symbol:
            return 0.0
        bar = _window_to_bar(self.window)
        # 需要 period+1 根 K 线来算 period 个收益率
        closes = await _fetch_closes(ctx, symbol, bar, self.period + 1)
        if not closes or len(closes) < 2:
            return 0.0
        # 计算收益率序列
        returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] == 0:
                continue
            returns.append((closes[i] - closes[i - 1]) / closes[i - 1])
        if len(returns) < 2:
            return 0.0
        # 总体标准差
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return variance ** 0.5


@indicator("volume_24h")
class Volume24h:
    """24 小时成交量指标。"""

    category = "行情·价格"
    label = "24h成交量"
    description = "获取指定交易对的 24 小时成交量（vol24h）"
    output_type = float
    priority = "P1"
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
            data = await ctx.client.get_ticker(symbol)
        except Exception:
            return 0.0
        if not data:
            return 0.0
        try:
            return float(data[0].get("vol24h", "0"))
        except (ValueError, TypeError, KeyError, IndexError):
            return 0.0
