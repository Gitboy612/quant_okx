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
    OnBalanceChange, OnFundingRate, OnPositionClose,
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

class FakePublicAPI:
    """模拟 OKXClient.public，仅实现 get_funding_rate。"""

    def __init__(self, funding_rates: dict | None = None):
        # {instId: [data, ...]}
        self._funding_rates = funding_rates or {}

    async def get_funding_rate(self, instId: str):
        return self._funding_rates.get(instId, [])


class FakeClient:
    """最小化 OKXClient mock，支持 get_positions/get_balance/public.get_funding_rate。"""

    def __init__(self, positions=None, balance=None, funding_rates=None):
        self._positions = positions if positions is not None else []
        self._balance = balance if balance is not None else {}
        self.public = FakePublicAPI(funding_rates)

    async def get_positions(self):
        return self._positions

    async def get_balance(self):
        return self._balance


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
# on_balance_change
# =========================================================================

def test_on_balance_change_first_check_records_baseline_no_trigger():
    """首次 check 仅记录基准，不触发。"""
    ctx = make_ctx(client=FakeClient(balance={"totalEq": "10000"}))
    ev = OnBalanceChange(threshold=0.01)
    p = asyncio.run(ev.check(ctx))
    assert p is None
    assert ev._last_balance == 10000.0


def test_on_balance_change_triggers_when_change_exceeds_threshold():
    """余额变化超过阈值时触发。"""
    ev = OnBalanceChange(threshold=0.01)
    # 第一次：记录基准
    ctx1 = make_ctx(client=FakeClient(balance={"totalEq": "10000"}))
    assert asyncio.run(ev.check(ctx1)) is None
    # 第二次：变化 2% > 1%，触发
    ctx2 = make_ctx(client=FakeClient(balance={"totalEq": "10200"}))
    p = asyncio.run(ev.check(ctx2))
    assert p is not None
    assert p["old_balance"] == 10000.0
    assert p["new_balance"] == 10200.0
    assert abs(p["change_ratio"] - 0.02) < 1e-9
    assert p["threshold"] == 0.01


def test_on_balance_change_no_trigger_when_change_below_threshold():
    """余额变化未超过阈值时不触发。"""
    ev = OnBalanceChange(threshold=0.01)
    ctx1 = make_ctx(client=FakeClient(balance={"totalEq": "10000"}))
    asyncio.run(ev.check(ctx1))
    # 变化 0.5% < 1%，不触发
    ctx2 = make_ctx(client=FakeClient(balance={"totalEq": "10050"}))
    p = asyncio.run(ev.check(ctx2))
    assert p is None
    assert ev._last_balance == 10050.0


def test_on_balance_change_triggers_on_decrease():
    """余额减少超过阈值时也触发。"""
    ev = OnBalanceChange(threshold=0.01)
    ctx1 = make_ctx(client=FakeClient(balance={"totalEq": "10000"}))
    asyncio.run(ev.check(ctx1))
    # 减少 3% > 1%，触发
    ctx2 = make_ctx(client=FakeClient(balance={"totalEq": "9700"}))
    p = asyncio.run(ev.check(ctx2))
    assert p is not None
    assert p["old_balance"] == 10000.0
    assert p["new_balance"] == 9700.0
    assert abs(p["change_ratio"] - 0.03) < 1e-9


def test_on_balance_change_default_threshold():
    """默认 threshold=0.01。"""
    ev = OnBalanceChange()
    assert ev.threshold == 0.01


def test_on_balance_change_empty_balance_returns_none():
    """get_balance 返回空时返回 None。"""
    ctx = make_ctx(client=FakeClient(balance={}))
    ev = OnBalanceChange()
    p = asyncio.run(ev.check(ctx))
    assert p is None


def test_on_balance_change_zero_baseline_to_nonzero_triggers():
    """上次余额为 0，当前非 0 时触发（绝对变化判断）。"""
    ev = OnBalanceChange(threshold=0.01)
    ctx1 = make_ctx(client=FakeClient(balance={"totalEq": "0"}))
    asyncio.run(ev.check(ctx1))  # 记录基准 0
    ctx2 = make_ctx(client=FakeClient(balance={"totalEq": "100"}))
    p = asyncio.run(ev.check(ctx2))
    assert p is not None
    assert p["old_balance"] == 0.0
    assert p["new_balance"] == 100.0


