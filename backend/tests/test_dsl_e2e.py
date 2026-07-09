"""可拼接策略 DSL 端到端验证（Task 15）。

用用户原始示例（网格 + 单边行情暂停-恢复）端到端验证整条 DSL 流水线：

    dsl_config (dict)
      -> DSLValidator.validate        (静态校验)
      -> FSMCompiler.compile          (编译为 FSM)
      -> DryRunSimulator.run          (历史回放)
      -> ComposableStrategy           (执行器实例化与参数校验)
      -> REST API                     (3 个端点协同)

不创建新的实现文件，只验证已有实现的协同工作。测试覆盖：
校验环节 / 编译环节 / Dry-Run 回放环节 / 执行器环节 / API 完整性。

K 线数据格式为 OKX 标准：
``[ts, open, high, low, close, vol, volCcy, volCcyConfirm, confirm]``，
ts 为毫秒时间戳字符串。
"""
import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dsl.validator import DSLValidator
from dsl.compiler import FSMCompiler, FSM
from dsl.dry_run import DryRunSimulator
from dsl.executor import ComposableStrategy
from routers.dsl import router as dsl_router
from services.strategy_engine import StrategyEngine


# ============================================================
# 独立测试 app（仅注册 dsl 路由，避免 main.py 副作用，参考 test_dsl_api.py）
# ============================================================

app = FastAPI()
app.include_router(dsl_router)
api_client = TestClient(app)


# ============================================================
# 用户示例 DSL 配置（网格 + 单边上涨暂停-恢复）
# ============================================================

USER_EXAMPLE_DSL = {
    "version": "1.0",
    "base_strategy": {
        "kind": "grid",
        "params": {
            "upper_price": 50000,
            "lower_price": 40000,
            "grid_count": 10,
            "order_qty": 0.01,
            "symbol": "BTC-USDT",
        },
    },
    "rules": [
        {
            "name": "单边上涨暂停",
            "when": {
                "mode": "condition",
                "condition": {
                    "kind": "gt",
                    "args": {
                        "indicator": {
                            "kind": "price_change_pct",
                            "args": {"window": "1h", "symbol": "BTC-USDT"},
                        },
                        "threshold": 0.05,
                    },
                },
            },
            "then": [
                {"kind": "pause_orders"},
                {"kind": "hold_position"},
                {"kind": "log_event", "args": {"level": "warn", "message": "单边上涨暂停"}},
            ],
            "recover_when": {
                "mode": "condition",
                "condition": {
                    "kind": "abs_lt",
                    "args": {
                        "indicator": {
                            "kind": "price_change_pct",
                            "args": {"window": "1h", "symbol": "BTC-USDT"},
                        },
                        "threshold": 0.05,
                    },
                },
            },
            "recover_then": [
                {"kind": "rebalance_position", "args": {"mode": "to_theoretical"}},
                {"kind": "resume_orders"},
            ],
            "cool_down_seconds": 60,
        }
    ],
}


# ============================================================
# K 线构造辅助（OKX 格式：[ts, o, h, l, c, vol, volCcy, volCcyConfirm, confirm]）
# ============================================================


def _make_candle(ts_ms: int, close: float, open_price: float | None = None) -> list[str]:
    """构造单根 OKX 格式 K 线。"""
    if open_price is None:
        open_price = close
    high = max(open_price, close)
    low = min(open_price, close)
    return [
        str(ts_ms), str(open_price), str(high), str(low), str(close),
        "1", "1", "1", "1",
    ]


def _rising_candles(n: int, start: float = 100.0, pct: float = 0.06) -> list[list[str]]:
    """构造连续上涨 K 线（每根收盘比上根高 pct）。时间正序（最早在前）。"""
    candles: list[list[str]] = []
    price = start
    base_ts = 1_700_000_000_000
    bar_ms = 3_600_000  # 1H
    for i in range(n):
        new_price = price * (1 + pct)
        candles.append(_make_candle(base_ts + i * bar_ms, new_price, price))
        price = new_price
    return candles


