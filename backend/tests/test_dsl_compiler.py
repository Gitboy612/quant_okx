"""FSM 编译器测试。

覆盖 spec.md「Requirement: 状态机执行模型」的编译产物：

- 编译正确性：最小配置 / 触发-恢复对 / 一次性触发 / 多规则 /
  guard_kind 判定 / is_recovery 标记 / 动作分配 / always 守卫 /
  transitions_from 方法 / 初始状态
- 可达性分析：手动构造死锁 FSM，验证检测逻辑抛出 CompilerError

导入风格参考 test_dsl_validator.py：sys.path 注入 backend 根目录后用
``from dsl.xxx import``。编译器不导入积木库，故测试配置中的 kind 字符串
无需在注册表中存在（编译阶段只处理 schema 数据结构）。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from dsl.schema import StrategyDSL, Trigger
from dsl.compiler import (
    FSMCompiler,
    FSM,
    FSMState,
    FSMStateType,
    Transition,
    CompilerError,
)


# ============================================================
# 辅助构造
# ============================================================


def _compile(config: dict) -> FSM:
    """从 dict 配置编译 FSM（compile 内部会解析为 StrategyDSL）。"""
    return FSMCompiler().compile(config)


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


def _condition_trigger(cond: dict) -> dict:
    return {"mode": "condition", "condition": cond}


def _event_trigger(event_kind: str = "on_margin_warning",
                   args: dict | None = None) -> dict:
    return {"mode": "event", "event": {"kind": event_kind, "args": args or {}}}


def _recovery_rule(name: str = "单边上涨暂停",
                   when_mode: str = "condition") -> dict:
    """用户示例「单边上涨暂停」规则：触发-恢复对。"""
    when = (
        _condition_trigger(_gt(_price_change_indicator("1h"), 0.05))
        if when_mode == "condition"
        else _event_trigger("on_tick", {"symbol": "BTC-USDT"})
    )
    return {
        "name": name,
        "when": when,
        "then": [
            {"kind": "pause_orders"},
            {"kind": "hold_position"},
            {"kind": "log_event", "args": {"level": "warn", "message": name}},
        ],
        "recover_when": _condition_trigger(
            _abs_lt(_price_change_indicator("1h"), 0.05)
        ),
        "recover_then": [
            {"kind": "rebalance_position", "args": {"mode": "to_theoretical"}},
            {"kind": "resume_orders"},
        ],
        "cool_down_seconds": 60,
    }


def _onetime_rule(name: str = "净值回撤全平止损",
                  when_mode: str = "event") -> dict:
    """无 recover_when 的一次性触发规则。"""
    when = (
        _event_trigger("on_equity_drawdown", {"pct": 0.1})
        if when_mode == "event"
        else _condition_trigger(_gt(_price_change_indicator("1h"), 0.05))
    )
    return {
        "name": name,
        "when": when,
        "then": [
            {"kind": "close_all"},
            {"kind": "stop_strategy"},
        ],
    }


def _transition_pairs(fsm: FSM, rule_name: str) -> dict[str, Transition]:
    """按 (from_state, to_state) 索引某规则的转换。"""
    return {
        f"{t.from_state}->{t.to_state}": t
        for t in fsm.transitions
        if t.rule_name == rule_name
    }


# ============================================================
# 编译正确性
# ============================================================


def test_compile_minimal_no_rules():
    """只有 base_strategy 无 rules → FSM 仅含 RUNNING 状态，0 转换。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [],
    }
    fsm = _compile(config)
    assert fsm.initial_state == "RUNNING"
    assert set(fsm.states.keys()) == {"RUNNING"}
    assert fsm.transitions == []
    running = fsm.get_state("RUNNING")
    assert running is not None
    assert running.state_type == FSMStateType.RUNNING
    assert running.rule_name is None


def test_compile_rule_with_recovery():
    """用户示例「单边上涨暂停」→ 3 状态 + 3 转换。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [_recovery_rule("单边上涨暂停")],
    }
    fsm = _compile(config)

    assert set(fsm.states.keys()) == {
        "RUNNING",
        "PAUSED_单边上涨暂停",
        "REBALANCING_单边上涨暂停",
    }
    assert len(fsm.transitions) == 3

    paused = fsm.get_state("PAUSED_单边上涨暂停")
    assert paused.state_type == FSMStateType.PAUSED
    assert paused.rule_name == "单边上涨暂停"
    rebal = fsm.get_state("REBALANCING_单边上涨暂停")
    assert rebal.state_type == FSMStateType.REBALANCING
    assert rebal.rule_name == "单边上涨暂停"

    # 三段转换的 from/to 正确
    pairs = _transition_pairs(fsm, "单边上涨暂停")
    assert "RUNNING->PAUSED_单边上涨暂停" in pairs
    assert "PAUSED_单边上涨暂停->REBALANCING_单边上涨暂停" in pairs
    assert "REBALANCING_单边上涨暂停->RUNNING" in pairs


def test_compile_rule_without_recovery():
    """无 recover_when 的规则 → 1 状态（RUNNING）+ 1 转换（RUNNING→RUNNING）。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [_onetime_rule("净值回撤全平止损", when_mode="event")],
    }
    fsm = _compile(config)

    assert set(fsm.states.keys()) == {"RUNNING"}
    assert len(fsm.transitions) == 1
    t = fsm.transitions[0]
    assert t.from_state == "RUNNING"
    assert t.to_state == "RUNNING"
    assert t.rule_name == "净值回撤全平止损"
    assert t.is_recovery is False


