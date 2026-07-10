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
from dsl.compiler import Transition, FSMStateType, FSMCompiler
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


@pytest.mark.asyncio
async def test_enter_state_self_loop_skips_on_resume():
    """自环转换（RUNNING→RUNNING）不触发 on_resume（Task 3.3）。

    无 recover_when 的规则编译为 RUNNING→RUNNING 自环，每 tick 评估
    通过后 _enter_state("RUNNING") 不应重复调用 on_resume，避免
    on_resume → on_start 爆炸挂单。
    """
    strategy = _make_strategy()
    base_block = MagicMock()
    base_block.on_resume = AsyncMock()
    base_block.on_pause = AsyncMock()
    strategy._base_block = base_block
    # 模拟已在 RUNNING 状态（主循环启动时设置）
    strategy._current_state = "RUNNING"
    ctx = strategy._build_context()

    await strategy._enter_state("RUNNING", ctx)
    base_block.on_resume.assert_not_awaited()
    base_block.on_pause.assert_not_awaited()


@pytest.mark.asyncio
async def test_enter_state_state_change_triggers_on_resume():
    """状态实际变化（PAUSED→RUNNING）时 on_resume 正常触发（Task 3.1 回归）。"""
    strategy = _make_strategy()
    base_block = MagicMock()
    base_block.on_resume = AsyncMock()
    base_block.on_pause = AsyncMock()
    strategy._base_block = base_block
    strategy._current_state = "PAUSED_r1"  # 从 PAUSED 迁入 RUNNING
    ctx = strategy._build_context()

    await strategy._enter_state("RUNNING", ctx)
    base_block.on_resume.assert_awaited_once_with(ctx)
    base_block.on_pause.assert_not_awaited()
    assert strategy._current_state == "RUNNING"


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


# ============================================================
# 纯规则策略（base_strategy=None，Task 4.3）
# ============================================================


def _pure_rule_dsl_config() -> dict:
    """无 base_strategy 的纯规则策略配置（有 1 条规则）。"""
    return {
        "version": "1.0",
        "rules": [
            {
                "name": "定时记录",
                "when": {
                    "mode": "event",
                    "event": {"kind": "on_interval", "args": {"seconds": 60}},
                },
                "then": [{"kind": "log_event", "args": {"message": "tick"}}],
            }
        ],
    }


def test_get_symbol_fallback_without_base_strategy():
    """base_strategy=None 时 _get_symbol 从 self.params['symbol'] 回退。"""
    strategy = _make_strategy(_pure_rule_dsl_config())
    strategy._dsl = StrategyDSL.model_validate(_pure_rule_dsl_config())
    strategy.params["symbol"] = "ETH-USDT"
    assert strategy._get_symbol() == "ETH-USDT"


def test_get_symbol_empty_without_base_strategy():
    """base_strategy=None 且无 symbol 参数 → 返回空串（不报错）。"""
    strategy = _make_strategy(_pure_rule_dsl_config())
    strategy._dsl = StrategyDSL.model_validate(_pure_rule_dsl_config())
    # 没有 symbol 参数
    assert strategy._get_symbol() == ""


@pytest.mark.asyncio
async def test_execute_pure_rule_strategy_skips_base_block():
    """纯规则策略 execute() 不实例化基础策略，仅运行 FSM 循环。

    通过 mock _refresh_price / _check_risk_filters / _bind_events，
    并在第一次 tick 后强制 _running=False 退出主循环。
    验证 _base_block 保持 None，且不会调用 on_start / on_tick / on_stop。
    """
    from dsl.compiler import FSMCompiler
    from dsl.schema import StrategyDSL as _DSL

    strategy = _make_strategy(_pure_rule_dsl_config())
    strategy.client.get_ticker = MagicMock(return_value=[{"last": "45000"}])

    # 记录 _record_event 调用
    recorded: list[tuple] = []
    strategy._record_event = lambda *a, **k: recorded.append(a)

    # mock 风控检查返回 True（不触发）
    strategy._check_risk_filters = AsyncMock(return_value=True)

    # 让主循环在第一次 tick 后退出：patch transitions_from 返回空 + 设 _running=False
    original_build = strategy._build_context

    def _ctx_and_stop():
        ctx = original_build()
        strategy._running = False  # 退出主循环
        return ctx

    strategy._build_context = _ctx_and_stop

    await strategy.execute()

    # _base_block 应保持 None（未实例化）
    assert strategy._base_block is None
    # 应记录 started 事件（证明走到了主循环前）
    assert any(et == "started" for et, *_ in recorded)


