"""P0 动作积木库。

通过 ``@action(kind)`` 装饰器自动注册到 ``action_registry``。
每个动作类暴露统一接口：

- 类属性：``category`` / ``description`` / ``param_schema`` / ``priority``
- ``__init__(self, **args)``：接收参数
- ``async execute(self, ctx: ExecutionContext) -> None``：执行动作

使用前需在 ComposableStrategy 首次使用前导入一次（如 ``import dsl.blocks.actions``）。
"""
from __future__ import annotations

import asyncio
from typing import Any

from dsl.registry import action
from dsl.context import ExecutionContext


# —— 策略控制类 ——


@action("pause_orders")
class PauseOrders:
    """暂停挂单：撤挂单但保留持仓。"""

    category = "策略控制"
    label = "暂停挂单"
    description = "暂停策略挂单（撤挂单但保留持仓），优先调用基础策略 on_pause 钩子"
    param_schema = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "label": "交易对", "description": "交易对，默认取 ctx.symbol"},
        },
    }
    priority = "P0"

    def __init__(self, symbol: str | None = None):
        self.symbol = symbol

    async def execute(self, ctx: ExecutionContext) -> None:
        symbol = self.symbol or ctx.symbol
        # 先记录触发事件（确保条件触发可被验证），再执行网络操作
        ctx.strategy._record_event("dsl_action", f"pause_orders: {symbol}")
        if ctx.base_strategy is not None:
            await ctx.base_strategy.on_pause(ctx)
        else:
            # 回退：直接撤销所有挂单
            await ctx.order_manager.cancel_all(symbol)


@action("resume_orders")
class ResumeOrders:
    """恢复挂单：重新挂网格。"""

    category = "策略控制"
    label = "恢复挂单"
    description = "恢复策略挂单（重新挂网格），调用基础策略 on_resume 钩子"
    param_schema = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "label": "交易对", "description": "交易对，默认取 ctx.symbol"},
        },
    }
    priority = "P0"

    def __init__(self, symbol: str | None = None):
        self.symbol = symbol

    async def execute(self, ctx: ExecutionContext) -> None:
        symbol = self.symbol or ctx.symbol
        # 先记录触发事件（确保条件触发可被验证），再执行网络操作
        ctx.strategy._record_event("dsl_action", f"resume_orders: {symbol}")
        if ctx.base_strategy is not None:
            await ctx.base_strategy.on_resume(ctx)


@action("hold_position")
class HoldPosition:
    """保持当前持仓：仅记录事件，无其他副作用。"""

    category = "策略控制"
    label = "持有不动"
    description = "保持当前持仓不动，仅记录事件"
    param_schema = {"type": "object", "properties": {}}
    priority = "P0"

    def __init__(self):
        pass

    async def execute(self, ctx: ExecutionContext) -> None:
        ctx.strategy._record_event("dsl_action", "hold_position: 保持当前持仓")


# —— 持仓类 ——


