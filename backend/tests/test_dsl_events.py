"""P0 事件积木库测试。

参考 test_backward_compat.py / test_dsl_schema.py 的导入风格：
通过 sys.path.insert 把 backend 目录加入路径，再用 from dsl.xxx 导入。
不依赖 pytest-asyncio，统一用 asyncio.run 包裹异步 check。
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from dsl.context import ExecutionContext
from dsl.schema import EventRef
from dsl.blocks.events import (  # 导入即注册到 event_registry
    Event, OnTick, OnInterval, OnOrderFilled, OnMarginWarning, OnStrategyError,
    check_event,
)
from services.order_manager import OrderInfo


def make_ctx(**kwargs):
    """构造测试用 ExecutionContext，默认填入合理值。"""
    defaults = dict(
        client=None,
        order_manager=None,
        symbol="BTC-USDT",
        tick_ts=0.0,
        current_price=0.0,
        kv_state={},
    )
    defaults.update(kwargs)
    return ExecutionContext(**defaults)


# =========================================================================
# on_tick
# =========================================================================

def test_on_tick_returns_payload():
    """on_tick 每个 tick 都触发，返回 ts 与 price。"""
    ctx = make_ctx(tick_ts=1000.0, current_price=50000.0)
    ev = OnTick(symbol="BTC-USDT")
    payload = asyncio.run(ev.check(ctx))
    assert payload == {"ts": 1000.0, "price": 50000.0}


def test_on_tick_metadata():
    ev = OnTick()
    assert ev.category == "行情·事件"
    assert ev.priority == "P0"


# =========================================================================
# on_interval
# =========================================================================

def test_on_interval_fires_first_then_skips_then_fires_again():
    """首次触发 -> 间隔内不触发 -> 超过间隔再次触发。"""
    ev = OnInterval(seconds=10)
    ctx = make_ctx(tick_ts=100)

    # 首次 check（_last_fired=0）必触发
    p1 = asyncio.run(ev.check(ctx))
    assert p1 == {"ts": 100}
    assert ev._last_fired == 100

    # tick_ts=105，未满 10 秒，不触发
    ctx.tick_ts = 105
    p2 = asyncio.run(ev.check(ctx))
    assert p2 is None

    # tick_ts=115，满 10 秒，触发
    ctx.tick_ts = 115
    p3 = asyncio.run(ev.check(ctx))
    assert p3 == {"ts": 115}
    assert ev._last_fired == 115


def test_on_interval_last_fired_persists_across_ticks():
    """实例级状态跨 tick 保持（同一事件实例被复用）。"""
    ev = OnInterval(seconds=5)
    ctx = make_ctx(tick_ts=10)
    assert asyncio.run(ev.check(ctx)) == {"ts": 10}
    # 模拟执行器复用同一实例
    ctx.tick_ts = 12
    assert asyncio.run(ev.check(ctx)) is None
    ctx.tick_ts = 16
    assert asyncio.run(ev.check(ctx)) == {"ts": 16}


# =========================================================================
# on_order_filled
# =========================================================================

class FakeOrderManager:
    """最小化 OrderManager mock，仅实现 on(event, cb)。"""

    def __init__(self):
        self.callbacks: list[tuple[str, object]] = []

    def on(self, event: str, cb):
        self.callbacks.append((event, cb))


def test_on_order_filled_bind_registers_callback():
    """bind() 应向 order_manager 注册 filled 回调。"""
    om = FakeOrderManager()
    ctx = make_ctx(order_manager=om)
    ev = OnOrderFilled(side="buy", symbol="BTC-USDT")
    ev.bind(ctx)
    assert len(om.callbacks) == 1
    assert om.callbacks[0][0] == "filled"
    assert om.callbacks[0][1] == ev._on_filled


def test_on_order_filled_filters_by_side_and_symbol():
    """check() 按 side/symbol 过滤；不匹配的被丢弃，返回首个匹配。"""
    om = FakeOrderManager()
    ctx = make_ctx(order_manager=om)
    ev = OnOrderFilled(side="buy", symbol="BTC-USDT")
    ev.bind(ctx)

    # 1) 匹配的 buy/BTC-USDT
    o1 = OrderInfo(ordId="1", symbol="BTC-USDT", side="buy", px="50000", sz="0.1")
    ev._on_filled(o1)
    # 2) side 不匹配
    o2 = OrderInfo(ordId="2", symbol="BTC-USDT", side="sell", px="51000", sz="0.2")
    ev._on_filled(o2)
    # 3) symbol 不匹配
    o3 = OrderInfo(ordId="3", symbol="ETH-USDT", side="buy", px="3000", sz="1")
    ev._on_filled(o3)

    # 第一次 check：跳过队列里前述不匹配项不存在（o1 在队首），返回 o1
    p1 = asyncio.run(ev.check(ctx))
    assert p1 == {
        "side": "buy", "symbol": "BTC-USDT",
        "px": "50000", "sz": "0.1", "ordId": "1",
    }

    # 第二次 check：o2/o3 不匹配被丢弃，队列空，返回 None
    p2 = asyncio.run(ev.check(ctx))
    assert p2 is None
    assert ev._queue == []


def test_on_order_filled_no_filter_matches_all():
    """无 side/symbol 过滤时所有成交都匹配。"""
    om = FakeOrderManager()
    ctx = make_ctx(order_manager=om)
    ev = OnOrderFilled()  # 无过滤
    ev.bind(ctx)

    o = OrderInfo(ordId="9", symbol="ETH-USDT", side="sell", px="3000", sz="2")
    ev._on_filled(o)
    p = asyncio.run(ev.check(ctx))
    assert p == {
        "side": "sell", "symbol": "ETH-USDT",
        "px": "3000", "sz": "2", "ordId": "9",
    }


def test_on_order_filled_empty_queue_returns_none():
    ev = OnOrderFilled(side="buy")
    ctx = make_ctx()
    assert asyncio.run(ev.check(ctx)) is None


# =========================================================================
# on_margin_warning
# =========================================================================

class FakeClient:
    """最小化 OKXClient mock，仅实现 get_positions。"""

    def __init__(self, positions):
        self._positions = positions

    async def get_positions(self):
        return self._positions


def test_on_margin_warning_triggers_when_ratio_below_threshold():
    positions = [
        {"instId": "BTC-USDT", "mgnRatio": "0.3"},
        {"instId": "ETH-USDT", "mgnRatio": "0.9"},
    ]
    ctx = make_ctx(client=FakeClient(positions))
    ev = OnMarginWarning(symbol="BTC-USDT", threshold=0.5)
    p = asyncio.run(ev.check(ctx))
    assert p == {"symbol": "BTC-USDT", "margin_ratio": 0.3, "threshold": 0.5}


def test_on_margin_warning_no_trigger_when_ratio_above_threshold():
    positions = [{"instId": "BTC-USDT", "mgnRatio": "0.8"}]
    ctx = make_ctx(client=FakeClient(positions))
    ev = OnMarginWarning(symbol="BTC-USDT", threshold=0.5)
    assert asyncio.run(ev.check(ctx)) is None


def test_on_margin_warning_no_position_returns_none():
    ctx = make_ctx(client=FakeClient([]))
    ev = OnMarginWarning(symbol="BTC-USDT", threshold=0.5)
    assert asyncio.run(ev.check(ctx)) is None


def test_on_margin_warning_symbol_not_in_positions():
    positions = [{"instId": "ETH-USDT", "mgnRatio": "0.1"}]
    ctx = make_ctx(client=FakeClient(positions))
    ev = OnMarginWarning(symbol="BTC-USDT", threshold=0.5)
    assert asyncio.run(ev.check(ctx)) is None


def test_on_margin_warning_default_threshold():
    positions = [{"instId": "BTC-USDT", "mgnRatio": "0.2"}]
    ctx = make_ctx(client=FakeClient(positions))
    ev = OnMarginWarning(symbol="BTC-USDT")  # 默认 threshold=0.5
    p = asyncio.run(ev.check(ctx))
    assert p["threshold"] == 0.5


# =========================================================================
# on_strategy_error
# =========================================================================

def test_on_strategy_error_consumes_flag():
    """flag 为真时返回 payload，并清除 flag（一次性消费）。"""
    ctx = make_ctx(kv_state={
        "_strategy_error_flag": True,
        "_strategy_error_msg": "boom",
    })
    ev = OnStrategyError()
    p = asyncio.run(ev.check(ctx))
    assert p == {"message": "boom"}
    # flag 被清除
    assert ctx.kv_state.get("_strategy_error_flag") is not True
    assert "_strategy_error_msg" not in ctx.kv_state
    # 第二次 check 返回 None（已消费）
    p2 = asyncio.run(ev.check(ctx))
    assert p2 is None


def test_on_strategy_error_no_flag_returns_none():
    ctx = make_ctx(kv_state={})
    ev = OnStrategyError()
    assert asyncio.run(ev.check(ctx)) is None


def test_on_strategy_error_missing_msg_returns_empty_string():
    """flag 为真但 msg 缺失时返回空字符串。"""
    ctx = make_ctx(kv_state={"_strategy_error_flag": True})
    ev = OnStrategyError()
    p = asyncio.run(ev.check(ctx))
    assert p == {"message": ""}


# =========================================================================
# check_event 便捷函数
# =========================================================================

def test_check_event_helper_on_tick():
    ctx = make_ctx(tick_ts=42.0, current_price=123.0)
    ref = EventRef(kind="on_tick", args={})
    p = asyncio.run(check_event(ref, ctx))
    assert p == {"ts": 42.0, "price": 123.0}


def test_check_event_helper_unknown_kind_raises():
    ctx = make_ctx()
    ref = EventRef(kind="on_unknown", args={})
    with pytest.raises(ValueError, match="未知事件 kind"):
        asyncio.run(check_event(ref, ctx))


# =========================================================================
# 注册表校验
# =========================================================================

def test_all_p0_events_registered():
    """五个 P0 事件均注册到 event_registry。"""
    from dsl.registry import event_registry
    for kind in ("on_tick", "on_interval", "on_order_filled",
                 "on_margin_warning", "on_strategy_error"):
        assert kind in event_registry, f"{kind} 未注册"
        cls = event_registry.get(kind)
        assert getattr(cls, "priority", None) == "P0", f"{kind} priority 非 P0"


def test_event_base_class_default_bind_is_noop():
    """基类 bind 默认空实现，不应报错。"""
    ev = OnTick()
    ctx = make_ctx()
    # 默认 bind 不应抛异常
    ev.bind(ctx)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