def _rising_then_stable_candles(
    rise_n: int, stable_n: int, start: float = 100.0, rise_pct: float = 0.06
) -> list[list[str]]:
    """构造先持续上涨再小幅震荡的 K 线。

    前 rise_n 根每根涨 rise_pct（触发暂停），后 stable_n 根涨跌在 ±2% 内
    （|涨跌幅| < 5% 触发恢复）。时间正序（最早在前）。
    """
    candles: list[list[str]] = []
    price = start
    base_ts = 1_700_000_000_000
    bar_ms = 3_600_000  # 1H
    for i in range(rise_n):
        new_price = price * (1 + rise_pct)
        candles.append(_make_candle(base_ts + i * bar_ms, new_price, price))
        price = new_price
    # 后半段：交替 +2% / -2%，保证 |涨跌幅| < 5%
    stable_changes = [0.02, -0.02]
    for j in range(stable_n):
        change = stable_changes[j % len(stable_changes)]
        new_price = price * (1 + change)
        candles.append(_make_candle(base_ts + (rise_n + j) * bar_ms, new_price, price))
        price = new_price
    return candles


# ============================================================
# 1. 校验环节
# ============================================================


def test_e2e_user_example_validates():
    """用 DSLValidator 校验 USER_EXAMPLE_DSL，结果 valid=True, errors=[]。"""
    result = DSLValidator().validate(USER_EXAMPLE_DSL)
    assert result.valid is True
    assert result.errors == []


def test_e2e_user_example_validates_via_api():
    """用 FastAPI TestClient 调用 POST /api/dsl/validate，返回 valid=True。"""
    resp = api_client.post("/api/dsl/validate", json=USER_EXAMPLE_DSL)
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["errors"] == []


# ============================================================
# 2. 编译环节
# ============================================================


def _compile_user_example() -> FSM:
    """编译 USER_EXAMPLE_DSL 为 FSM（测试复用）。"""
    return FSMCompiler().compile(USER_EXAMPLE_DSL)


def test_e2e_fsm_has_correct_states():
    """FSM 包含 3 个状态：RUNNING / PAUSED_单边上涨暂停 / REBALANCING_单边上涨暂停。"""
    fsm = _compile_user_example()
    expected_states = {
        "RUNNING",
        "PAUSED_单边上涨暂停",
        "REBALANCING_单边上涨暂停",
    }
    assert set(fsm.states.keys()) == expected_states


def test_e2e_fsm_has_correct_transitions():
    """FSM 包含 3 个转换，分别校验 from/to/guard_kind/is_recovery/actions。"""
    fsm = _compile_user_example()
    assert len(fsm.transitions) == 3

    # 转换 1：RUNNING → PAUSED_单边上涨暂停（condition，非恢复，含 then 动作）
    t1 = next(
        t for t in fsm.transitions
        if t.from_state == "RUNNING" and t.to_state == "PAUSED_单边上涨暂停"
    )
    assert t1.guard_kind == "condition"
    assert t1.is_recovery is False
    t1_action_kinds = [a.kind for a in t1.actions]
    assert "pause_orders" in t1_action_kinds
    assert "hold_position" in t1_action_kinds
    assert "log_event" in t1_action_kinds

    # 转换 2：PAUSED_单边上涨暂停 → REBALANCING_单边上涨暂停（condition，恢复，含 recover_then）
    t2 = next(
        t for t in fsm.transitions
        if t.from_state == "PAUSED_单边上涨暂停"
        and t.to_state == "REBALANCING_单边上涨暂停"
    )
    assert t2.guard_kind == "condition"
    assert t2.is_recovery is True
    t2_action_kinds = [a.kind for a in t2.actions]
    assert "rebalance_position" in t2_action_kinds
    assert "resume_orders" in t2_action_kinds

    # 转换 3：REBALANCING_单边上涨暂停 → RUNNING（always，恢复，无显式动作）
    t3 = next(
        t for t in fsm.transitions
        if t.from_state == "REBALANCING_单边上涨暂停" and t.to_state == "RUNNING"
    )
    assert t3.guard_kind == "always"
    assert t3.is_recovery is True


