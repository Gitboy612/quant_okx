"""ComposableStrategy 执行器测试（Task 11）。

执行器涉及 OKX API 与主循环，测试采用 **mock 策略**：

- 用 ``MagicMock`` / ``AsyncMock`` 替换 OKXClient、OrderManager、db_session_factory
- 用 ``unittest.mock.patch`` 替换 ``dsl.executor.evaluate_condition`` /
  ``check_event`` / ``execute_action``（按名导入到 executor 命名空间，故 patch
  ``dsl.executor.<name>``）
- 手动设置 ``self._dsl`` / ``self._fsm`` / ``self._rule_map`` / ``self._base_block``
  等实例属性，不调用 ``execute()`` 完整主循环（会死循环）
- 单独测试各内部方法：validate_params / _build_context / _evaluate_guard /
  _execute_actions / _enter_state / _is_in_cooldown

导入风格参考 test_dsl_compiler.py：sys.path 注入 backend 根目录后用
``from dsl.xxx import``。
"""
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from dsl.executor import ComposableStrategy
from dsl.schema import (
    StrategyDSL,
    Rule,
    Trigger,
    ConditionRef,
    EventRef,
    ActionRef,
)
from dsl.compiler import Transition, FSMStateType
from dsl.context import ExecutionContext


# ============================================================
# 辅助构造
# ============================================================


def _base_grid() -> dict:
    """用户示例的基础网格策略配置。"""
    return {
        "kind": "grid",
        "params": {
            "upper_price": 50000,
            "lower_price": 40000,
            "grid_count": 10,
            "order_qty": 0.01,
            "symbol": "BTC-USDT",
        },
    }


def _price_change_indicator(window: str = "1h", symbol: str = "BTC-USDT") -> dict:
    return {"kind": "price_change_pct", "args": {"window": window, "symbol": symbol}}


def _gt(indicator: dict, threshold: float) -> dict:
    return {"kind": "gt", "args": {"indicator": indicator, "threshold": threshold}}


def _abs_lt(indicator: dict, threshold: float) -> dict:
    return {"kind": "abs_lt", "args": {"indicator": indicator, "threshold": threshold}}


def _valid_dsl_config() -> dict:
    """用户示例「单边上涨暂停」配置：condition-trigger + recover_when，合法。"""
    return {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "单边上涨暂停",
                "when": {
                    "mode": "condition",
                    "condition": _gt(_price_change_indicator("1h"), 0.05),
                },
                "then": [
                    {"kind": "pause_orders"},
                    {"kind": "hold_position"},
                    {"kind": "log_event", "args": {"level": "warn", "message": "单边上涨暂停"}},
                ],
                "recover_when": {
                    "mode": "condition",
                    "condition": _abs_lt(_price_change_indicator("1h"), 0.05),
                },
                "recover_then": [
                    {"kind": "rebalance_position", "args": {"mode": "to_theoretical"}},
                    {"kind": "resume_orders"},
                ],
                "cool_down_seconds": 60,
            }
        ],
    }


def _make_strategy(config: dict | None = None) -> ComposableStrategy:
    """构造一个带 mock 依赖的 ComposableStrategy，不进入主循环。

    client / order_manager / db_session_factory 均为 MagicMock；_record_event
    内部 try/except 吞掉所有异常，故 db_session_factory 用 MagicMock 即可。
    """
    cfg = config if config is not None else _valid_dsl_config()
    client = MagicMock()
    order_manager = MagicMock()
    db_session_factory = MagicMock()
    strategy = ComposableStrategy(
        instance_id=1,
        params={"dsl_config": cfg, "tick_interval": 3},
        client=client,
        db_session_factory=db_session_factory,
        account_id=1,
        order_manager=order_manager,
    )
    return strategy