@pytest.mark.asyncio
async def test_execute_pure_rule_strategy_runs_fsm_transitions():
    """纯规则策略 FSM 循环能评估 guard 并执行 actions（无基础策略）。"""
    strategy = _make_strategy(_pure_rule_dsl_config())
    strategy.client.get_ticker = MagicMock(return_value=[{"last": "45000"}])
    strategy._record_event = lambda *a, **k: None
    strategy._check_risk_filters = AsyncMock(return_value=True)

    # mock evaluate_condition / check_event 让 guard 通过
    action_executed: list[str] = []

    async def _fake_execute_action(ref, ctx):
        action_executed.append(ref.kind)

    with patch("dsl.executor.execute_action", new=_fake_execute_action), \
         patch("dsl.executor.check_event", new=AsyncMock(return_value={"ts": 1})):
        # 让第一次 tick 评估 guard 通过并执行 action，然后退出
        call_count = {"n": 0}
        original_build = strategy._build_context

        def _ctx_with_exit():
            ctx = original_build()
            call_count["n"] += 1
            if call_count["n"] >= 2:
                strategy._running = False
            return ctx

        strategy._build_context = _ctx_with_exit
        await strategy.execute()

    # 应执行了 log_event action
    assert "log_event" in action_executed
    assert strategy._base_block is None


# ============================================================
# 风控检查（Task 5.5）
# ============================================================

from dsl.schema import RiskFilter


def _make_strategy_with_risk(rf_kwargs: dict) -> ComposableStrategy:
    """构造带 RiskFilter 的 ComposableStrategy（mock 依赖）。"""
    strategy = _make_strategy()
    strategy._risk_filter = RiskFilter(**rf_kwargs)
    return strategy


@pytest.mark.asyncio
async def test_check_risk_filters_skipped_when_no_risk_filter():
    """risk_filter=None → _check_risk_filters 直接返回 True。"""
    strategy = _make_strategy()
    strategy._risk_filter = None
    ctx = strategy._build_context()
    assert await strategy._check_risk_filters(ctx) is True


@pytest.mark.asyncio
async def test_check_risk_filters_passes_when_all_clear():
    """risk_filter 有值但各项均未触发 → 返回 True。"""
    strategy = _make_strategy_with_risk({
        "daily_max_loss": 0.05,
        "stop_loss": 0.10,
        "take_profit": 0.20,
    })
    ctx = strategy._build_context()
    # mock 账户与持仓查询：无亏损、无持仓
    strategy.client.get_balance = AsyncMock(
        return_value={"data": [{"totalEq": "10000"}]}
    )
    strategy.client.get_positions = AsyncMock(return_value=[])
    strategy._realized_pnl = 0.0

    assert await strategy._check_risk_filters(ctx) is True


@pytest.mark.asyncio
async def test_daily_max_loss_triggers_risk_stop():
    """累计当日已实现亏损达 daily_max_loss 阈值 → 触发风控停止。"""
    from datetime import datetime, timezone
    strategy = _make_strategy_with_risk({"daily_max_loss": 0.05})
    strategy._record_event = MagicMock()
    strategy.order_manager.cancel_all = AsyncMock(return_value=3)

    ctx = strategy._build_context()
    ctx.symbol = "BTC-USDT"

    # mock 账户权益 10000，已实现亏损 600（6% > 5%）
    strategy.client.get_balance = AsyncMock(
        return_value={"data": [{"totalEq": "10000"}]}
    )
    strategy._realized_pnl = -600.0
    # 设为今日日期以避免 _get_daily_realized_pnl 重置基线
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    strategy._daily_reset_date = today
    strategy._daily_pnl_baseline = 0.0  # 当日基线为 0

    result = await strategy._check_risk_filters(ctx)

    assert result is False  # 风控触发
    assert strategy._running is False  # 策略已停止
    strategy.order_manager.cancel_all.assert_awaited_once_with("BTC-USDT")
    # 应记录 risk_triggered 事件
    recorded = [c for c in strategy._record_event.call_args_list
                if c.args[0] == "risk_triggered"]
    assert len(recorded) == 1
    assert "daily_max_loss" in recorded[0].args[1]