@action("rebalance_position")
class RebalancePosition:
    """再平衡持仓：将实际持仓拉到理论持仓。"""

    category = "持仓"
    label = "调仓"
    description = "再平衡持仓至理论持仓，按 mode 抹平差值（市价单）"
    param_schema = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "label": "交易对", "description": "交易对，默认取 ctx.symbol"},
            "mode": {
                "type": "select",
                "label": "再平衡模式",
                "options": ["to_theoretical", "to_target", "from_zero"],
                "option_labels": ["到理论持仓", "到目标持仓", "从零开始"],
                "default": "to_theoretical",
                "description": "再平衡模式，默认 to_theoretical",
            },
            "target": {"type": "number", "label": "目标持仓", "description": "目标持仓（mode=to_target 时使用）"},
        },
    }
    priority = "P0"

    def __init__(
        self,
        symbol: str | None = None,
        mode: str = "to_theoretical",
        target: float | None = None,
    ):
        self.symbol = symbol
        self.mode = mode
        self.target = target

    async def execute(self, ctx: ExecutionContext) -> None:
        symbol = self.symbol or ctx.symbol

        # 基础策略需提供理论持仓接口
        if ctx.base_strategy is None or not hasattr(ctx.base_strategy, "get_theoretical_position"):
            ctx.strategy._record_event(
                "dsl_warn",
                "rebalance_position: base_strategy 无 get_theoretical_position 方法，跳过",
                {"symbol": symbol, "mode": self.mode},
            )
            return

        # 获取理论持仓（同步方法）
        theoretical = float(ctx.base_strategy.get_theoretical_position(ctx))

        # 获取实际持仓：从 positions 列表中匹配 symbol（网络调用，可能失败）
        actual = 0.0
        try:
            positions = await asyncio.wait_for(
                ctx.client.get_positions(), timeout=5.0
            )
            for pos in positions:
                inst_id = pos.get("instId") if isinstance(pos, dict) else getattr(pos, "instId", None)
                if inst_id == symbol:
                    pos_val = pos.get("pos") if isinstance(pos, dict) else getattr(pos, "pos", "0")
                    actual = float(pos_val or 0)
                    break
        except Exception:
            # 网络错误：先记录触发事件（确保条件触发可被验证），再向上抛出
            ctx.strategy._record_event(
                "dsl_action",
                f"rebalance_position: {symbol} (获取持仓失败, theoretical={theoretical})",
                {"symbol": symbol, "mode": self.mode, "theoretical": theoretical, "actual": None},
            )
            raise

        delta = theoretical - actual

        details = {
            "symbol": symbol,
            "mode": self.mode,
            "theoretical": theoretical,
            "actual": actual,
            "delta": delta,
        }

        # 差值极小则无需操作
        if abs(delta) <= 0.0001:
            ctx.strategy._record_event(
                "dsl_info",
                f"rebalance_position: 持仓已平衡 delta={delta}",
                details,
            )
            return

        # delta>0 买入，delta<0 卖出
        side = "buy" if delta > 0 else "sell"
        sz = str(abs(delta))
        await ctx.client.place_order(symbol, side, "market", sz)

        details["side"] = side
        details["sz"] = sz
        ctx.strategy._record_event(
            "dsl_action",
            f"rebalance_position: {side} {sz} {symbol} (delta={delta})",
            details,
        )


# —— 订单类 ——


@action("place_order")
class PlaceOrder:
    """下单：调用 OKX 客户端 place_order。"""

    category = "订单"
    label = "下单"
    description = "下一笔订单（市价或限价）"
    param_schema = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "label": "交易对", "description": "交易对"},
            "side": {
                "type": "select",
                "label": "买卖方向",
                "options": ["buy", "sell"],
                "option_labels": ["买入", "卖出"],
                "description": "买卖方向 buy/sell",
            },
            "type": {
                "type": "select",
                "label": "订单类型",
                "options": ["market", "limit"],
                "option_labels": ["市价", "限价"],
                "description": "订单类型 market/limit",
            },
            "qty": {"type": "number", "label": "数量", "description": "数量"},
            "price": {"type": "number", "label": "价格", "description": "价格（限价单必填）"},
        },
        "required": ["symbol", "side", "type", "qty"],
    }
    priority = "P0"

    def __init__(self, symbol: str, side: str, type: str, qty: float, price: float | None = None):
        self.symbol = symbol
        self.side = side
        self.type = type
        self.qty = qty
        self.price = price

    async def execute(self, ctx: ExecutionContext) -> None:
        px = str(self.price) if self.price else None
        resp = await ctx.client.place_order(self.symbol, self.side, self.type, str(self.qty), px=px)
        details = {
            "symbol": self.symbol,
            "side": self.side,
            "type": self.type,
            "qty": self.qty,
            "price": self.price,
            "resp": resp,
        }
        ctx.strategy._record_event(
            "dsl_action",
            f"place_order: {self.side} {self.qty} {self.symbol} @ {self.type}",
            details,
        )


@action("cancel_all")
class CancelAll:
    """撤销指定 symbol 的所有挂单。"""

    category = "订单"
    label = "撤销全部"
    description = "撤销指定交易对的所有挂单"
    param_schema = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "label": "交易对", "description": "交易对，默认取 ctx.symbol"},
        },
    }
    priority = "P0"

    def __init__(self, symbol: str | None = None):
        self.symbol = symbol

    async def execute(self, ctx: ExecutionContext) -> None:
        symbol = self.symbol or ctx.symbol
        cancelled = await ctx.order_manager.cancel_all(symbol)
        ctx.strategy._record_event(
            "dsl_action",
            f"cancel_all: 撤销 {cancelled} 笔订单 {symbol}",
            {"symbol": symbol, "cancelled": cancelled},
        )


# —— 通知类 ——