def test_e2e_fsm_initial_state_is_running():
    """fsm.initial_state == "RUNNING"。"""
    fsm = _compile_user_example()
    assert fsm.initial_state == "RUNNING"


def test_e2e_fsm_no_deadlock():
    """所有非 RUNNING 状态都能回到 RUNNING（find_unreachable_to_running 返回空列表）。"""
    fsm = _compile_user_example()
    deadlocked = fsm.find_unreachable_to_running()
    assert deadlocked == []


# ============================================================
# 3. Dry-Run 回放环节
# ============================================================


@pytest.mark.asyncio
async def test_e2e_dry_run_with_rising_prices():
    """构造 10 根持续上涨 K 线（每根涨 6%），回放 → 前 1 步在 RUNNING，
    涨幅超 5% 后迁移到 PAUSED_单边上涨暂停，触发步骤的 actions 含 pause_orders。"""
    candles = _rising_candles(10, pct=0.06)
    simulator = DryRunSimulator()
    result = await simulator.run(
        USER_EXAMPLE_DSL, "BTC-USDT", "1H", 10, candles=candles
    )

    assert result.total_ticks == 10
    # 第 0 根无前一根 K 线，price_change_pct=0.0，不触发，停留 RUNNING
    assert result.steps[0].state == "RUNNING"
    assert result.steps[0].triggered is False

    # 第 1 根起 price_change_pct=0.06 > 0.05 → 触发，迁移到 PAUSED
    triggered_steps = [s for s in result.steps if s.triggered]
    assert len(triggered_steps) >= 1
    pause_step = triggered_steps[0]
    assert pause_step.state.startswith("PAUSED")
    assert pause_step.rule_name == "单边上涨暂停"
    assert "pause_orders" in pause_step.actions
    assert pause_step.transition is not None
    assert "RUNNING" in pause_step.transition
    assert "PAUSED" in pause_step.transition

    # 持续上涨，恢复条件 abs_lt(0.05) 不满足，后续步停留在 PAUSED
    for step in result.steps[2:]:
        assert step.state.startswith("PAUSED")
    assert result.final_state.startswith("PAUSED")


@pytest.mark.asyncio
async def test_e2e_dry_run_with_rising_then_stable():
    """构造 20 根 K 线（前 10 根涨 6%，后 10 根涨跌在 ±2% 内），回放 →
    前 10 步在 RUNNING/PAUSED 间转换，后 10 步从 PAUSED 恢复到
    REBALANCING 再到 RUNNING。"""
    candles = _rising_then_stable_candles(rise_n=10, stable_n=10)
    simulator = DryRunSimulator()
    result = await simulator.run(
        USER_EXAMPLE_DSL, "BTC-USDT", "1H", 20, candles=candles
    )

    assert result.total_ticks == 20

    # 前 10 步：第 0 步 RUNNING，第 1 步触发到 PAUSED，第 2-9 步停留 PAUSED
    assert result.steps[0].state == "RUNNING"
    assert result.steps[1].triggered is True
    assert result.steps[1].state.startswith("PAUSED")
    for step in result.steps[2:10]:
        assert step.state.startswith("PAUSED")

    # 后 10 步：应包含 PAUSED → REBALANCING 与 REBALANCING → RUNNING 两次转换
    transitions = [s.transition for s in result.steps[10:] if s.transition]
    transition_str = " | ".join(transitions)
    assert "REBALANCING" in transition_str
    assert "RUNNING" in transition_str

    # 最终恢复到 RUNNING
    assert result.final_state == "RUNNING"