@pytest.mark.asyncio
async def test_daily_max_loss_not_triggered_below_threshold():
    """已实现亏损未达阈值 → 不触发。"""
    from datetime import datetime, timezone
    strategy = _make_strategy_with_risk({"daily_max_loss": 0.05})
    strategy.client.get_balance = AsyncMock(
        return_value={"data": [{"totalEq": "10000"}]}
    )
    strategy._realized_pnl = -300.0  # 3% < 5%
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    strategy._daily_reset_date = today
    strategy._daily_pnl_baseline = 0.0

    ctx = strategy._build_context()
    assert await strategy._check_risk_filters(ctx) is True


@pytest.mark.asyncio
async def test_stop_loss_triggers_risk_stop():
    """未实现亏损率达 stop_loss 阈值 → 触发风控停止。"""
    strategy = _make_strategy_with_risk({"stop_loss": 0.10})
    strategy._record_event = MagicMock()
    strategy.order_manager.cancel_all = AsyncMock(return_value=0)

    ctx = strategy._build_context()
    ctx.symbol = "BTC-USDT"

    # mock 持仓未实现盈亏率 -15%（<= -10%）
    strategy.client.get_positions = AsyncMock(return_value=[
        {"instId": "BTC-USDT", "uplRatio": "-0.15"}
    ])

    result = await strategy._check_risk_filters(ctx)

    assert result is False
    assert strategy._running is False
    recorded = [c for c in strategy._record_event.call_args_list
                if c.args[0] == "risk_triggered"]
    assert len(recorded) == 1
    assert "stop_loss" in recorded[0].args[1]


@pytest.mark.asyncio
async def test_take_profit_triggers_risk_stop():
    """未实现盈利率达 take_profit 阈值 → 触发风控停止。"""
    strategy = _make_strategy_with_risk({"take_profit": 0.20})
    strategy._record_event = MagicMock()
    strategy.order_manager.cancel_all = AsyncMock(return_value=0)

    ctx = strategy._build_context()
    ctx.symbol = "BTC-USDT"

    # mock 持仓未实现盈亏率 +25%（>= 20%）
    strategy.client.get_positions = AsyncMock(return_value=[
        {"instId": "BTC-USDT", "uplRatio": "0.25"}
    ])

    result = await strategy._check_risk_filters(ctx)

    assert result is False
    assert strategy._running is False
    recorded = [c for c in strategy._record_event.call_args_list
                if c.args[0] == "risk_triggered"]
    assert len(recorded) == 1
    assert "take_profit" in recorded[0].args[1]


@pytest.mark.asyncio
async def test_check_order_risk_skipped_when_no_risk_filter():
    """risk_filter=None → _check_order_risk 直接返回 True。"""
    strategy = _make_strategy()
    strategy._risk_filter = None
    ctx = strategy._build_context()
    action = ActionRef(kind="place_order", args={"qty": 0.001})
    assert await strategy._check_order_risk(ctx, action) is True


@pytest.mark.asyncio
async def test_min_trade_size_rejects_small_order():
    """订单量 < min_trade_size → 拒绝下单并记录。"""
    strategy = _make_strategy_with_risk({"min_trade_size": 0.01})
    strategy._record_event = MagicMock()

    ctx = strategy._build_context()
    action = ActionRef(kind="place_order", args={"qty": 0.001})

    result = await strategy._check_order_risk(ctx, action)

    assert result is False
    recorded = [c for c in strategy._record_event.call_args_list
                if c.args[0] == "risk_rejected"]
    assert len(recorded) == 1


@pytest.mark.asyncio
async def test_min_trade_size_allows_valid_order():
    """订单量 >= min_trade_size → 允许下单。"""
    strategy = _make_strategy_with_risk({"min_trade_size": 0.01})
    ctx = strategy._build_context()
    action = ActionRef(kind="place_order", args={"qty": 0.05})
    assert await strategy._check_order_risk(ctx, action) is True


