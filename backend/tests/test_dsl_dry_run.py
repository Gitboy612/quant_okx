"""DSL 历史回放模拟器测试（Task 14）。

覆盖 DryRunSimulator 的核心回放逻辑：

- 无 rules 的 DSL + 模拟数据 → 全程 RUNNING、无触发
- 含 price_change_pct > 阈值的规则 + 上涨数据 → 部分步触发，状态迁移到 PAUSED
- 含 recover_when 的规则 + 先涨后跌数据 → 触发后能恢复到 RUNNING
- 触发步的 actions 列表非空且含正确 action kind
- 每步 indicator_values 含条件引用的指标值
- total_ticks / triggered_count / final_state 统计正确

测试策略：直接构造 K 线列表（时间正序，最早在前）传入 ``candles`` 参数，
不依赖 OKX 客户端。K 线格式为 OKX 标准：
``[ts, open, high, low, close, vol, volCcy, volCcyConfirm, confirm]``。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from dsl.dry_run import DryRunSimulator, DryRunResult, DryRunStep


# ============================================================
# 辅助构造
# ============================================================


def _base_grid() -> dict:
    """基础网格策略配置。"""
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


def _minimal_config() -> dict:
    """无 rules 的最小 DSL 配置。"""
    return {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [],
    }


def _pause_config() -> dict:
    """含单条「单边上涨暂停」规则（无 recover_when）的配置。

    触发后停留在 PAUSED 状态无法恢复。
    """
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
                    {"kind": "log_event", "args": {"level": "warn", "message": "m"}},
                ],
            }
        ],
    }


def _pause_recover_config() -> dict:
    """含「单边上涨暂停 + 恢复」规则对的配置。"""
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
    """构造连续上涨 K 线（每根收盘比上根高 pct）。时间正序。"""
    candles = []
    price = start
    base_ts = 1_700_000_000_000
    bar_ms = 3_600_000  # 1H
    for i in range(n):
        new_price = price * (1 + pct)
        candles.append(_make_candle(base_ts + i * bar_ms, new_price, price))
        price = new_price
    return candles


def _rise_then_fall_candles(
    rise_n: int, fall_n: int, start: float = 100.0,
    rise_pct: float = 0.06, fall_pct: float = -0.03,
) -> list[list[str]]:
    """构造先涨后跌 K 线。时间正序。"""
    candles = []
    price = start
    base_ts = 1_700_000_000_000
    bar_ms = 3_600_000  # 1H
    for i in range(rise_n):
        new_price = price * (1 + rise_pct)
        candles.append(_make_candle(base_ts + i * bar_ms, new_price, price))
        price = new_price
    for j in range(fall_n):
        new_price = price * (1 + fall_pct)
        candles.append(_make_candle(base_ts + (rise_n + j) * bar_ms, new_price, price))
        price = new_price
    return candles


# ============================================================
# 测试用例
# ============================================================


@pytest.mark.asyncio
async def test_dry_run_minimal_no_rules():
    """无 rules 的 DSL + 模拟数据 → 所有步 state=RUNNING, triggered=False。"""
    candles = _rising_candles(5)
    simulator = DryRunSimulator()
    result = await simulator.run(
        _minimal_config(), "BTC-USDT", "1H", 5, candles=candles
    )

    assert isinstance(result, DryRunResult)
    assert result.total_ticks == 5
    assert len(result.steps) == 5
    for step in result.steps:
        assert step.state == "RUNNING"
        assert step.triggered is False
        assert step.rule_name is None
        assert step.actions == []
        assert step.transition is None
    assert result.triggered_count == 0
    assert result.state_changes == 0
    assert result.final_state == "RUNNING"


@pytest.mark.asyncio
async def test_dry_run_with_condition_trigger():
    """含 price_change_pct > 5% 规则 + 上涨数据 → 部分步触发，迁移到 PAUSED。

    使用带 recover_when 的配置，但数据持续上涨（|涨幅| > 5% 恢复条件不满足），
    因此 FSM 进入 PAUSED 后不恢复。
    """
    # 每根涨 6%，price_change_pct = 0.06 > 0.05
    candles = _rising_candles(5, pct=0.06)
    simulator = DryRunSimulator()
    result = await simulator.run(
        _pause_recover_config(), "BTC-USDT", "1H", 5, candles=candles
    )

    assert result.total_ticks == 5
    # 第 0 根 K 线无前一根（get_candles 只返回 1 根），price_change_pct=0.0，不触发
    assert result.steps[0].triggered is False
    assert result.steps[0].state == "RUNNING"

    # 第 1 根起 price_change_pct=0.06 > 0.05 → 触发，迁移到 PAUSED
    assert result.steps[1].triggered is True
    assert result.steps[1].state.startswith("PAUSED")
    assert result.steps[1].rule_name == "单边上涨暂停"
    assert result.steps[1].transition is not None
    assert "RUNNING" in result.steps[1].transition
    assert "PAUSED" in result.steps[1].transition

    # 持续上涨，恢复条件 abs_lt(0.05) 不满足，后续步停留在 PAUSED，不触发
    for step in result.steps[2:]:
        assert step.state.startswith("PAUSED")
        assert step.triggered is False

    assert result.triggered_count == 1
    assert result.final_state.startswith("PAUSED")


@pytest.mark.asyncio
async def test_dry_run_with_recovery():
    """含 recover_when 的规则 + 先涨后跌数据 → 触发后能恢复到 RUNNING。"""
    # 前 3 根涨 6%（触发暂停），后 4 根跌 3%（|−3%| < 5% 触发恢复）
    candles = _rise_then_fall_candles(rise_n=3, fall_n=4, rise_pct=0.06, fall_pct=-0.03)
    simulator = DryRunSimulator()
    result = await simulator.run(
        _pause_recover_config(), "BTC-USDT", "1H", 7, candles=candles
    )

    assert result.total_ticks == 7

    # 应至少有一次触发（RUNNING → PAUSED）
    triggered_steps = [s for s in result.steps if s.triggered]
    assert len(triggered_steps) >= 2  # 至少：暂停 + 恢复 + 回 RUNNING

    # 最终应恢复到 RUNNING
    assert result.final_state == "RUNNING"

    # 验证状态转换链中包含 PAUSED 和 REBALANCING
    transitions = [s.transition for s in result.steps if s.transition]
    transition_str = " | ".join(transitions)
    assert "PAUSED" in transition_str
    assert "REBALANCING" in transition_str
    assert "RUNNING" in transition_str


@pytest.mark.asyncio
async def test_dry_run_records_actions():
    """触发步骤的 actions 列表非空，含正确的 action kind。"""
    candles = _rising_candles(3, pct=0.06)
    simulator = DryRunSimulator()
    result = await simulator.run(
        _pause_config(), "BTC-USDT", "1H", 3, candles=candles
    )

    # 找到触发步
    triggered = [s for s in result.steps if s.triggered]
    assert len(triggered) >= 1

    step = triggered[0]
    assert len(step.actions) > 0
    # _pause_config 的 then 为 pause_orders, hold_position, log_event
    assert "pause_orders" in step.actions
    assert "hold_position" in step.actions
    assert "log_event" in step.actions

    # 未触发步的 actions 应为空
    for step in result.steps:
        if not step.triggered:
            assert step.actions == []


@pytest.mark.asyncio
async def test_dry_run_records_indicator_values():
    """每步的 indicator_values 含 condition 引用的指标值。"""
    candles = _rising_candles(4, pct=0.06)
    simulator = DryRunSimulator()
    result = await simulator.run(
        _pause_config(), "BTC-USDT", "1H", 4, candles=candles
    )

    expected_key = "price_change_pct(symbol=BTC-USDT,window=1h)"
    for step in result.steps:
        assert expected_key in step.indicator_values, (
            f"step {step.timestamp} 缺少指标 {expected_key}"
        )
        val = step.indicator_values[expected_key]
        # 第 0 步无前一根 K 线，price_change_pct=0.0；后续步应为 0.06
        assert isinstance(val, (int, float))


@pytest.mark.asyncio
async def test_dry_run_total_ticks():
    """total_ticks == K 线根数。"""
    for n in (1, 5, 10, 20):
        candles = _rising_candles(n)
        simulator = DryRunSimulator()
        result = await simulator.run(
            _minimal_config(), "BTC-USDT", "1H", n, candles=candles
        )
        assert result.total_ticks == n
        assert len(result.steps) == n


@pytest.mark.asyncio
async def test_dry_run_triggered_count():
    """triggered_count == 触发步数。

    使用带 recover_when 的配置 + 持续上涨数据：仅第 1 步触发（RUNNING→PAUSED），
    后续步在 PAUSED 状态且恢复条件不满足，不触发。
    """
    candles = _rising_candles(5, pct=0.06)
    simulator = DryRunSimulator()
    result = await simulator.run(
        _pause_recover_config(), "BTC-USDT", "1H", 5, candles=candles
    )

    triggered_steps = [s for s in result.steps if s.triggered]
    assert result.triggered_count == len(triggered_steps)
    # 仅第 1 步触发（RUNNING→PAUSED），后续在 PAUSED 且恢复条件不满足
    assert result.triggered_count == 1


@pytest.mark.asyncio
async def test_dry_run_final_state_no_recovery():
    """有 recover_when 但恢复条件不满足 → final_state 为 PAUSED。"""
    candles = _rising_candles(5, pct=0.06)
    simulator = DryRunSimulator()
    result = await simulator.run(
        _pause_recover_config(), "BTC-USDT", "1H", 5, candles=candles
    )
    assert result.final_state.startswith("PAUSED")


@pytest.mark.asyncio
async def test_dry_run_final_state_with_recovery():
    """有 recover_when + 先涨后跌 → final_state 为 RUNNING。"""
    candles = _rise_then_fall_candles(rise_n=3, fall_n=5, rise_pct=0.06, fall_pct=-0.03)
    simulator = DryRunSimulator()
    result = await simulator.run(
        _pause_recover_config(), "BTC-USDT", "1H", 8, candles=candles
    )
    assert result.final_state == "RUNNING"


@pytest.mark.asyncio
async def test_dry_run_mock_candles_no_client():
    """无 OKX 客户端且不传 candles → 使用模拟数据，能正常回放。"""
    simulator = DryRunSimulator()  # okx_client=None
    result = await simulator.run(
        _pause_recover_config(), "BTC-USDT", "1H", 10
    )

    assert result.total_ticks == 10
    assert len(result.steps) == 10
    # 模拟数据前半段涨 6%（应触发暂停），后半段跌 3%（应触发恢复）
    triggered = [s for s in result.steps if s.triggered]
    assert len(triggered) >= 1
    # 最终恢复到 RUNNING
    assert result.final_state == "RUNNING"


@pytest.mark.asyncio
async def test_dry_run_invalid_config_raises():
    """非法 DSL 配置 → 抛 ValueError。"""
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
    simulator = DryRunSimulator()
    with pytest.raises(ValueError, match="DSL 配置校验失败"):
        await simulator.run(bad_config, "BTC-USDT", "1H", 5)


@pytest.mark.asyncio
async def test_dry_run_step_fields_complete():
    """每步 DryRunStep 含完整字段：timestamp/price/state/indicator_values/triggered/rule_name/actions/transition。"""
    candles = _rising_candles(3, pct=0.06)
    simulator = DryRunSimulator()
    result = await simulator.run(
        _pause_config(), "BTC-USDT", "1H", 3, candles=candles
    )

    for step in result.steps:
        assert isinstance(step, DryRunStep)
        assert isinstance(step.timestamp, str)
        assert isinstance(step.price, float)
        assert isinstance(step.state, str)
        assert isinstance(step.indicator_values, dict)
        assert isinstance(step.triggered, bool)
        assert isinstance(step.actions, list)
        # rule_name / transition 可以是 None
        assert step.rule_name is None or isinstance(step.rule_name, str)
        assert step.transition is None or isinstance(step.transition, str)


@pytest.mark.asyncio
async def test_dry_run_cooldown_prevents_rapid_trigger():
    """冷却期内同规则不重复触发。

    构造连续上涨数据 + cool_down_seconds=3600（1H），
    第 1 步触发后，后续步在冷却期内（1H 间隔 = 3600s，不 < 3600）边界情况。
    改用 cool_down_seconds=7200（2H）确保第 2 步仍在冷却内。
    """
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "单边上涨暂停",
                "when": {
                    "mode": "condition",
                    "condition": _gt(_price_change_indicator("1h"), 0.05),
                },
                "then": [{"kind": "pause_orders"}],
                # 一次性触发（RUNNING→RUNNING），cool_down=7200s（2H）
                # K 线间隔 1H=3600s，第 2 步 ts-第1步 ts = 3600 < 7200 → 冷却中
                "cool_down_seconds": 7200,
            }
        ],
    }
    candles = _rising_candles(4, pct=0.06)
    simulator = DryRunSimulator()
    result = await simulator.run(
        config, "BTC-USDT", "1H", 4, candles=candles
    )

    # 第 1 步触发（price_change_pct=0.06 > 0.05）
    assert result.steps[1].triggered is True
    # 第 2 步在冷却内（3600 < 7200），不触发
    assert result.steps[2].triggered is False
    # 第 3 步冷却已过（7200s = 2*3600），可再次触发
    assert result.steps[3].triggered is True
    assert result.triggered_count == 2


@pytest.mark.asyncio
async def test_dry_run_with_okx_client():
    """传入 mock OKX 客户端 → 从客户端拉取 K 线回放。"""
    from unittest.mock import AsyncMock

    # 构造 OKX 返回格式（最新在前）
    candles_chrono = _rising_candles(4, pct=0.06)
    okx_candles = list(reversed(candles_chrono))  # 最新在前

    mock_client = AsyncMock()
    mock_client.get_candles.return_value = okx_candles

    simulator = DryRunSimulator(okx_client=mock_client)
    result = await simulator.run(
        _pause_config(), "BTC-USDT", "1H", 4
    )

    assert result.total_ticks == 4
    mock_client.get_candles.assert_called_once_with(
        inst_id="BTC-USDT", bar="1H", limit="4"
    )
    # 第 1 步应触发
    assert result.steps[1].triggered is True
