"""DSL 执行上下文。

指标 / 条件 / 动作 / 事件积木在求值与执行时共享的上下文对象。
由 ComposableStrategy 在每个 tick 构造并传入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.okx_client import OKXClient
    from services.order_manager import OrderManager


@dataclass
class ExecutionContext:
    """单次 tick 内的执行上下文。

    所有积木通过 ctx 访问 OKX 客户端、订单管理器、基础策略钩子、
    策略级 KV 状态、指标缓存等。同 tick 内复用同一实例。
    """

    # —— 外部依赖 ——
    client: "OKXClient"
    order_manager: "OrderManager"
    base_strategy: Any = None  # 基础策略 Block（grid/trend 等），暴露 on_* 钩子
    strategy: Any = None       # ComposableStrategy 实例本身（用于 record_event / realized_pnl 等）

    # —— 身份信息 ——
    instance_id: int = 0
    account_id: int = 0
    symbol: str = ""           # 基础策略的主交易对（来自 base_strategy.params["symbol"]）

    # —— 当前 tick 信息 ——
    tick_ts: float = 0.0       # unix 秒
    current_price: float = 0.0 # 缓存的最新价（由执行器在每个 tick 填充）

    # —— 策略级 KV 状态（跨 tick 持久，跨规则共享）——
    kv_state: dict[str, Any] = field(default_factory=dict)

    # —— 处于触发态的规则名集合（用于 rule_active 指标）——
    active_rules: set[str] = field(default_factory=set)

    # —— 同 tick 内指标缓存（key = (kind, frozenset(args.items()))）——
    indicator_cache: dict[tuple, Any] = field(default_factory=dict)

    # —— 用于 log_event 等 db 写入 ——
    db_session_factory: Any = None

    # —— 已实现盈亏（由执行器从 strategy._realized_pnl 同步）——
    realized_pnl: float = 0.0

    def get_state(self, key: str, default: Any = None) -> Any:
        return self.kv_state.get(key, default)

    def set_state(self, key: str, value: Any) -> None:
        self.kv_state[key] = value

    def clear_state(self, key: str) -> None:
        self.kv_state.pop(key, None)

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
