"""ComposableStrategy tick 吞吐性能基准测试。

测试维度：
1. 单次 tick 执行耗时（含 _refresh_price / _build_context / guard 评估 / 转换扫描）
2. 1000 次 tick 连续执行总耗时
3. 多规则规模（5 / 10 / 20 条规则）下的 tick 执行耗时

基准标准：
- 单次 tick < 50ms
- 1000 次连续 tick < 5s

实现说明：
- 使用 mock OKXClient（get_ticker 返回固定 ticker），不依赖实际 API
- 使用 mock evaluate_condition（返回 False，模拟常见无触发场景），
  测量 FSM guard 评估 + 转换扫描的 CPU 开销
- 直接调用 execute() 主循环的逐 tick 逻辑（通过 tick 计数器在 N 次后退出），
  避免拆分内部方法导致行为偏离生产代码
- 使用 time.perf_counter() 高精度计时
"""
import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from dsl.executor import ComposableStrategy
from dsl.schema import StrategyDSL
from dsl.compiler import FSMCompiler

pytestmark = pytest.mark.perf


# ============================================================
# 配置生成
# ============================================================


def _make_rule(idx: int) -> dict:
    """生成单条 condition-triggered 规则（无 recover_when，编译为 RUNNING→RUNNING 自环）。"""
    return {
        "name": f"rule_{idx}",
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
            {"kind": "log_event", "args": {"level": "warn", "message": f"rule_{idx} triggered"}},
        ],
        "cool_down_seconds": 60,
    }


def _make_config(n_rules: int) -> dict:
    """生成含 n_rules 条规则的 DSL 配置（含 grid base_strategy）。"""
    return {
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
        "rules": [_make_rule(i) for i in range(n_rules)],
    }


# ============================================================
# Strategy 构造与 tick 运行
# ============================================================


def _make_benchmark_strategy(n_rules: int) -> ComposableStrategy:
    """构造一个带 mock 依赖的 ComposableStrategy，已编译 FSM，可直接执行 tick。

    - client.get_ticker → AsyncMock 返回固定 ticker
    - _record_event → no-op（避免 DB 写入干扰计时）
    - _restore_realized_pnl_from_db / _load_daily_baseline → no-op
    - _base_block → mock（on_tick / on_start / on_stop 为 AsyncMock）
    """
    config = _make_config(n_rules)
    client = MagicMock()
    client.get_ticker = AsyncMock(return_value=[{"last": "50000"}])
    order_manager = MagicMock()
    order_manager.cancel_all = AsyncMock(return_value=0)
    db_session_factory = MagicMock()

    strategy = ComposableStrategy(
        instance_id=1,
        params={"dsl_config": config, "tick_interval": 0},
        client=client,
        db_session_factory=db_session_factory,
        account_id=1,
        order_manager=order_manager,
    )

    # 预编译 DSL → FSM（跳过 execute() 的完整启动流程）
    strategy._dsl = StrategyDSL.model_validate(config)
    strategy._fsm = FSMCompiler().compile(strategy._dsl)
    strategy._rule_map = {rule.name: rule for rule in strategy._dsl.rules}
    strategy._running = True
    strategy._current_state = "RUNNING"

    # mock base_block（避免 GridBlock.on_start 真实挂单）
    base_block = MagicMock()
    base_block.on_tick = AsyncMock()
    base_block.on_start = AsyncMock()
    base_block.on_stop = AsyncMock()
    base_block.on_pause = AsyncMock()
    base_block.on_resume = AsyncMock()
    strategy._base_block = base_block

    return strategy


async def _run_ticks(strategy: ComposableStrategy, n: int) -> None:
    """执行 n 次 tick 后退出（复刻 execute() 主循环的逐 tick 逻辑）。

    通过覆盖 _build_context 在第 n 次调用后设置 _running=False 退出循环，
    同时 patch asyncio.sleep 为 no-op 避免真实等待。
    """
    counter = {"n": 0}
    original_build = strategy._build_context

    def _ctx_with_counter():
        ctx = original_build()
        counter["n"] += 1
        if counter["n"] >= n:
            strategy._running = False
        return ctx

    strategy._build_context = _ctx_with_counter

    with patch("dsl.executor.asyncio.sleep", new=AsyncMock()):
        await strategy.execute()


# ============================================================
# 基准测试：单次 tick
# ============================================================


@pytest.mark.asyncio
async def test_single_tick_latency():
    """单次 tick 执行耗时 < 50ms。

    使用 10 条规则的策略，mock evaluate_condition 返回 False（无转换触发），
    测量完整的单次 tick 处理路径。
    """
    strategy = _make_benchmark_strategy(n_rules=10)

    with patch("dsl.executor.evaluate_condition", new=AsyncMock(return_value=False)):
        # warm up（首次 execute 含启动开销，不计入）
        await _run_ticks(strategy, 3)
        strategy._running = True
        strategy._current_state = "RUNNING"

        start = time.perf_counter()
        await _run_ticks(strategy, 1)
        elapsed_ms = (time.perf_counter() - start) * 1000

    print(f"\n[perf] 单次 tick 耗时: {elapsed_ms:.3f}ms (10 rules)")
    assert elapsed_ms < 50.0, f"单次 tick 耗时 {elapsed_ms:.2f}ms 超过 50ms 基准"


