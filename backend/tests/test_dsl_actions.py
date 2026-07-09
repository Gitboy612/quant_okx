"""DSL P0 动作库测试。

用 AsyncMock 构造 ctx 各依赖，验证动作行为。
导入风格参考 test_dsl_schema.py：sys.path 注入 backend 根目录后用 ``from dsl.xxx import``。
"""
import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入动作模块（触发 @action 装饰器注册）
import dsl.blocks.actions  # noqa: F401
from dsl.context import ExecutionContext
from dsl.schema import ActionRef
from dsl.blocks.actions import execute_action


def _make_ctx(symbol: str = "BTC-USDT-SWAP") -> ExecutionContext:
    """构造一个带 mock 依赖的 ExecutionContext。"""
    ctx = ExecutionContext(
        client=MagicMock(),
        order_manager=MagicMock(),
        base_strategy=MagicMock(),
        strategy=MagicMock(),
        symbol=symbol,
    )
    # 异步方法用 AsyncMock
    ctx.client.place_order = AsyncMock(return_value={"code": "0", "data": [{"ordId": "x"}]})
    ctx.client.cancel_order = AsyncMock(return_value={"code": "0"})
    ctx.client.get_positions = AsyncMock(return_value=[])
    ctx.order_manager.cancel_all = AsyncMock(return_value=0)
    ctx.base_strategy.on_pause = AsyncMock()
    ctx.base_strategy.on_resume = AsyncMock()
    ctx.base_strategy.get_theoretical_position = MagicMock(return_value=0.0)
    # _record_event 是同步方法
    ctx.strategy._record_event = MagicMock()
    return ctx


# —— pause_orders ——


@pytest.mark.asyncio
async def test_pause_orders_calls_on_pause_and_records_event():
    ctx = _make_ctx()
    action_inst = dsl.blocks.actions.PauseOrders()
    await action_inst.execute(ctx)
    ctx.base_strategy.on_pause.assert_awaited_once_with(ctx)
    ctx.strategy._record_event.assert_called_once()
    args = ctx.strategy._record_event.call_args
    assert args.args[0] == "dsl_action"
    assert "pause_orders" in args.args[1]


@pytest.mark.asyncio
async def test_pause_orders_fallback_to_cancel_all_when_no_base_strategy():
    ctx = _make_ctx()
    ctx.base_strategy = None
    action_inst = dsl.blocks.actions.PauseOrders()
    await action_inst.execute(ctx)
    ctx.order_manager.cancel_all.assert_awaited_once_with(ctx.symbol)
    ctx.strategy._record_event.assert_called_once()


@pytest.mark.asyncio
async def test_pause_orders_uses_ctx_symbol_when_none():
    ctx = _make_ctx(symbol="ETH-USDT-SWAP")
    action_inst = dsl.blocks.actions.PauseOrders(symbol=None)
    await action_inst.execute(ctx)
    ctx.base_strategy.on_pause.assert_awaited_once()
    assert "ETH-USDT-SWAP" in ctx.strategy._record_event.call_args.args[1]


# —— resume_orders ——


@pytest.mark.asyncio
async def test_resume_orders_calls_on_resume():
    ctx = _make_ctx()
    action_inst = dsl.blocks.actions.ResumeOrders()
    await action_inst.execute(ctx)
    ctx.base_strategy.on_resume.assert_awaited_once_with(ctx)
    ctx.strategy._record_event.assert_called_once()
    assert "resume_orders" in ctx.strategy._record_event.call_args.args[1]


# —— hold_position ——


@pytest.mark.asyncio
async def test_hold_position_only_records_event():
    ctx = _make_ctx()
    action_inst = dsl.blocks.actions.HoldPosition()
    await action_inst.execute(ctx)
    # 仅调用 _record_event，不触碰 client / order_manager / base_strategy
    ctx.strategy._record_event.assert_called_once_with(
        "dsl_action", "hold_position: 保持当前持仓"
    )
    ctx.client.place_order.assert_not_called()
    ctx.order_manager.cancel_all.assert_not_called()
    ctx.base_strategy.on_pause.assert_not_called()


# —— rebalance_position ——


@pytest.mark.asyncio
async def test_rebalance_position_to_theoretical_buys_when_actual_below():
    ctx = _make_ctx(symbol="BTC-USDT-SWAP")
    ctx.base_strategy.get_theoretical_position = MagicMock(return_value=1.0)
    ctx.client.get_positions = AsyncMock(return_value=[
        {"instId": "BTC-USDT-SWAP", "pos": "0.5"},
    ])
    action_inst = dsl.blocks.actions.RebalancePosition()
    await action_inst.execute(ctx)
    # delta = 1.0 - 0.5 = 0.5 > 0 => 买入 0.5
    ctx.client.place_order.assert_awaited_once()
    call_args = ctx.client.place_order.call_args
    assert call_args.args[0] == "BTC-USDT-SWAP"
    assert call_args.args[1] == "buy"
    assert call_args.args[2] == "market"
    assert call_args.args[3] == "0.5"
    # 记录事件含 delta/theoretical/actual
    details = ctx.strategy._record_event.call_args.args[2]
    assert details["theoretical"] == 1.0
    assert details["actual"] == 0.5
    assert details["delta"] == 0.5


@pytest.mark.asyncio
async def test_rebalance_position_sells_when_actual_above():
    ctx = _make_ctx()
    ctx.base_strategy.get_theoretical_position = MagicMock(return_value=0.3)
    ctx.client.get_positions = AsyncMock(return_value=[
        {"instId": ctx.symbol, "pos": "1.0"},
    ])
    action_inst = dsl.blocks.actions.RebalancePosition()
    await action_inst.execute(ctx)
    # delta = 0.3 - 1.0 = -0.7 => 卖出 0.7
    call_args = ctx.client.place_order.call_args
    assert call_args.args[1] == "sell"
    assert call_args.args[3] == "0.7"


