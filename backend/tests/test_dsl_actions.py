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


# —— stop_loss ——


@pytest.mark.asyncio
async def test_stop_loss_closes_long_position_when_below_threshold():
    """止损：多仓盈亏比例低于阈值时市价卖出平仓。"""
    ctx = _make_ctx(symbol="BTC-USDT-SWAP")
    ctx.client.get_positions = AsyncMock(return_value=[
        {"instId": "BTC-USDT-SWAP", "pos": "1.0", "uplRatio": "-0.08"},
    ])
    action_inst = dsl.blocks.actions.StopLoss(threshold=-0.05)
    await action_inst.execute(ctx)
    ctx.client.place_order.assert_awaited_once()
    call_args = ctx.client.place_order.call_args
    assert call_args.args[0] == "BTC-USDT-SWAP"
    assert call_args.args[1] == "sell"  # 多仓平仓 → 卖出
    assert call_args.args[2] == "market"
    assert call_args.args[3] == "1.0"
    details = ctx.strategy._record_event.call_args.args[2]
    assert details["upl_ratio"] == -0.08
    assert details["threshold"] == -0.05


@pytest.mark.asyncio
async def test_stop_loss_closes_short_position_when_below_threshold():
    """止损：空仓盈亏比例低于阈值时市价买入平仓。"""
    ctx = _make_ctx(symbol="BTC-USDT-SWAP")
    ctx.client.get_positions = AsyncMock(return_value=[
        {"instId": "BTC-USDT-SWAP", "pos": "-2.0", "uplRatio": "-0.10"},
    ])
    action_inst = dsl.blocks.actions.StopLoss(threshold=-0.05)
    await action_inst.execute(ctx)
    call_args = ctx.client.place_order.call_args
    assert call_args.args[1] == "buy"  # 空仓平仓 → 买入
    assert call_args.args[3] == "2.0"


@pytest.mark.asyncio
async def test_stop_loss_no_trigger_when_above_threshold():
    """止损：盈亏比例高于阈值时不平仓，仅记录 info 事件。"""
    ctx = _make_ctx(symbol="BTC-USDT-SWAP")
    ctx.client.get_positions = AsyncMock(return_value=[
        {"instId": "BTC-USDT-SWAP", "pos": "1.0", "uplRatio": "0.02"},
    ])
    action_inst = dsl.blocks.actions.StopLoss(threshold=-0.05)
    await action_inst.execute(ctx)
    ctx.client.place_order.assert_not_called()
    args = ctx.strategy._record_event.call_args
    assert args.args[0] == "dsl_info"
    assert "未触发" in args.args[1]


@pytest.mark.asyncio
async def test_stop_loss_skips_when_no_position():
    """止损：无持仓时跳过。"""
    ctx = _make_ctx(symbol="BTC-USDT-SWAP")
    ctx.client.get_positions = AsyncMock(return_value=[])
    action_inst = dsl.blocks.actions.StopLoss(threshold=-0.05)
    await action_inst.execute(ctx)
    ctx.client.place_order.assert_not_called()
    args = ctx.strategy._record_event.call_args
    assert args.args[0] == "dsl_info"
    assert "无持仓" in args.args[1]


# —— take_profit ——


@pytest.mark.asyncio
async def test_take_profit_closes_position_when_above_threshold():
    """止盈：盈亏比例高于阈值时全部平仓。"""
    ctx = _make_ctx(symbol="BTC-USDT-SWAP")
    ctx.client.get_positions = AsyncMock(return_value=[
        {"instId": "BTC-USDT-SWAP", "pos": "1.5", "uplRatio": "0.15"},
    ])
    action_inst = dsl.blocks.actions.TakeProfit(threshold=0.10)
    await action_inst.execute(ctx)
    ctx.client.place_order.assert_awaited_once()
    call_args = ctx.client.place_order.call_args
    assert call_args.args[1] == "sell"
    assert call_args.args[3] == "1.5"
    details = ctx.strategy._record_event.call_args.args[2]
    assert details["upl_ratio"] == 0.15
    assert details["threshold"] == 0.10


@pytest.mark.asyncio
async def test_take_profit_no_trigger_when_below_threshold():
    """止盈：盈亏比例低于阈值时不平仓。"""
    ctx = _make_ctx(symbol="BTC-USDT-SWAP")
    ctx.client.get_positions = AsyncMock(return_value=[
        {"instId": "BTC-USDT-SWAP", "pos": "1.0", "uplRatio": "0.05"},
    ])
    action_inst = dsl.blocks.actions.TakeProfit(threshold=0.10)
    await action_inst.execute(ctx)
    ctx.client.place_order.assert_not_called()
    args = ctx.strategy._record_event.call_args
    assert args.args[0] == "dsl_info"
    assert "未触发" in args.args[1]