def _make_transition(
    guard_kind: str = "condition",
    rule_name: str = "rule1",
    from_state: str = "RUNNING",
    to_state: str = "PAUSED_rule1",
    condition: ConditionRef | None = None,
    event: EventRef | None = None,
    extra_condition: ConditionRef | None = None,
    actions: list[ActionRef] | None = None,
) -> Transition:
    """构造一个 Transition（测试用，不经过编译器）。"""
    trigger = Trigger(
        mode=guard_kind if guard_kind in ("condition", "event") else "condition",
        condition=condition,
        event=event,
        extra_condition=extra_condition,
    )
    return Transition(
        from_state=from_state,
        to_state=to_state,
        trigger=trigger,
        guard_kind=guard_kind,
        actions=actions or [],
        rule_name=rule_name,
    )


# ============================================================
# validate_params
# ============================================================


@pytest.mark.asyncio
async def test_validate_params_valid():
    """合法 dsl_config → validate_params 返回 True。"""
    strategy = _make_strategy()
    assert await strategy.validate_params() is True


@pytest.mark.asyncio
async def test_validate_params_invalid():
    """非法 dsl_config（then 为空）→ validate_params 返回 False。"""
    bad_config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "空then",
                "when": {
                    "mode": "condition",
                    "condition": _gt(_price_change_indicator("1h"), 0.05),
                },
                "then": [],  # 语义错误：EMPTY_THEN
            }
        ],
    }
    strategy = _make_strategy(bad_config)
    assert await strategy.validate_params() is False


@pytest.mark.asyncio
async def test_validate_params_missing_dsl_config():
    """params 中缺少 dsl_config → validate_params 返回 False。"""
    strategy = _make_strategy()
    strategy.params = {"tick_interval": 3}  # 无 dsl_config
    assert await strategy.validate_params() is False


# ============================================================
# _build_context
# ============================================================


def test_build_context():
    """_build_context 返回的 ctx 含正确的 symbol/client/order_manager，
    indicator_cache 为空 dict，base_strategy 默认为 None。"""
    strategy = _make_strategy()
    ctx = strategy._build_context()
    assert isinstance(ctx, ExecutionContext)
    assert ctx.symbol == "BTC-USDT"
    assert ctx.client is strategy.client
    assert ctx.order_manager is strategy.order_manager
    assert ctx.indicator_cache == {}
    assert ctx.kv_state is strategy._kv_state  # 跨 tick 持久引用
    assert ctx.active_rules is strategy._active_rules
    assert ctx.strategy is strategy
    assert ctx.instance_id == 1


# ============================================================
# _evaluate_guard: condition
# ============================================================


@pytest.mark.asyncio
async def test_evaluate_guard_condition_passes():
    """guard_kind='condition'，mock evaluate_condition 返回 True → guard 通过。"""
    strategy = _make_strategy()
    cond_ref = ConditionRef(
        kind="gt",
        args={"indicator": _price_change_indicator("1h"), "threshold": 0.05},
    )
    transition = _make_transition(
        guard_kind="condition", condition=cond_ref, rule_name="r1"
    )
    ctx = strategy._build_context()

    with patch("dsl.executor.evaluate_condition", new=AsyncMock(return_value=True)):
        result = await strategy._evaluate_guard(transition, ctx)
    assert result is True


@pytest.mark.asyncio
async def test_evaluate_guard_condition_fails():
    """guard_kind='condition'，mock evaluate_condition 返回 False → guard 不通过。"""
    strategy = _make_strategy()
    cond_ref = ConditionRef(
        kind="gt",
        args={"indicator": _price_change_indicator("1h"), "threshold": 0.05},
    )
    transition = _make_transition(
        guard_kind="condition", condition=cond_ref, rule_name="r1"
    )
    ctx = strategy._build_context()

    with patch("dsl.executor.evaluate_condition", new=AsyncMock(return_value=False)):
        result = await strategy._evaluate_guard(transition, ctx)
    assert result is False


# ============================================================
# _evaluate_guard: always
# ============================================================