@pytest.mark.asyncio
async def test_max_position_ratio_rejects_over_limit():
    """下单后持仓占比 > max_position_ratio → 拒绝下单。"""
    strategy = _make_strategy_with_risk({"max_position_ratio": 0.5})
    strategy._record_event = MagicMock()
    strategy.client.get_balance = AsyncMock(
        return_value={"data": [{"totalEq": "10000"}]}
    )
    strategy.client.get_positions = AsyncMock(return_value=[
        {"instId": "BTC-USDT", "pos": "0.3"}
    ])

    ctx = strategy._build_context()
    ctx.symbol = "BTC-USDT"
    ctx.current_price = 50000.0
    # 当前持仓价值 = 0.3 * 50000 = 15000；下单 0.05 * 50000 = 2500
    # 总计 17500 / 10000 = 1.75 > 0.5
    action = ActionRef(kind="place_order", args={"qty": 0.05})

    result = await strategy._check_order_risk(ctx, action)

    assert result is False
    recorded = [c for c in strategy._record_event.call_args_list
                if c.args[0] == "risk_rejected"]
    assert len(recorded) == 1


@pytest.mark.asyncio
async def test_max_position_ratio_allows_within_limit():
    """下单后持仓占比 <= max_position_ratio → 允许下单。"""
    strategy = _make_strategy_with_risk({"max_position_ratio": 0.5})
    strategy.client.get_balance = AsyncMock(
        return_value={"data": [{"totalEq": "100000"}]}
    )
    strategy.client.get_positions = AsyncMock(return_value=[
        {"instId": "BTC-USDT", "pos": "0.1"}
    ])

    ctx = strategy._build_context()
    ctx.symbol = "BTC-USDT"
    ctx.current_price = 50000.0
    # 当前持仓价值 = 0.1 * 50000 = 5000；下单 0.01 * 50000 = 500
    # 总计 5500 / 100000 = 0.055 <= 0.5
    action = ActionRef(kind="place_order", args={"qty": 0.01})

    result = await strategy._check_order_risk(ctx, action)

    assert result is True


@pytest.mark.asyncio
async def test_trigger_risk_stop_cancels_and_stops_and_logs():
    """_trigger_risk_stop 执行 close_all + stop_strategy + log_event。"""
    strategy = _make_strategy()
    strategy._record_event = MagicMock()
    strategy.order_manager.cancel_all = AsyncMock(return_value=5)
    strategy._running = True

    ctx = strategy._build_context()
    ctx.symbol = "BTC-USDT"

    await strategy._trigger_risk_stop(ctx, "test_reason", {"key": "val"})

    assert strategy._running is False
    strategy.order_manager.cancel_all.assert_awaited_once_with("BTC-USDT")
    recorded = [c for c in strategy._record_event.call_args_list
                if c.args[0] == "risk_triggered"]
    assert len(recorded) == 1
    assert "test_reason" in recorded[0].args[1]


@pytest.mark.asyncio
async def test_execute_actions_skips_place_order_rejected_by_risk():
    """place_order 被风控拒绝时 _execute_actions 跳过该动作，其他动作仍执行。"""
    strategy = _make_strategy_with_risk({"min_trade_size": 0.1})
    ctx = strategy._build_context()
    ctx.symbol = "BTC-USDT"

    actions = [
        ActionRef(kind="place_order", args={"qty": 0.001}),  # 会被拒绝
        ActionRef(kind="hold_position"),  # 应正常执行
    ]

    mock_exec = AsyncMock()
    with patch("dsl.executor.execute_action", new=mock_exec):
        await strategy._execute_actions(actions, ctx)

    # 只 hold_position 被执行，place_order 被跳过
    assert mock_exec.await_count == 1
    assert mock_exec.await_args_list[0].args[0].kind == "hold_position"


@pytest.mark.asyncio
async def test_get_daily_realized_pnl_resets_on_new_day():
    """_get_daily_realized_pnl 按 UTC 日期重置基线。"""
    strategy = _make_strategy()
    strategy._realized_pnl = 100.0
    strategy._daily_reset_date = "2020-01-01"  # 旧日期
    strategy._daily_pnl_baseline = 50.0

    # 调用后应重置基线为当前 _realized_pnl
    daily = strategy._get_daily_realized_pnl()
    # 基线被重置为 100，当日盈亏 = 100 - 100 = 0
    assert daily == 0.0
    assert strategy._daily_pnl_baseline == 100.0