@pytest.mark.asyncio
async def test_e2e_dry_run_records_indicator_values():
    """回放步骤的 indicator_values 含 price_change_pct 的值。"""
    candles = _rising_candles(5, pct=0.06)
    simulator = DryRunSimulator()
    result = await simulator.run(
        USER_EXAMPLE_DSL, "BTC-USDT", "1H", 5, candles=candles
    )

    expected_key = "price_change_pct(symbol=BTC-USDT,window=1h)"
    for step in result.steps:
        assert expected_key in step.indicator_values, (
            f"step {step.timestamp} 缺少指标 {expected_key}"
        )
        val = step.indicator_values[expected_key]
        assert isinstance(val, (int, float))


def test_e2e_dry_run_via_api():
    """用 TestClient 调用 POST /api/dsl/dry-run，返回 steps 列表非空。"""
    resp = api_client.post(
        "/api/dsl/dry-run",
        json={
            "config": USER_EXAMPLE_DSL,
            "symbol": "BTC-USDT",
            "bar": "1H",
            "limit": 10,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["steps"], list)
    assert len(data["steps"]) > 0
    assert data["total_ticks"] == len(data["steps"])


# ============================================================
# 4. 执行器环节
# ============================================================


@pytest.mark.asyncio
async def test_e2e_composable_strategy_instantiable():
    """ComposableStrategy 可用 USER_EXAMPLE_DSL 的 params 实例化（mock
    client/order_manager），validate_params 返回 True。"""
    client = MagicMock()
    order_manager = MagicMock()
    db_session_factory = MagicMock()
    strategy = ComposableStrategy(
        instance_id=1,
        params={"dsl_config": USER_EXAMPLE_DSL, "tick_interval": 3},
        client=client,
        db_session_factory=db_session_factory,
        account_id=1,
        order_manager=order_manager,
    )
    assert await strategy.validate_params() is True


def test_e2e_strategy_engine_has_composable():
    """strategy_engine._strategy_map 含 "composable" 键。"""
    strategy_map = StrategyEngine._strategy_map
    assert "composable" in strategy_map
    assert strategy_map["composable"] is ComposableStrategy


# ============================================================
# 5. API 完整性
# ============================================================


def test_e2e_blocks_api_returns_grid_base_strategy():
    """GET /api/dsl/blocks 返回的 base_strategies 列表含 grid。"""
    resp = api_client.get("/api/dsl/blocks")
    assert resp.status_code == 200
    base_strategies = resp.json()["base_strategies"]
    kinds = {b["kind"] for b in base_strategies}
    assert "grid" in kinds


def test_e2e_blocks_api_returns_all_p0_blocks():
    """GET /api/dsl/blocks 返回全部 P0 积木：
    indicators 含 price_change_pct/rsi/position_qty；
    actions 含 pause_orders/resume_orders/rebalance_position；
    events 含 on_tick/on_order_filled；
    conditions 含 gt/lt/abs_gt/abs_lt/and/or/not。"""
    resp = api_client.get("/api/dsl/blocks")
    assert resp.status_code == 200
    data = resp.json()

    indicator_kinds = {b["kind"] for b in data["indicators"]}
    for k in ("price_change_pct", "rsi", "position_qty"):
        assert k in indicator_kinds, f"缺少 P0 指标: {k}"

    action_kinds = {b["kind"] for b in data["actions"]}
    for k in ("pause_orders", "resume_orders", "rebalance_position"):
        assert k in action_kinds, f"缺少 P0 动作: {k}"

    event_kinds = {b["kind"] for b in data["events"]}
    for k in ("on_tick", "on_order_filled"):
        assert k in event_kinds, f"缺少 P0 事件: {k}"

    condition_kinds = {b["kind"] for b in data["conditions"]}
    for k in ("gt", "lt", "abs_gt", "abs_lt", "and", "or", "not"):
        assert k in condition_kinds, f"缺少 P0 条件: {k}"