@pytest.mark.asyncio
async def test_evaluate_guard_always():
    """guard_kind='always' → 总是 True，不调用任何积木函数。"""
    strategy = _make_strategy()
    transition = _make_transition(guard_kind="always", rule_name="r1")
    ctx = strategy._build_context()

    # 即便 patch 为返回 False，always 也不应调用 evaluate_condition
    with patch("dsl.executor.evaluate_condition", new=AsyncMock(return_value=False)):
        result = await strategy._evaluate_guard(transition, ctx)
    assert result is True


# ============================================================
# _evaluate_guard: event
# ============================================================


@pytest.mark.asyncio
async def test_evaluate_guard_event_fires():
    """guard_kind='event'，mock check_event 返回 dict → 通过。

    _event_instances 为空（未调用 _bind_events），故走 check_event 回退路径。
    """
    strategy = _make_strategy()
    event_ref = EventRef(kind="on_tick", args={"symbol": "BTC-USDT"})
    transition = _make_transition(
        guard_kind="event", event=event_ref, rule_name="r1"
    )
    ctx = strategy._build_context()

    with patch("dsl.executor.check_event", new=AsyncMock(return_value={"ts": 1.0})):
        result = await strategy._evaluate_guard(transition, ctx)
    assert result is True


@pytest.mark.asyncio
async def test_evaluate_guard_event_no_fire():
    """guard_kind='event'，mock check_event 返回 None → 不通过。"""
    strategy = _make_strategy()
    event_ref = EventRef(kind="on_tick", args={"symbol": "BTC-USDT"})
    transition = _make_transition(
        guard_kind="event", event=event_ref, rule_name="r1"
    )
    ctx = strategy._build_context()

    with patch("dsl.executor.check_event", new=AsyncMock(return_value=None)):
        result = await strategy._evaluate_guard(transition, ctx)
    assert result is False


@pytest.mark.asyncio
async def test_evaluate_guard_event_uses_cached_instance():
    """guard_kind='event'，缓存的事件实例 check 返回 dict → 通过（不走 check_event）。"""
    strategy = _make_strategy()
    event_ref = EventRef(kind="on_tick", args={"symbol": "BTC-USDT"})
    transition = _make_transition(
        guard_kind="event", event=event_ref, rule_name="r1"
    )
    ctx = strategy._build_context()

    cached_inst = MagicMock()
    cached_inst.check = AsyncMock(return_value={"ts": 99.0})
    strategy._event_instances["r1"] = cached_inst

    # check_event 不应被调用（缓存命中）
    with patch("dsl.executor.check_event", new=AsyncMock(return_value=None)):
        result = await strategy._evaluate_guard(transition, ctx)
    assert result is True
    cached_inst.check.assert_awaited_once_with(ctx)


# ============================================================
# _evaluate_guard: extra_condition
# ============================================================


@pytest.mark.asyncio
async def test_evaluate_guard_extra_condition_blocks():
    """guard 通过但 extra_condition 为 False → 整体不通过。"""
    strategy = _make_strategy()
    cond_ref = ConditionRef(
        kind="gt",
        args={"indicator": _price_change_indicator("1h"), "threshold": 0.05},
    )
    extra_ref = ConditionRef(
        kind="lt",
        args={"indicator": _price_change_indicator("1h"), "threshold": 0.1},
    )
    transition = _make_transition(
        guard_kind="condition",
        condition=cond_ref,
        extra_condition=extra_ref,
        rule_name="r1",
    )
    ctx = strategy._build_context()

    # 主 guard True，extra_condition False
    async def fake_eval(ref, ctx):
        if ref is extra_ref:
            return False
        return True

    with patch("dsl.executor.evaluate_condition", new=AsyncMock(side_effect=fake_eval)):
        result = await strategy._evaluate_guard(transition, ctx)
    assert result is False


# ============================================================
# _execute_actions
# ============================================================


