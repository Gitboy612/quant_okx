"""可拼接策略 DSL —— P0 事件积木库。

事件采用轮询检查模型：执行器每个 tick 调用事件的 `check(ctx)`，
返回 payload（dict）表示触发，返回 None 表示未触发。
对于 push 型事件（如 on_order_filled），执行器预先在 OrderManager
注册回调把事件推入队列，事件 check() 从队列取。

重要提示（执行器实现方）：
    执行器应缓存事件实例（按 kind+args 复用同一实例），以便跨 tick
    保留实例级状态（如 on_interval 的 _last_fired、on_order_filled 的
    _queue）。本模块导出的 check_event() 便捷函数每次都会新建实例，
    仅适用于无状态检查，不能用于有状态事件。实际执行器应：
      1. 启动时为每条 Rule 的事件构造一次实例并缓存；
      2. 对每个实例调用 bind(ctx)（push 型事件在此注册回调）；
      3. 每个 tick 复用缓存的实例调用 check(ctx)。
"""
from __future__ import annotations

from typing import Any

from dsl.registry import event, event_registry
from dsl.context import ExecutionContext


class Event:
    """事件积木基类。

    子类需定义类属性 category / description / param_schema / priority，
    并实现 async check(ctx) -> dict | None。
    push 型事件可覆盖 bind(ctx) 注册外部回调。
    """

    category: str = "未分类"
    description: str = ""
    param_schema: dict = {}
    priority: str = "P1"

    def __init__(self, **args: Any) -> None:
        self.args = args

    def bind(self, ctx: ExecutionContext) -> None:
        """默认空实现。push 型事件覆盖此方法注册外部回调。"""
        return None

    async def check(self, ctx: ExecutionContext) -> dict | None:
        raise NotImplementedError


@event("on_tick")
class OnTick(Event):
    """每个 tick 都触发的高频评估事件。"""

    category = "行情·事件"
    label = "行情更新"
    description = "每个 tick 触发，返回当前时间戳与最新价"
    param_schema = {"symbol": {"type": "str", "label": "交易对", "required": False}}
    priority = "P0"

    async def check(self, ctx: ExecutionContext) -> dict | None:
        return {
            "ts": ctx.tick_ts,
            "price": ctx.current_price,
        }


@event("on_interval")
class OnInterval(Event):
    """固定时间间隔触发的事件。

    实例级状态 _last_fired 跨 tick 保持（执行器复用同一事件实例）。
    """

    category = "定时"
    label = "定时触发"
    description = "每隔 seconds 秒触发一次"
    param_schema = {"seconds": {"type": "float", "label": "间隔秒数", "unit": "秒", "required": True}}
    priority = "P0"

    def __init__(self, **args: Any) -> None:
        super().__init__(**args)
        self.seconds: float = float(args.get("seconds", 0))
        # 上次触发时间，初始化为 0 保证首次 tick 必触发
        self._last_fired: float = 0.0

    async def check(self, ctx: ExecutionContext) -> dict | None:
        if ctx.tick_ts - self._last_fired >= self.seconds:
            self._last_fired = ctx.tick_ts
            return {"ts": ctx.tick_ts}
        return None