# ============================================================
# on_order_filled 回调接通（Task 5.1）
# ============================================================


def test_bind_events_registers_on_order_filled_callback():
    """_bind_events 为 base_block 注册 OrderManager "filled" 回调（Task 5.1）。

    验证：当 _base_block 非 None 且有 on_order_filled 方法时，
    order_manager.on("filled", cb) 被调用注册回调。
    """
    from dsl.compiler import FSMCompiler

    strategy = _make_strategy()
    strategy._dsl = StrategyDSL.model_validate(_valid_dsl_config())
    strategy._fsm = FSMCompiler().compile(strategy._dsl)
    base_block = MagicMock()
    base_block.on_order_filled = AsyncMock()
    strategy._base_block = base_block

    # mock order_manager.on 记录回调注册
    registered_callbacks: dict[str, list] = {}
    strategy.order_manager.on = lambda event, cb: registered_callbacks.setdefault(event, []).append(cb)

    ctx = strategy._build_context()
    strategy._bind_events(ctx)

    assert "filled" in registered_callbacks
    assert len(registered_callbacks["filled"]) == 1
    # 注册的回调应是 strategy._on_order_filled_cb 绑定方法
    cb = registered_callbacks["filled"][0]
    assert callable(cb)


def test_bind_events_skips_on_order_filled_without_base_block():
    """_base_block 为 None 时不注册 on_order_filled 回调。"""
    from dsl.compiler import FSMCompiler

    strategy = _make_strategy()
    strategy._dsl = StrategyDSL.model_validate(_valid_dsl_config())
    strategy._fsm = FSMCompiler().compile(strategy._dsl)
    strategy._base_block = None  # 纯规则策略

    registered_callbacks: dict[str, list] = {}
    strategy.order_manager.on = lambda event, cb: registered_callbacks.setdefault(event, []).append(cb)

    ctx = strategy._build_context()
    strategy._bind_events(ctx)

    assert "filled" not in registered_callbacks


@pytest.mark.asyncio
async def test_on_order_filled_cb_forwards_to_base_block():
    """_on_order_filled_cb 转发订单给 base_block.on_order_filled（Task 5.1）。"""
    strategy = _make_strategy()
    base_block = MagicMock()
    base_block.on_order_filled = AsyncMock()
    strategy._base_block = base_block
    ctx = strategy._build_context()
    strategy._latest_ctx = ctx

    order = MagicMock()
    order.ordId = "test_oid"

    await strategy._on_order_filled_cb(order)

    base_block.on_order_filled.assert_awaited_once_with(order, ctx)


# ============================================================
# FSM 编译缓存（Task 6.3）
# ============================================================


@pytest.fixture()
def _clear_fsm_cache():
    """每个 FSM 缓存测试前后清空模块级 _fsm_cache，避免测试间污染。"""
    from dsl.executor import _fsm_cache

    _fsm_cache.clear()
    yield _fsm_cache
    _fsm_cache.clear()


def _make_cache_test_strategy(logic_hash: str | None = None) -> ComposableStrategy:
    """构造用于 FSM 缓存测试的策略（纯规则，无 base_strategy，便于 execute() 退出）。

    mock 掉 _refresh_price / _check_risk_filters / _build_context，使 execute()
    在第一次 tick 后立即退出主循环。
    """
    strategy = _make_strategy(_pure_rule_dsl_config())
    strategy.client.get_ticker = MagicMock(return_value=[{"last": "45000"}])
    strategy._record_event = lambda *a, **k: None
    strategy._check_risk_filters = AsyncMock(return_value=True)

    original_build = strategy._build_context

    def _ctx_and_stop():
        ctx = original_build()
        strategy._running = False  # 退出主循环
        return ctx

    strategy._build_context = _ctx_and_stop

    if logic_hash is not None:
        strategy.params["logic_hash"] = logic_hash
    return strategy