def test_compile_multiple_rules():
    """2 条带恢复的规则 → 5 状态 + 6 转换。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            _recovery_rule("单边上涨暂停"),
            _recovery_rule("RSI超买暂停"),
        ],
    }
    fsm = _compile(config)

    assert set(fsm.states.keys()) == {
        "RUNNING",
        "PAUSED_单边上涨暂停",
        "REBALANCING_单边上涨暂停",
        "PAUSED_RSI超买暂停",
        "REBALANCING_RSI超买暂停",
    }
    assert len(fsm.states) == 5
    assert len(fsm.transitions) == 6  # 每条规则 3 个转换

    # 每条规则各有 1 个从 RUNNING 出发的触发转换
    running_out = fsm.transitions_from("RUNNING")
    assert len(running_out) == 2
    assert {t.to_state for t in running_out} == {
        "PAUSED_单边上涨暂停",
        "PAUSED_RSI超买暂停",
    }


def test_compile_condition_trigger_guard_kind():
    """mode="condition" → guard_kind="condition"。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [_recovery_rule("单边上涨暂停", when_mode="condition")],
    }
    fsm = _compile(config)
    trigger_t = next(
        t for t in fsm.transitions
        if t.from_state == "RUNNING" and t.to_state == "PAUSED_单边上涨暂停"
    )
    assert trigger_t.guard_kind == "condition"


def test_compile_event_trigger_guard_kind():
    """mode="event" → guard_kind="event"。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [_recovery_rule("事件触发暂停", when_mode="event")],
    }
    fsm = _compile(config)
    trigger_t = next(
        t for t in fsm.transitions
        if t.from_state == "RUNNING" and t.to_state == "PAUSED_事件触发暂停"
    )
    assert trigger_t.guard_kind == "event"


def test_compile_recovery_transition_marked():
    """恢复转换（PAUSED→REBALANCING 与 REBALANCING→RUNNING）的 is_recovery=True，
    触发转换（RUNNING→PAUSED）为 False。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [_recovery_rule("单边上涨暂停")],
    }
    fsm = _compile(config)
    pairs = _transition_pairs(fsm, "单边上涨暂停")

    assert pairs["RUNNING->PAUSED_单边上涨暂停"].is_recovery is False
    assert pairs["PAUSED_单边上涨暂停->REBALANCING_单边上涨暂停"].is_recovery is True
    assert pairs["REBALANCING_单边上涨暂停->RUNNING"].is_recovery is True


def test_compile_actions_assigned_correctly():
    """then 动作在触发转换，recover_then 动作在恢复转换，REBALANCING→RUNNING 无动作。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [_recovery_rule("单边上涨暂停")],
    }
    fsm = _compile(config)
    pairs = _transition_pairs(fsm, "单边上涨暂停")

    trigger_t = pairs["RUNNING->PAUSED_单边上涨暂停"]
    assert [a.kind for a in trigger_t.actions] == [
        "pause_orders", "hold_position", "log_event"
    ]

    recover_t = pairs["PAUSED_单边上涨暂停->REBALANCING_单边上涨暂停"]
    assert [a.kind for a in recover_t.actions] == [
        "rebalance_position", "resume_orders"
    ]

    back_t = pairs["REBALANCING_单边上涨暂停->RUNNING"]
    assert back_t.actions == []


def test_compile_always_guard_for_rebalancing_to_running():
    """REBALANCING→RUNNING 的 guard_kind="always"。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [_recovery_rule("单边上涨暂停")],
    }
    fsm = _compile(config)
    back_t = next(
        t for t in fsm.transitions
        if t.from_state == "REBALANCING_单边上涨暂停" and t.to_state == "RUNNING"
    )
    assert back_t.guard_kind == "always"