# =========================================================================
# on_funding_rate
# =========================================================================

def test_on_funding_rate_triggers_when_rate_exceeds_threshold():
    """资金费率超过阈值时触发。"""
    funding_rates = {"BTC-USDT-SWAP": [{"fundingRate": "0.002", "nextFundingTime": "1700000000000"}]}
    ctx = make_ctx(client=FakeClient(funding_rates=funding_rates), symbol="BTC-USDT-SWAP")
    ev = OnFundingRate(threshold=0.001)
    p = asyncio.run(ev.check(ctx))
    assert p is not None
    assert p["symbol"] == "BTC-USDT-SWAP"
    assert p["funding_rate"] == 0.002
    assert p["threshold"] == 0.001
    assert p["next_funding_time"] == "1700000000000"


def test_on_funding_rate_no_trigger_when_rate_below_threshold():
    """资金费率未超过阈值时不触发。"""
    funding_rates = {"BTC-USDT-SWAP": [{"fundingRate": "0.0005", "nextFundingTime": ""}]}
    ctx = make_ctx(client=FakeClient(funding_rates=funding_rates), symbol="BTC-USDT-SWAP")
    ev = OnFundingRate(threshold=0.001)
    p = asyncio.run(ev.check(ctx))
    assert p is None


def test_on_funding_rate_negative_rate_triggers_on_abs():
    """负费率按绝对值判断，超过阈值也触发。"""
    funding_rates = {"BTC-USDT-SWAP": [{"fundingRate": "-0.0015", "nextFundingTime": ""}]}
    ctx = make_ctx(client=FakeClient(funding_rates=funding_rates), symbol="BTC-USDT-SWAP")
    ev = OnFundingRate(threshold=0.001)
    p = asyncio.run(ev.check(ctx))
    assert p is not None
    assert p["funding_rate"] == -0.0015


def test_on_funding_rate_non_swap_returns_none():
    """非 swap 合约（现货）直接返回 None。"""
    ctx = make_ctx(client=FakeClient(), symbol="BTC-USDT")
    ev = OnFundingRate(threshold=0.001)
    p = asyncio.run(ev.check(ctx))
    assert p is None


def test_on_funding_rate_empty_data_returns_none():
    """费率数据为空时返回 None。"""
    ctx = make_ctx(client=FakeClient(funding_rates={}), symbol="BTC-USDT-SWAP")
    ev = OnFundingRate(threshold=0.001)
    p = asyncio.run(ev.check(ctx))
    assert p is None


def test_on_funding_rate_default_threshold():
    """默认 threshold=0.001。"""
    ev = OnFundingRate()
    assert ev.threshold == 0.001


def test_on_funding_rate_uses_param_symbol_over_ctx():
    """参数 symbol 优先于 ctx.symbol。"""
    funding_rates = {"ETH-USDT-SWAP": [{"fundingRate": "0.002", "nextFundingTime": ""}]}
    ctx = make_ctx(client=FakeClient(funding_rates=funding_rates), symbol="BTC-USDT-SWAP")
    ev = OnFundingRate(symbol="ETH-USDT-SWAP", threshold=0.001)
    p = asyncio.run(ev.check(ctx))
    assert p is not None
    assert p["symbol"] == "ETH-USDT-SWAP"


# =========================================================================
# on_position_close
# =========================================================================

def test_on_position_close_first_check_records_baseline_no_trigger():
    """首次 check 仅记录基准，不触发。"""
    positions = [{"instId": "BTC-USDT-SWAP", "pos": "1.5"}]
    ctx = make_ctx(client=FakeClient(positions=positions), symbol="BTC-USDT-SWAP")
    ev = OnPositionClose(symbol="BTC-USDT-SWAP")
    p = asyncio.run(ev.check(ctx))
    assert p is None
    assert ev._last_positions.get("BTC-USDT-SWAP") == 1.5


def test_on_position_close_triggers_when_position_becomes_zero():
    """持仓从非零变为零时触发。"""
    ev = OnPositionClose(symbol="BTC-USDT-SWAP")
    # 第一次：有持仓
    ctx1 = make_ctx(
        client=FakeClient(positions=[{"instId": "BTC-USDT-SWAP", "pos": "1.5"}]),
        symbol="BTC-USDT-SWAP",
    )
    asyncio.run(ev.check(ctx1))
    # 第二次：持仓归零
    ctx2 = make_ctx(
        client=FakeClient(positions=[{"instId": "BTC-USDT-SWAP", "pos": "0"}]),
        symbol="BTC-USDT-SWAP",
    )
    p = asyncio.run(ev.check(ctx2))
    assert p is not None
    assert "BTC-USDT-SWAP" in p["symbols"]
    assert p["symbol"] == "BTC-USDT-SWAP"