@pytest.mark.asyncio
async def test_execute_actions_calls_execute_action():
    """mock execute_action，验证每个 ActionRef 都被调用一次，顺序保持。"""
    strategy = _make_strategy()
    actions = [
        ActionRef(kind="pause_orders"),
        ActionRef(kind="hold_position"),
        ActionRef(kind="log_event", args={"level": "warn", "message": "m"}),
    ]
    ctx = strategy._build_context()

    mock_exec = AsyncMock()
    with patch("dsl.executor.execute_action", new=mock_exec):
        await strategy._execute_actions(actions, ctx)

    assert mock_exec.await_count == 3
    # 验证调用顺序与参数
    called_refs = [call.args[0] for call in mock_exec.await_args_list]
    assert called_refs == actions
    # 每个 await 的第二个参数都是 ctx
    for call in mock_exec.await_args_list:
        assert call.args[1] is ctx


@pytest.mark.asyncio
async def test_execute_actions_empty_list():
    """空动作列表 → execute_action 不被调用，无异常。"""
    strategy = _make_strategy()
    ctx = strategy._build_context()

    mock_exec = AsyncMock()
    with patch("dsl.executor.execute_action", new=mock_exec):
        await strategy._execute_actions([], ctx)
    mock_exec.assert_not_awaited()


# ============================================================
# _enter_state
# ============================================================


@pytest.mark.asyncio
async def test_enter_state_running_calls_on_resume():
    """进入 RUNNING → base_block.on_resume 被调用。"""
    strategy = _make_strategy()
    base_block = MagicMock()
    base_block.on_resume = AsyncMock()
    base_block.on_pause = AsyncMock()
    strategy._base_block = base_block
    ctx = strategy._build_context()

    await strategy._enter_state("RUNNING", ctx)
    base_block.on_resume.assert_awaited_once_with(ctx)
    base_block.on_pause.assert_not_awaited()


@pytest.mark.asyncio
async def test_enter_state_paused_calls_on_pause():
    """进入 PAUSED_<rule> → base_block.on_pause 被调用。"""
    strategy = _make_strategy()
    base_block = MagicMock()
    base_block.on_pause = AsyncMock()
    base_block.on_resume = AsyncMock()
    strategy._base_block = base_block
    ctx = strategy._build_context()

    await strategy._enter_state("PAUSED_单边上涨暂停", ctx)
    base_block.on_pause.assert_awaited_once_with(ctx)
    base_block.on_resume.assert_not_awaited()


@pytest.mark.asyncio
async def test_enter_state_rebalancing_no_hook():
    """进入 REBALANCING_<rule> → on_pause / on_resume 均不被调用。"""
    strategy = _make_strategy()
    base_block = MagicMock()
    base_block.on_pause = AsyncMock()
    base_block.on_resume = AsyncMock()
    strategy._base_block = base_block
    ctx = strategy._build_context()

    await strategy._enter_state("REBALANCING_单边上涨暂停", ctx)
    base_block.on_pause.assert_not_awaited()
    base_block.on_resume.assert_not_awaited()


# ============================================================
# _is_in_cooldown
# ============================================================


def test_cool_down_prevents_retrigger():
    """同一规则在冷却期内不重复触发（_is_in_cooldown 返回 True）。"""
    strategy = _make_strategy()
    # 构造 rule_name -> Rule 映射，cool_down_seconds=60
    rule = Rule(
        name="r1",
        when=Trigger(mode="condition", condition=ConditionRef(
            kind="gt", args={"indicator": _price_change_indicator("1h"), "threshold": 0.05}
        )),
        cool_down_seconds=60,
    )
    strategy._rule_map = {"r1": rule}
    strategy._last_triggered = {"r1": 1000.0}

    transition = _make_transition(guard_kind="condition", rule_name="r1")
    ctx = ExecutionContext(client=MagicMock(), order_manager=MagicMock(),
                           symbol="BTC-USDT", tick_ts=1010.0)  # 仅过 10 秒 < 60

    assert strategy._is_in_cooldown(transition, ctx) is True