def test_transitions_from_method():
    """transitions_from("RUNNING") 返回从 RUNNING 出发的全部转换。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            _recovery_rule("单边上涨暂停"),
            _onetime_rule("净值回撤全平止损", when_mode="event"),
        ],
    }
    fsm = _compile(config)

    running_out = fsm.transitions_from("RUNNING")
    # 一条恢复规则的触发转换 + 一条一次性规则的 RUNNING→RUNNING 转换 = 2
    assert len(running_out) == 2
    targets = sorted(t.to_state for t in running_out)
    assert targets == ["PAUSED_单边上涨暂停", "RUNNING"]

    # PAUSED 状态出发只有 1 条到 REBALANCING
    paused_out = fsm.transitions_from("PAUSED_单边上涨暂停")
    assert len(paused_out) == 1
    assert paused_out[0].to_state == "REBALANCING_单边上涨暂停"

    # 不存在的状态返回空列表
    assert fsm.transitions_from("NOT_EXIST") == []


def test_initial_state_is_running():
    """fsm.initial_state == "RUNNING"，且 RUNNING 状态一定存在。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [_recovery_rule("单边上涨暂停")],
    }
    fsm = _compile(config)
    assert fsm.initial_state == "RUNNING"
    assert "RUNNING" in fsm.states
    assert fsm.get_state("RUNNING").state_type == FSMStateType.RUNNING


def test_compile_accepts_strategy_dsl_object():
    """compile 也接受 StrategyDSL 对象（不仅是 dict）。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [_onetime_rule("一次性", when_mode="event")],
    }
    dsl = StrategyDSL.model_validate(config)
    fsm = FSMCompiler().compile(dsl)
    assert len(fsm.transitions) == 1
    assert fsm.transitions[0].from_state == "RUNNING"
    assert fsm.transitions[0].to_state == "RUNNING"


# ============================================================
# 可达性分析（SubTask 10.3）
# ============================================================


def test_reachability_no_deadlock_for_valid_fsm():
    """合法 FSM（每条恢复规则都形成闭环）不应报死锁。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [_recovery_rule("单边上涨暂停")],
    }
    fsm = _compile(config)
    # 正常编译通过即说明无死锁；这里再次显式验证
    assert fsm.find_unreachable_to_running() == []


def test_reachability_deadlock_raises():
    """手动构造无法回到 RUNNING 的 FSM，验证检测逻辑抛出 CompilerError。

    由于校验器会拦截非法配置，且编译器对任何带 recover_when 的规则都会
    生成回到 RUNNING 的闭环，正常 DSL 不会产生死锁。因此这里直接手动
    拼一个 FSM（带 PAUSED 死状态、无回 RUNNING 的转换），分别验证：
      1. FSM.find_unreachable_to_running() 返回死锁状态
      2. FSMCompiler._check_reachability() 抛出 CompilerError
    """
    fsm = FSM()
    fsm.states["RUNNING"] = FSMState(
        name="RUNNING", state_type=FSMStateType.RUNNING, rule_name=None
    )
    fsm.states["PAUSED_死锁规则"] = FSMState(
        name="PAUSED_死锁规则",
        state_type=FSMStateType.PAUSED,
        rule_name="死锁规则",
    )
    # 只有 RUNNING -> PAUSED 的转换，没有 PAUSED -> ... -> RUNNING 的回路
    fsm.transitions.append(Transition(
        from_state="RUNNING",
        to_state="PAUSED_死锁规则",
        trigger=Trigger(),
        guard_kind="condition",
        actions=[],
        rule_name="死锁规则",
        is_recovery=False,
    ))

    # 1. 纯查询接口
    deadlocked = fsm.find_unreachable_to_running()
    assert deadlocked == ["PAUSED_死锁规则"]

    # 2. 编译器检查接口抛异常
    compiler = FSMCompiler()
    with pytest.raises(CompilerError):
        compiler._check_reachability(fsm)


def test_reachability_rebalancing_without_back_edge_deadlocks():
    """REBALANCING 状态若无回到 RUNNING 的边，也应被判为死锁。"""
    fsm = FSM()
    fsm.states["RUNNING"] = FSMState(
        name="RUNNING", state_type=FSMStateType.RUNNING, rule_name=None
    )
    fsm.states["PAUSED_R"] = FSMState(
        name="PAUSED_R", state_type=FSMStateType.PAUSED, rule_name="R"
    )
    fsm.states["REBALANCING_R"] = FSMState(
        name="REBALANCING_R",
        state_type=FSMStateType.REBALANCING,
        rule_name="R",
    )
    # RUNNING -> PAUSED -> REBALANCING，但 REBALANCING 无后续边
    fsm.transitions.append(Transition(
        from_state="RUNNING", to_state="PAUSED_R", trigger=Trigger(),
        guard_kind="condition", actions=[], rule_name="R", is_recovery=False,
    ))
    fsm.transitions.append(Transition(
        from_state="PAUSED_R", to_state="REBALANCING_R", trigger=Trigger(),
        guard_kind="condition", actions=[], rule_name="R", is_recovery=True,
    ))

    deadlocked = fsm.find_unreachable_to_running()
    # PAUSED_R 可经 REBALANCING_R... 但 REBALANCING_R 无出边，两者都死锁
    assert set(deadlocked) == {"PAUSED_R", "REBALANCING_R"}

    with pytest.raises(CompilerError):
        FSMCompiler()._check_reachability(fsm)