def test_on_position_close_triggers_when_position_disappears():
    """持仓从 positions 列表中消失也触发平仓。"""
    ev = OnPositionClose(symbol="BTC-USDT-SWAP")
    ctx1 = make_ctx(
        client=FakeClient(positions=[{"instId": "BTC-USDT-SWAP", "pos": "1.5"}]),
        symbol="BTC-USDT-SWAP",
    )
    asyncio.run(ev.check(ctx1))
    # 持仓完全消失（不在列表中）
    ctx2 = make_ctx(
        client=FakeClient(positions=[]),
        symbol="BTC-USDT-SWAP",
    )
    p = asyncio.run(ev.check(ctx2))
    assert p is not None
    assert "BTC-USDT-SWAP" in p["symbols"]


def test_on_position_close_no_trigger_when_position_still_open():
    """持仓仍存在时不触发。"""
    ev = OnPositionClose(symbol="BTC-USDT-SWAP")
    ctx1 = make_ctx(
        client=FakeClient(positions=[{"instId": "BTC-USDT-SWAP", "pos": "1.5"}]),
        symbol="BTC-USDT-SWAP",
    )
    asyncio.run(ev.check(ctx1))
    ctx2 = make_ctx(
        client=FakeClient(positions=[{"instId": "BTC-USDT-SWAP", "pos": "1.0"}]),
        symbol="BTC-USDT-SWAP",
    )
    p = asyncio.run(ev.check(ctx2))
    assert p is None


def test_on_position_close_no_trigger_when_zero_to_zero():
    """持仓从零到零不触发。"""
    ev = OnPositionClose(symbol="BTC-USDT-SWAP")
    ctx1 = make_ctx(
        client=FakeClient(positions=[{"instId": "BTC-USDT-SWAP", "pos": "0"}]),
        symbol="BTC-USDT-SWAP",
    )
    asyncio.run(ev.check(ctx1))
    ctx2 = make_ctx(
        client=FakeClient(positions=[]),
        symbol="BTC-USDT-SWAP",
    )
    p = asyncio.run(ev.check(ctx2))
    assert p is None


def test_on_position_close_no_symbol_triggers_for_any_closed():
    """无 symbol 过滤时，任意 symbol 平仓都触发。"""
    ev = OnPositionClose()
    ctx1 = make_ctx(
        client=FakeClient(positions=[
            {"instId": "BTC-USDT-SWAP", "pos": "1.0"},
            {"instId": "ETH-USDT-SWAP", "pos": "2.0"},
        ]),
        symbol="",  # 显式无 symbol 过滤
    )
    asyncio.run(ev.check(ctx1))
    # ETH 平仓，BTC 仍持有
    ctx2 = make_ctx(
        client=FakeClient(positions=[{"instId": "BTC-USDT-SWAP", "pos": "1.0"}]),
        symbol="",
    )
    p = asyncio.run(ev.check(ctx2))
    assert p is not None
    assert "ETH-USDT-SWAP" in p["symbols"]


def test_on_position_close_uses_ctx_symbol_when_no_param():
    """无参数 symbol 时使用 ctx.symbol。"""
    ev = OnPositionClose()
    ctx1 = make_ctx(
        client=FakeClient(positions=[{"instId": "BTC-USDT-SWAP", "pos": "1.0"}]),
        symbol="BTC-USDT-SWAP",
    )
    asyncio.run(ev.check(ctx1))
    ctx2 = make_ctx(
        client=FakeClient(positions=[]),
        symbol="BTC-USDT-SWAP",
    )
    p = asyncio.run(ev.check(ctx2))
    assert p is not None
    assert "BTC-USDT-SWAP" in p["symbols"]


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
    """八个 P0 事件均注册到 event_registry。"""
    from dsl.registry import event_registry
    for kind in ("on_tick", "on_interval", "on_order_filled",
                 "on_margin_warning", "on_strategy_error",
                 "on_balance_change", "on_funding_rate", "on_position_close"):
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