# ============================================================
# 基准测试：1000 次连续 tick
# ============================================================


@pytest.mark.asyncio
async def test_1000_ticks_throughput():
    """1000 次连续 tick 总耗时 < 5s。

    使用 10 条规则的策略，测量连续 tick 的吞吐能力。
    """
    strategy = _make_benchmark_strategy(n_rules=10)

    with patch("dsl.executor.evaluate_condition", new=AsyncMock(return_value=False)):
        # warm up
        await _run_ticks(strategy, 10)
        strategy._running = True
        strategy._current_state = "RUNNING"

        start = time.perf_counter()
        await _run_ticks(strategy, 1000)
        elapsed_s = time.perf_counter() - start

    avg_ms = (elapsed_s / 1000) * 1000
    print(f"\n[perf] 1000 次 tick 总耗时: {elapsed_s:.3f}s, 平均: {avg_ms:.3f}ms/tick (10 rules)")
    assert elapsed_s < 5.0, f"1000 次 tick 耗时 {elapsed_s:.2f}s 超过 5s 基准"


# ============================================================
# 基准测试：多规则规模（5 / 10 / 20）
# ============================================================


@pytest.mark.asyncio
async def test_tick_latency_with_5_rules():
    """5 条规则下单次 tick 耗时 < 50ms。"""
    strategy = _make_benchmark_strategy(n_rules=5)

    with patch("dsl.executor.evaluate_condition", new=AsyncMock(return_value=False)):
        await _run_ticks(strategy, 5)  # warm up
        strategy._running = True
        strategy._current_state = "RUNNING"

        start = time.perf_counter()
        await _run_ticks(strategy, 100)
        elapsed_s = time.perf_counter() - start

    avg_ms = (elapsed_s / 100) * 1000
    print(f"\n[perf] 5 规则: {avg_ms:.3f}ms/tick (100 ticks, total {elapsed_s:.3f}s)")
    assert avg_ms < 50.0, f"5 规则 tick 耗时 {avg_ms:.2f}ms 超过 50ms 基准"


@pytest.mark.asyncio
async def test_tick_latency_with_10_rules():
    """10 条规则下单次 tick 耗时 < 50ms。"""
    strategy = _make_benchmark_strategy(n_rules=10)

    with patch("dsl.executor.evaluate_condition", new=AsyncMock(return_value=False)):
        await _run_ticks(strategy, 5)  # warm up
        strategy._running = True
        strategy._current_state = "RUNNING"

        start = time.perf_counter()
        await _run_ticks(strategy, 100)
        elapsed_s = time.perf_counter() - start

    avg_ms = (elapsed_s / 100) * 1000
    print(f"\n[perf] 10 规则: {avg_ms:.3f}ms/tick (100 ticks, total {elapsed_s:.3f}s)")
    assert avg_ms < 50.0, f"10 规则 tick 耗时 {avg_ms:.2f}ms 超过 50ms 基准"


@pytest.mark.asyncio
async def test_tick_latency_with_20_rules():
    """20 条规则下单次 tick 耗时 < 50ms。"""
    strategy = _make_benchmark_strategy(n_rules=20)

    with patch("dsl.executor.evaluate_condition", new=AsyncMock(return_value=False)):
        await _run_ticks(strategy, 5)  # warm up
        strategy._running = True
        strategy._current_state = "RUNNING"

        start = time.perf_counter()
        await _run_ticks(strategy, 100)
        elapsed_s = time.perf_counter() - start

    avg_ms = (elapsed_s / 100) * 1000
    print(f"\n[perf] 20 规则: {avg_ms:.3f}ms/tick (100 ticks, total {elapsed_s:.3f}s)")
    assert avg_ms < 50.0, f"20 规则 tick 耗时 {avg_ms:.2f}ms 超过 50ms 基准"


# ============================================================
# 基准测试：FSM 编译耗时（附加）
# ============================================================


def test_fsm_compile_latency():
    """FSM 编译耗时 < 100ms（20 条规则）。

    FSM 编译在策略启动时执行一次，通过 logic_hash 缓存复用。
    测量编译阶段的 CPU 开销。
    """
    config = _make_config(n_rules=20)
    dsl = StrategyDSL.model_validate(config)
    compiler = FSMCompiler()

    # warm up
    compiler.compile(dsl)

    start = time.perf_counter()
    for _ in range(10):
        compiler.compile(dsl)
    elapsed_ms = (time.perf_counter() - start) * 1000 / 10

    print(f"\n[perf] FSM 编译耗时 (20 rules): {elapsed_ms:.3f}ms/次")
    assert elapsed_ms < 100.0, f"FSM 编译耗时 {elapsed_ms:.2f}ms 超过 100ms"