@action("log_event")
class LogEvent:
    """记录事件到 StrategyEvent 表。"""

    category = "通知"
    label = "记录事件"
    description = "记录一条 DSL 事件到 StrategyEvent 表"
    param_schema = {
        "type": "object",
        "properties": {
            "level": {
                "type": "select",
                "label": "日志级别",
                "options": ["info", "warn", "error", "critical"],
                "option_labels": ["信息", "警告", "错误", "严重"],
                "default": "info",
                "description": "级别 info/warn/error/critical，默认 info",
            },
            "message": {"type": "string", "label": "事件消息", "description": "事件消息"},
            "details": {"type": "object", "label": "附加详情", "description": "附加详情"},
        },
        "required": ["message"],
    }
    priority = "P0"

    # level -> event_type 前缀映射
    _LEVEL_MAP = {
        "info": "dsl_info",
        "warn": "dsl_warn",
        "error": "dsl_error",
        "critical": "dsl_critical",
    }

    def __init__(self, level: str = "info", message: str = "", details: dict | None = None):
        self.level = level
        self.message = message
        self.details = details

    async def execute(self, ctx: ExecutionContext) -> None:
        event_type = self._LEVEL_MAP.get(self.level, "dsl_info")
        ctx.strategy._record_event(event_type, self.message, self.details)


async def execute_action(ref: Any, ctx: ExecutionContext) -> None:
    """便捷执行函数：根据 ActionRef 查找动作类并执行。

    Args:
        ref: ActionRef（或兼容对象），需含 ``kind`` 与 ``args`` 属性
        ctx: 执行上下文
    """
    from dsl.registry import action_registry

    cls = action_registry.get(ref.kind)
    if cls is None:
        raise ValueError(f"未知动作 kind: {ref.kind}")
    inst = cls(**ref.args)
    await inst.execute(ctx)


# —— 风控类 ——


async def _get_position_for_symbol(ctx: ExecutionContext, symbol: str) -> dict | None:
    """从 ctx.client.get_positions() 中匹配 symbol 的持仓 dict，未找到返回 None。"""
    try:
        positions = await ctx.client.get_positions()
    except Exception:
        return None
    for pos in positions:
        inst_id = pos.get("instId") if isinstance(pos, dict) else getattr(pos, "instId", None)
        if inst_id == symbol:
            return pos if isinstance(pos, dict) else {"instId": inst_id}
    return None


async def _close_position_market(ctx: ExecutionContext, symbol: str, pos_val: float) -> None:
    """以市价单全部平仓：多仓卖出、空仓买入。"""
    side = "sell" if pos_val > 0 else "buy"
    sz = str(abs(pos_val))
    await ctx.client.place_order(symbol, side, "market", sz)


@action("stop_loss")
class StopLoss:
    """止损：持仓盈亏比例低于阈值时全部平仓。"""

    category = "风控"
    label = "止损"
    description = "持仓盈亏比例低于阈值时全部平仓（threshold 为小数，如 -0.05 表示 -5%）"
    param_schema = {
        "type": "object",
        "properties": {
            "threshold": {
                "type": "number",
                "label": "止损阈值",
                "description": "止损盈亏比例阈值（小数，如 -0.05 表示 -5%）",
            },
            "symbol": {"type": "string", "label": "交易对", "description": "交易对，默认取 ctx.symbol"},
        },
        "required": ["threshold"],
    }
    priority = "P1"

    def __init__(self, threshold: float, symbol: str | None = None):
        self.threshold = float(threshold)
        self.symbol = symbol

    async def execute(self, ctx: ExecutionContext) -> None:
        symbol = self.symbol or ctx.symbol
        pos = await _get_position_for_symbol(ctx, symbol)
        if not pos:
            ctx.strategy._record_event(
                "dsl_info",
                f"stop_loss: 无持仓 {symbol}，跳过",
                {"symbol": symbol, "threshold": self.threshold},
            )
            return
        try:
            pos_val = float(pos.get("pos", "0"))
        except (ValueError, TypeError):
            pos_val = 0.0
        if abs(pos_val) < 1e-9:
            ctx.strategy._record_event(
                "dsl_info",
                f"stop_loss: 持仓为 0 {symbol}，跳过",
                {"symbol": symbol, "threshold": self.threshold},
            )
            return
        try:
            upl_ratio = float(pos.get("uplRatio", "0"))
        except (ValueError, TypeError):
            upl_ratio = 0.0
        if upl_ratio < self.threshold:
            await _close_position_market(ctx, symbol, pos_val)
            details = {
                "symbol": symbol,
                "pos": pos_val,
                "upl_ratio": upl_ratio,
                "threshold": self.threshold,
            }
            ctx.strategy._record_event(
                "dsl_action",
                f"stop_loss: 平仓 {symbol} (uplRatio={upl_ratio} < {self.threshold})",
                details,
            )
        else:
            ctx.strategy._record_event(
                "dsl_info",
                f"stop_loss: 未触发 {symbol} (uplRatio={upl_ratio} >= {self.threshold})",
                {"symbol": symbol, "upl_ratio": upl_ratio, "threshold": self.threshold},
            )