@pytest.mark.asyncio
async def test_rebalance_position_no_trade_when_balanced():
    ctx = _make_ctx()
    ctx.base_strategy.get_theoretical_position = MagicMock(return_value=1.0)
    ctx.client.get_positions = AsyncMock(return_value=[
        {"instId": ctx.symbol, "pos": "1.0"},
    ])
    action_inst = dsl.blocks.actions.RebalancePosition()
    await action_inst.execute(ctx)
    ctx.client.place_order.assert_not_called()
    ctx.strategy._record_event.assert_called_once()


@pytest.mark.asyncio
async def test_rebalance_position_skips_when_no_theoretical_method():
    ctx = _make_ctx()
    # 移除 get_theoretical_position 属性
    del ctx.base_strategy.get_theoretical_position
    action_inst = dsl.blocks.actions.RebalancePosition()
    await action_inst.execute(ctx)
    ctx.client.place_order.assert_not_called()
    # 记录警告事件
    args = ctx.strategy._record_event.call_args
    assert args.args[0] == "dsl_warn"


# —— place_order ——


@pytest.mark.asyncio
async def test_place_order_market_calls_client_correctly():
    ctx = _make_ctx()
    action_inst = dsl.blocks.actions.PlaceOrder(
        symbol="BTC-USDT-SWAP", side="buy", type="market", qty=0.5
    )
    await action_inst.execute(ctx)
    ctx.client.place_order.assert_awaited_once_with(
        "BTC-USDT-SWAP", "buy", "market", "0.5", px=None
    )
    ctx.strategy._record_event.assert_called_once()


@pytest.mark.asyncio
async def test_place_order_limit_passes_price():
    ctx = _make_ctx()
    action_inst = dsl.blocks.actions.PlaceOrder(
        symbol="BTC-USDT-SWAP", side="sell", type="limit", qty=1.5, price=100000
    )
    await action_inst.execute(ctx)
    ctx.client.place_order.assert_awaited_once_with(
        "BTC-USDT-SWAP", "sell", "limit", "1.5", px="100000"
    )


# —— cancel_all ——


@pytest.mark.asyncio
async def test_cancel_all_calls_order_manager():
    ctx = _make_ctx()
    ctx.order_manager.cancel_all = AsyncMock(return_value=3)
    action_inst = dsl.blocks.actions.CancelAll()
    await action_inst.execute(ctx)
    ctx.order_manager.cancel_all.assert_awaited_once_with(ctx.symbol)
    details = ctx.strategy._record_event.call_args.args[2]
    assert details["cancelled"] == 3


# —— log_event ——


@pytest.mark.asyncio
async def test_log_event_info_level():
    ctx = _make_ctx()
    action_inst = dsl.blocks.actions.LogEvent(level="info", message="hello", details={"k": "v"})
    await action_inst.execute(ctx)
    ctx.strategy._record_event.assert_called_once_with("dsl_info", "hello", {"k": "v"})


@pytest.mark.asyncio
async def test_log_event_warn_level():
    ctx = _make_ctx()
    action_inst = dsl.blocks.actions.LogEvent(level="warn", message="小心")
    await action_inst.execute(ctx)
    args = ctx.strategy._record_event.call_args
    assert args.args[0] == "dsl_warn"
    assert "小心" in args.args[1]


@pytest.mark.asyncio
async def test_log_event_error_and_critical_levels():
    ctx = _make_ctx()
    for level, expected in [("error", "dsl_error"), ("critical", "dsl_critical")]:
        ctx.strategy._record_event.reset_mock()
        action_inst = dsl.blocks.actions.LogEvent(level=level, message="m")
        await action_inst.execute(ctx)
        assert ctx.strategy._record_event.call_args.args[0] == expected


# —— execute_action 便捷函数 ——


@pytest.mark.asyncio
async def test_execute_action_dispatches_registered_kind():
    ctx = _make_ctx()
    ref = ActionRef(kind="hold_position", args={})
    await execute_action(ref, ctx)
    ctx.strategy._record_event.assert_called_once()


@pytest.mark.asyncio
async def test_execute_action_unknown_kind_raises():
    ctx = _make_ctx()
    ref = ActionRef(kind="nonexistent_kind", args={})
    with pytest.raises(ValueError, match="未知动作 kind"):
        await execute_action(ref, ctx)


# —— 注册表完整性 ——


def test_all_p0_actions_registered():
    from dsl.registry import action_registry
    expected = {
        "pause_orders", "resume_orders", "hold_position",
        "rebalance_position", "place_order", "cancel_all", "log_event",
    }
    for kind in expected:
        assert action_registry.exists(kind), f"动作 {kind} 未注册"
        cls = action_registry.get(kind)
        # 每个动作类都有元数据
        assert hasattr(cls, "category")
        assert hasattr(cls, "description")
        assert hasattr(cls, "param_schema")
        assert hasattr(cls, "priority")
        assert cls.priority == "P0"


def test_action_metadata_categories():
    from dsl.registry import action_registry
    assert action_registry.get("pause_orders").category == "策略控制"
    assert action_registry.get("resume_orders").category == "策略控制"
    assert action_registry.get("hold_position").category == "策略控制"
    assert action_registry.get("rebalance_position").category == "持仓"
    assert action_registry.get("place_order").category == "订单"
    assert action_registry.get("cancel_all").category == "订单"
    assert action_registry.get("log_event").category == "通知"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