@pytest.mark.asyncio
async def test_fsm_cache_reuses_for_same_logic_hash(_clear_fsm_cache):
    """两个相同 logic_hash 的实例启动只触发 1 次 compile（Task 6.3）。

    验证：
    - 第一个实例 cache miss → compile 1 次，FSM 存入 _fsm_cache
    - 第二个实例 cache hit → 不 compile，复用同一 FSM 对象
    """
    from dsl.compiler import FSMCompiler as _RealCompiler

    compile_calls = {"n": 0}
    real_compile = _RealCompiler.compile

    def counting_compile(self_compiler, dsl):
        compile_calls["n"] += 1
        return real_compile(self_compiler, dsl)

    shared_hash = "shared-test-hash-6.3"
    s1 = _make_cache_test_strategy(logic_hash=shared_hash)
    s2 = _make_cache_test_strategy(logic_hash=shared_hash)

    with patch.object(FSMCompiler, "compile", counting_compile):
        await s1.execute()
        assert compile_calls["n"] == 1, "第一个实例应 cache miss 并 compile 1 次"
        await s2.execute()
        assert compile_calls["n"] == 1, "第二个实例应 cache hit，不触发 compile"

    # 两个实例复用同一个 FSM 对象
    assert s1._fsm is not None
    assert s2._fsm is not None
    assert s1._fsm is s2._fsm

    # 缓存中存在该 logic_hash
    assert shared_hash in _clear_fsm_cache


@pytest.mark.asyncio
async def test_fsm_cache_miss_for_different_logic_hash(_clear_fsm_cache):
    """两个不同 logic_hash 的实例各触发 1 次 compile（cache miss）。"""
    from dsl.compiler import FSMCompiler as _RealCompiler

    compile_calls = {"n": 0}
    real_compile = _RealCompiler.compile

    def counting_compile(self_compiler, dsl):
        compile_calls["n"] += 1
        return real_compile(self_compiler, dsl)

    s1 = _make_cache_test_strategy(logic_hash="hash-A")
    s2 = _make_cache_test_strategy(logic_hash="hash-B")

    with patch.object(FSMCompiler, "compile", counting_compile):
        await s1.execute()
        await s2.execute()

    assert compile_calls["n"] == 2, "不同 logic_hash 应各 compile 1 次"
    assert s1._fsm is not s2._fsm


@pytest.mark.asyncio
async def test_fsm_cache_computes_hash_when_missing(_clear_fsm_cache):
    """实例未携带 logic_hash 时现场计算并缓存（Task 6.2 回退路径）。

    两个相同配置、无 logic_hash 的实例：现场计算的 hash 相同 → 第二个复用缓存。
    """
    from dsl.compiler import FSMCompiler as _RealCompiler

    compile_calls = {"n": 0}
    real_compile = _RealCompiler.compile

    def counting_compile(self_compiler, dsl):
        compile_calls["n"] += 1
        return real_compile(self_compiler, dsl)

    # 都不带 logic_hash，但配置完全相同 → 现场计算的 hash 相同
    s1 = _make_cache_test_strategy(logic_hash=None)
    s2 = _make_cache_test_strategy(logic_hash=None)

    with patch.object(FSMCompiler, "compile", counting_compile):
        await s1.execute()
        assert compile_calls["n"] == 1
        await s2.execute()
        assert compile_calls["n"] == 1, "相同配置现场计算 hash 相同，应复用缓存"

    assert s1._fsm is s2._fsm
    # 缓存中应有 1 个条目（现场计算的 hash）
    assert len(_clear_fsm_cache) == 1


@pytest.mark.asyncio
async def test_fsm_cache_hit_does_not_call_compile(_clear_fsm_cache):
    """缓存命中时 FSMCompiler().compile 完全不被调用。"""
    from dsl.compiler import FSMCompiler as _RealCompiler

    # 预填充缓存
    pre_fsm = _RealCompiler().compile(_pure_rule_dsl_config())
    _clear_fsm_cache["precomputed-hash"] = pre_fsm

    mock_compile = MagicMock()
    with patch.object(FSMCompiler, "compile", mock_compile):
        s = _make_cache_test_strategy(logic_hash="precomputed-hash")
        await s.execute()

    mock_compile.assert_not_called()
    assert s._fsm is pre_fsm