@action("take_profit")
class TakeProfit:
    """止盈：持仓盈亏比例高于阈值时全部平仓。"""

    category = "风控"
    label = "止盈"
    description = "持仓盈亏比例高于阈值时全部平仓（threshold 为小数，如 0.1 表示 +10%）"
    param_schema = {
        "type": "object",
        "properties": {
            "threshold": {
                "type": "number",
                "label": "止盈阈值",
                "description": "止盈盈亏比例阈值（小数，如 0.1 表示 +10%）",
            },
            "symbol": {"type": "string", "label": "交易对", "description": "交易对，默认取 ctx.symbol"},
        },
        "required": ["threshold"],
    }
    priority = "P1"

    def __init__(self, threshold: float, symbol: str | None = None):
        self.threshold = float(threshold)
        self.symbol = symbol

    async def execute(self, ctx: ExecutionContext) -> None:
        symbol = self.symbol or ctx.symbol
        pos = await _get_position_for_symbol(ctx, symbol)
        if not pos:
            ctx.strategy._record_event(
                "dsl_info",
                f"take_profit: 无持仓 {symbol}，跳过",
                {"symbol": symbol, "threshold": self.threshold},
            )
            return
        try:
            pos_val = float(pos.get("pos", "0"))
        except (ValueError, TypeError):
            pos_val = 0.0
        if abs(pos_val) < 1e-9:
            ctx.strategy._record_event(
                "dsl_info",
                f"take_profit: 持仓为 0 {symbol}，跳过",
                {"symbol": symbol, "threshold": self.threshold},
            )
            return
        try:
            upl_ratio = float(pos.get("uplRatio", "0"))
        except (ValueError, TypeError):
            upl_ratio = 0.0
        if upl_ratio > self.threshold:
            await _close_position_market(ctx, symbol, pos_val)
            details = {
                "symbol": symbol,
                "pos": pos_val,
                "upl_ratio": upl_ratio,
                "threshold": self.threshold,
            }
            ctx.strategy._record_event(
                "dsl_action",
                f"take_profit: 平仓 {symbol} (uplRatio={upl_ratio} > {self.threshold})",
                details,
            )
        else:
            ctx.strategy._record_event(
                "dsl_info",
                f"take_profit: 未触发 {symbol} (uplRatio={upl_ratio} <= {self.threshold})",
                {"symbol": symbol, "upl_ratio": upl_ratio, "threshold": self.threshold},
            )


# —— 状态管理类 ——


@action("set_var")
class SetVar:
    """设置状态变量：写入 ctx.kv_state（跨 tick 持久，跨规则共享）。"""

    category = "状态管理"
    label = "设置变量"
    description = "设置策略级状态变量（跨 tick 持久，跨规则共享）"
    param_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "label": "变量名", "description": "变量名"},
            "value": {"type": "any", "label": "变量值", "description": "变量值（任意类型）"},
        },
        "required": ["name", "value"],
    }
    priority = "P1"

    def __init__(self, name: str, value: Any = None):
        self.name = name
        self.value = value

    async def execute(self, ctx: ExecutionContext) -> None:
        ctx.set_state(self.name, self.value)
        ctx.strategy._record_event(
            "dsl_action",
            f"set_var: {self.name}={self.value}",
            {"name": self.name, "value": self.value},
        )


@action("get_var")
class GetVar:
    """获取状态变量：从 ctx.kv_state 读取值。

    注意：标准动作接口为 ``execute -> None``，本动作返回变量值以便直接调用时获取；
    经 execute_action 调度时返回值会被忽略。
    """

    category = "状态管理"
    label = "获取变量"
    description = "获取策略级状态变量的值"
    param_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "label": "变量名", "description": "变量名"},
            "default": {"type": "any", "label": "默认值", "description": "变量不存在时的默认值"},
        },
        "required": ["name"],
    }
    priority = "P1"

    def __init__(self, name: str, default: Any = None):
        self.name = name
        self.default = default

    async def execute(self, ctx: ExecutionContext) -> Any:
        value = ctx.get_state(self.name, self.default)
        ctx.strategy._record_event(
            "dsl_action",
            f"get_var: {self.name}={value}",
            {"name": self.name, "value": value},
        )
        return value