@pytest.mark.asyncio
async def test_take_profit_skips_when_no_position():
    """止盈：无持仓时跳过。"""
    ctx = _make_ctx(symbol="BTC-USDT-SWAP")
    ctx.client.get_positions = AsyncMock(return_value=[])
    action_inst = dsl.blocks.actions.TakeProfit(threshold=0.10)
    await action_inst.execute(ctx)
    ctx.client.place_order.assert_not_called()
    args = ctx.strategy._record_event.call_args
    assert "无持仓" in args.args[1]


# —— set_var / get_var ——


@pytest.mark.asyncio
async def test_set_var_writes_to_kv_state():
    """set_var：写入 ctx.kv_state 并记录事件。"""
    ctx = _make_ctx()
    action_inst = dsl.blocks.actions.SetVar(name="my_var", value=42)
    await action_inst.execute(ctx)
    assert ctx.get_state("my_var") == 42
    args = ctx.strategy._record_event.call_args
    assert args.args[0] == "dsl_action"
    assert "my_var" in args.args[1]
    details = args.args[2]
    assert details["name"] == "my_var"
    assert details["value"] == 42


@pytest.mark.asyncio
async def test_set_var_supports_any_type():
    """set_var：支持任意类型的值。"""
    ctx = _make_ctx()
    # 字符串
    await dsl.blocks.actions.SetVar(name="s", value="hello").execute(ctx)
    assert ctx.get_state("s") == "hello"
    # 列表
    await dsl.blocks.actions.SetVar(name="lst", value=[1, 2, 3]).execute(ctx)
    assert ctx.get_state("lst") == [1, 2, 3]
    # 字典
    await dsl.blocks.actions.SetVar(name="d", value={"k": "v"}).execute(ctx)
    assert ctx.get_state("d") == {"k": "v"}


@pytest.mark.asyncio
async def test_get_var_returns_value():
    """get_var：返回已设置的变量值。"""
    ctx = _make_ctx()
    ctx.set_state("existing", "value123")
    action_inst = dsl.blocks.actions.GetVar(name="existing")
    result = await action_inst.execute(ctx)
    assert result == "value123"
    args = ctx.strategy._record_event.call_args
    assert args.args[0] == "dsl_action"
    assert "existing" in args.args[1]


@pytest.mark.asyncio
async def test_get_var_returns_default_when_missing():
    """get_var：变量不存在时返回默认值。"""
    ctx = _make_ctx()
    action_inst = dsl.blocks.actions.GetVar(name="missing", default="fallback")
    result = await action_inst.execute(ctx)
    assert result == "fallback"


@pytest.mark.asyncio
async def test_get_var_returns_none_when_missing_and_no_default():
    """get_var：变量不存在且无默认值时返回 None。"""
    ctx = _make_ctx()
    action_inst = dsl.blocks.actions.GetVar(name="missing")
    result = await action_inst.execute(ctx)
    assert result is None


@pytest.mark.asyncio
async def test_set_get_var_roundtrip():
    """set_var + get_var 端到端：写入后立即读取应一致。"""
    ctx = _make_ctx()
    await dsl.blocks.actions.SetVar(name="counter", value=99).execute(ctx)
    result = await dsl.blocks.actions.GetVar(name="counter").execute(ctx)
    assert result == 99


# —— P1 动作注册与元数据 ——


def test_all_p1_actions_registered():
    """测试所有 P1 动作均已注册。"""
    from dsl.registry import action_registry
    expected = {"stop_loss", "take_profit", "set_var", "get_var"}
    for kind in expected:
        assert action_registry.exists(kind), f"动作 {kind} 未注册"
        cls = action_registry.get(kind)
        assert cls.priority == "P1", f"{kind} priority 应为 P1"
        assert hasattr(cls, "category")
        assert hasattr(cls, "description")
        assert hasattr(cls, "param_schema")


def test_p1_action_metadata_categories():
    """P1 动作分类正确。"""
    from dsl.registry import action_registry
    assert action_registry.get("stop_loss").category == "风控"
    assert action_registry.get("stop_loss").label == "止损"
    assert action_registry.get("take_profit").category == "风控"
    assert action_registry.get("take_profit").label == "止盈"
    assert action_registry.get("set_var").category == "状态管理"
    assert action_registry.get("set_var").label == "设置变量"
    assert action_registry.get("get_var").category == "状态管理"
    assert action_registry.get("get_var").label == "获取变量"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