def test_cool_down_expired_allows_trigger():
    """冷却期已过 → _is_in_cooldown 返回 False。"""
    strategy = _make_strategy()
    rule = Rule(
        name="r1",
        when=Trigger(mode="condition", condition=ConditionRef(
            kind="gt", args={"indicator": _price_change_indicator("1h"), "threshold": 0.05}
        )),
        cool_down_seconds=60,
    )
    strategy._rule_map = {"r1": rule}
    strategy._last_triggered = {"r1": 1000.0}

    transition = _make_transition(guard_kind="condition", rule_name="r1")
    ctx = ExecutionContext(client=MagicMock(), order_manager=MagicMock(),
                           symbol="BTC-USDT", tick_ts=1070.0)  # 过 70 秒 > 60

    assert strategy._is_in_cooldown(transition, ctx) is False


def test_cool_down_zero_disables_cooldown():
    """cool_down_seconds=0 → 永不冷却（_is_in_cooldown 返回 False）。"""
    strategy = _make_strategy()
    rule = Rule(
        name="r1",
        when=Trigger(mode="condition", condition=ConditionRef(
            kind="gt", args={"indicator": _price_change_indicator("1h"), "threshold": 0.05}
        )),
        cool_down_seconds=0,
    )
    strategy._rule_map = {"r1": rule}
    strategy._last_triggered = {"r1": 1000.0}

    transition = _make_transition(guard_kind="condition", rule_name="r1")
    ctx = ExecutionContext(client=MagicMock(), order_manager=MagicMock(),
                           symbol="BTC-USDT", tick_ts=1001.0)

    assert strategy._is_in_cooldown(transition, ctx) is False


def test_cool_down_no_prior_trigger():
    """从未触发过 → 不在冷却期（_is_in_cooldown 返回 False）。"""
    strategy = _make_strategy()
    rule = Rule(
        name="r1",
        when=Trigger(mode="condition", condition=ConditionRef(
            kind="gt", args={"indicator": _price_change_indicator("1h"), "threshold": 0.05}
        )),
        cool_down_seconds=60,
    )
    strategy._rule_map = {"r1": rule}
    strategy._last_triggered = {}  # 未触发过

    transition = _make_transition(guard_kind="condition", rule_name="r1")
    ctx = ExecutionContext(client=MagicMock(), order_manager=MagicMock(),
                           symbol="BTC-USDT", tick_ts=1000.0)

    assert strategy._is_in_cooldown(transition, ctx) is False


# ============================================================
# _resolve_state_type（_enter_state 的依赖，额外覆盖）
# ============================================================


def test_resolve_state_type_via_fsm():
    """通过真实编译的 FSM 查询状态类型。"""
    from dsl.compiler import FSMCompiler

    strategy = _make_strategy()
    strategy._dsl = StrategyDSL.model_validate(_valid_dsl_config())
    strategy._fsm = FSMCompiler().compile(strategy._dsl)

    assert strategy._resolve_state_type("RUNNING") == FSMStateType.RUNNING
    assert strategy._resolve_state_type("PAUSED_单边上涨暂停") == FSMStateType.PAUSED
    assert strategy._resolve_state_type("REBALANCING_单边上涨暂停") == FSMStateType.REBALANCING


def test_resolve_state_type_fallback_without_fsm():
    """FSM 未设置时按名称前缀推断。"""
    strategy = _make_strategy()
    strategy._fsm = None
    assert strategy._resolve_state_type("RUNNING") == FSMStateType.RUNNING
    assert strategy._resolve_state_type("PAUSED_x") == FSMStateType.PAUSED
    assert strategy._resolve_state_type("REBALANCING_x") == FSMStateType.REBALANCING
    assert strategy._resolve_state_type("UNKNOWN") is None