@event("on_order_filled")
class OnOrderFilled(Event):
    """订单成交事件（push 型）。

    执行器启动时调用 bind(ctx) 注册 OrderManager 的 filled 回调，
    成交订单会被推入实例队列；check() 从队列取并按 side/symbol 过滤。
    """

    category = "订单·事件"
    label = "订单成交"
    description = "订单成交时触发，可按 side/symbol 过滤"
    param_schema = {
        "side": {
            "type": "select",
            "label": "买卖方向",
            "options": ["buy", "sell"],
            "option_labels": ["买入", "卖出"],
            "required": False,
        },
        "symbol": {"type": "str", "label": "交易对", "required": False},
    }
    priority = "P0"

    def __init__(self, **args: Any) -> None:
        super().__init__(**args)
        self.side: str | None = args.get("side")
        self.symbol: str | None = args.get("symbol")
        # 实例级队列：_on_filled 追加，check 弹出
        self._queue: list = []

    def bind(self, ctx: ExecutionContext) -> None:
        """注册 OrderManager 的 filled 回调，把成交订单推入实例队列。"""
        ctx.order_manager.on("filled", self._on_filled)

    def _on_filled(self, order_info: Any) -> None:
        """OrderManager filled 回调：把订单追加到实例队列。"""
        self._queue.append(order_info)

    async def check(self, ctx: ExecutionContext) -> dict | None:
        # 从队列逐个弹出，按 side/symbol 过滤；不匹配的丢弃
        # （不匹配的订单对本实例无意义，其它实例有自己的队列副本）
        while self._queue:
            order = self._queue.pop(0)
            d = order.to_dict() if hasattr(order, "to_dict") else dict(order)
            if self.side is not None and d.get("side") != self.side:
                continue
            if self.symbol is not None and d.get("symbol") != self.symbol:
                continue
            return {
                "side": d.get("side"),
                "symbol": d.get("symbol"),
                "px": d.get("px"),
                "sz": d.get("sz"),
                "ordId": d.get("ordId"),
            }
        return None


@event("on_margin_warning")
class OnMarginWarning(Event):
    """保证金率低于阈值时触发的事件。"""

    category = "持仓·事件"
    label = "保证金预警"
    description = "持仓保证金率低于阈值时触发"
    param_schema = {
        "symbol": {"type": "str", "label": "交易对", "required": True},
        "threshold": {"type": "float", "label": "保证金率阈值", "unit": "保证金率", "required": False, "default": 0.5},
    }
    priority = "P0"

    def __init__(self, **args: Any) -> None:
        super().__init__(**args)
        self.symbol: str = args.get("symbol", "")
        self.threshold: float = float(args.get("threshold", 0.5))

    async def check(self, ctx: ExecutionContext) -> dict | None:
        positions = await ctx.client.get_positions()
        if not positions:
            return None
        for pos in positions:
            if pos.get("instId") != self.symbol:
                continue
            # mgnRatio 缺失时按 1（安全）处理
            mgn_ratio = float(pos.get("mgnRatio", "1"))
            if mgn_ratio < self.threshold:
                return {
                    "symbol": self.symbol,
                    "margin_ratio": mgn_ratio,
                    "threshold": self.threshold,
                }
            return None
        # 无对应 symbol 持仓
        return None


@event("on_strategy_error")
class OnStrategyError(Event):
    """策略异常事件（一次性消费）。

    执行器在捕获异常时设置 kv_state["_strategy_error_flag"] = True
    与 _strategy_error_msg；本事件 check() 检测到 flag 后返回 payload
    并清除 flag（一次性消费），避免重复触发。
    """

    category = "策略·生命周期"
    label = "策略异常"
    description = "策略抛出异常时触发（一次性消费）"
    param_schema = {}
    priority = "P0"

    async def check(self, ctx: ExecutionContext) -> dict | None:
        if not ctx.kv_state.get("_strategy_error_flag"):
            return None
        msg = ctx.kv_state.get("_strategy_error_msg", "")
        # 一次性消费：清除 flag 与消息
        ctx.kv_state["_strategy_error_flag"] = False
        ctx.kv_state.pop("_strategy_error_msg", None)
        return {"message": msg}


async def check_event(ref, ctx: ExecutionContext) -> dict | None:
    """便捷函数：根据 EventRef 无状态地检查一次事件。

    注意：此函数每次都会新建事件实例，无法保留跨 tick 的实例级状态
    （如 on_interval 的 _last_fired、on_order_filled 的 _queue）。
    实际执行器应按 kind+args 缓存事件实例并复用，并对 push 型事件
    在启动时调用 bind(ctx)。
    """
    cls = event_registry.get(ref.kind)
    if cls is None:
        raise ValueError(f"未知事件 kind: {ref.kind}")
    inst = cls(**ref.args)
    return await inst.check(ctx)
