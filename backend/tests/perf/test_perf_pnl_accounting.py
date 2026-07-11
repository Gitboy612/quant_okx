"""PnL 核算引擎性能基准测试。

测试维度：
1. recompute() 全量核算在不同订单量（100/500/1000/5000）下的耗时
2. incremental_update() 增量核算单条订单耗时

基准标准：
- 1000 条订单 recompute < 500ms
- 单条订单 incremental_update < 5ms

实现说明：
- 生成 mock Order 对象（buy/sell 交替），mock DB session 返回这些订单
- mock SessionLocal 使 recompute/incremental_update 在内存中完成计算
- 不依赖实际数据库，纯 CPU 计算耗时
- 使用 time.perf_counter() 高精度计时
"""
import os
import sys
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from services.pnl_accounting_engine import PnlAccountingEngine
from models.order import Order
from models.pnl import PnlRecord
from models.strategy import StrategyInstance

pytestmark = pytest.mark.perf


# ============================================================
# Mock 数据生成
# ============================================================


def _make_order(oid: int, side: str, px: float, qty: float, fee: float,
                actual_qty: float | None = None, symbol: str = "BTC-USDT"):
    """构造 mock Order 对象，模拟 filled 订单。"""
    o = MagicMock()
    o.id = oid
    o.side = side
    o.fill_px = px
    o.fill_sz = qty
    o.actual_qty = actual_qty if actual_qty is not None else qty
    o.filled_quantity = None
    o.quantity = None
    o.fee = fee
    o.symbol = symbol
    o.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return o


def _generate_orders(n: int) -> list:
    """生成 n 条 mock 订单（buy/sell 交替，价格在 100-120 间波动）。"""
    orders = []
    for i in range(1, n + 1):
        side = "buy" if i % 2 == 1 else "sell"
        px = 100.0 + (i % 20)
        qty = 1.0
        fee = 0.1
        orders.append(_make_order(i, side, px, qty, fee, actual_qty=qty))
    return orders


def _make_mock_instance(account_id: int = 1, symbol: str = "BTC-USDT"):
    """构造 mock StrategyInstance。"""
    inst = MagicMock()
    inst.account_id = account_id
    inst.symbol = symbol
    inst.params = {"fee_rate": 0.001}
    return inst


def _make_recompute_mock_db(orders, instance=None, latest_pnl=None):
    """构造 mock DB session 适配 recompute 的查询链路。

    recompute 查询链路：
      - StrategyInstance: .filter().first()
      - Order: .filter().filter().all()  /  .filter().update()
      - PnlRecord: .filter().order_by().first()
    """
    mock_db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        if model is StrategyInstance:
            chain.filter.return_value.first.return_value = instance
        elif model is Order:
            chain.filter.return_value.filter.return_value.all.return_value = orders
            chain.filter.return_value.update.return_value = 0
        elif model is PnlRecord:
            chain.filter.return_value.order_by.return_value.first.return_value = latest_pnl
        return chain

    mock_db.query.side_effect = query_side_effect
    return mock_db


def _make_incremental_mock_db(new_orders, instance=None, latest_pnl=None):
    """构造 mock DB session 适配 incremental_update 的查询链路。

    incremental_update 查询链路：
      - StrategyInstance: .filter().first()
      - Order: .filter().filter().filter().order_by().all()  /  .filter().update()
      - PnlRecord: .filter().order_by().first()
    """
    mock_db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        if model is StrategyInstance:
            chain.filter.return_value.first.return_value = instance
        elif model is Order:
            chain.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = new_orders
            chain.filter.return_value.update.return_value = 0
        elif model is PnlRecord:
            chain.filter.return_value.order_by.return_value.first.return_value = latest_pnl
        return chain

    mock_db.query.side_effect = query_side_effect
    return mock_db


# ============================================================
# 基准测试：recompute 全量核算
# ============================================================


@pytest.mark.asyncio
async def test_recompute_100_orders():
    """100 条订单 recompute 耗时 < 200ms。"""
    orders = _generate_orders(100)
    instance = _make_mock_instance()
    mock_db = _make_recompute_mock_db(orders, instance=instance, latest_pnl=None)

    engine = PnlAccountingEngine()
    with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
        start = time.perf_counter()
        snapshot = await engine.recompute(strategy_instance_id=1, client=None)
        elapsed_ms = (time.perf_counter() - start) * 1000

    print(f"\n[perf] recompute 100 orders: {elapsed_ms:.3f}ms")
    assert snapshot.order_count == 100
    assert elapsed_ms < 200.0, f"100 条订单 recompute 耗时 {elapsed_ms:.2f}ms 超过 200ms"


@pytest.mark.asyncio
async def test_recompute_500_orders():
    """500 条订单 recompute 耗时 < 300ms。"""
    orders = _generate_orders(500)
    instance = _make_mock_instance()
    mock_db = _make_recompute_mock_db(orders, instance=instance, latest_pnl=None)

    engine = PnlAccountingEngine()
    with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
        start = time.perf_counter()
        snapshot = await engine.recompute(strategy_instance_id=1, client=None)
        elapsed_ms = (time.perf_counter() - start) * 1000

    print(f"\n[perf] recompute 500 orders: {elapsed_ms:.3f}ms")
    assert snapshot.order_count == 500
    assert elapsed_ms < 300.0, f"500 条订单 recompute 耗时 {elapsed_ms:.2f}ms 超过 300ms"


@pytest.mark.asyncio
async def test_recompute_1000_orders():
    """1000 条订单 recompute 耗时 < 500ms（核心基准标准）。"""
    orders = _generate_orders(1000)
    instance = _make_mock_instance()
    mock_db = _make_recompute_mock_db(orders, instance=instance, latest_pnl=None)

    engine = PnlAccountingEngine()
    with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
        start = time.perf_counter()
        snapshot = await engine.recompute(strategy_instance_id=1, client=None)
        elapsed_ms = (time.perf_counter() - start) * 1000

    print(f"\n[perf] recompute 1000 orders: {elapsed_ms:.3f}ms")
    assert snapshot.order_count == 1000
    assert elapsed_ms < 500.0, f"1000 条订单 recompute 耗时 {elapsed_ms:.2f}ms 超过 500ms 基准"


@pytest.mark.asyncio
async def test_recompute_5000_orders():
    """5000 条订单 recompute 耗时 < 3000ms（压力测试）。"""
    orders = _generate_orders(5000)
    instance = _make_mock_instance()
    mock_db = _make_recompute_mock_db(orders, instance=instance, latest_pnl=None)

    engine = PnlAccountingEngine()
    with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
        start = time.perf_counter()
        snapshot = await engine.recompute(strategy_instance_id=1, client=None)
        elapsed_ms = (time.perf_counter() - start) * 1000

    print(f"\n[perf] recompute 5000 orders: {elapsed_ms:.3f}ms")
    assert snapshot.order_count == 5000
    assert elapsed_ms < 3000.0, f"5000 条订单 recompute 耗时 {elapsed_ms:.2f}ms 超过 3000ms"


# ============================================================
# 基准测试：incremental_update 增量核算
# ============================================================


@pytest.mark.asyncio
async def test_incremental_update_single_order():
    """单条订单 incremental_update 耗时 < 5ms。

    基于已有 PnlRecord 基准，新增 1 条 filled 订单进行增量核算。
    使用多次迭代取最小值以消除系统噪声。
    """
    # 基准 PnlRecord
    latest = MagicMock()
    latest.realized_pnl = 10.0
    latest.net_position = 2.0
    latest.avg_buy_price = 100.0
    latest.total_fee = 0.5
    latest.order_count = 5
    latest.equity = 5000.0

    # 1 条新增 buy 订单
    new_orders = [_make_order(101, "buy", 105.0, 1.0, 0.1, actual_qty=1.0)]
    instance = _make_mock_instance()
    engine = PnlAccountingEngine()

    with patch("services.pnl_accounting_engine.SessionLocal") as mock_session_local:
        # warm up（5 轮，让 MagicMock 内部缓存生效）
        for _ in range(5):
            mock_session_local.return_value = _make_incremental_mock_db(
                new_orders, instance=instance, latest_pnl=latest
            )
            await engine.incremental_update(strategy_instance_id=1, client=None)

        # 测量 10 轮取最小值
        times = []
        for _ in range(10):
            mock_session_local.return_value = _make_incremental_mock_db(
                new_orders, instance=instance, latest_pnl=latest
            )
            start = time.perf_counter()
            snapshot = await engine.incremental_update(strategy_instance_id=1, client=None)
            times.append((time.perf_counter() - start) * 1000)

    elapsed_ms = min(times)
    avg_ms = sum(times) / len(times)

    print(f"\n[perf] incremental_update 1 order: min={elapsed_ms:.3f}ms, avg={avg_ms:.3f}ms (10 iters)")
    assert snapshot is not None
    assert snapshot.order_count == 6  # 5 base + 1 new
    assert elapsed_ms < 5.0, f"单条订单 incremental_update 耗时 {elapsed_ms:.2f}ms 超过 5ms 基准"


@pytest.mark.asyncio
async def test_incremental_update_10_orders():
    """10 条订单 incremental_update 耗时 < 10ms。"""
    latest = MagicMock()
    latest.realized_pnl = 10.0
    latest.net_position = 2.0
    latest.avg_buy_price = 100.0
    latest.total_fee = 0.5
    latest.order_count = 5
    latest.equity = 5000.0

    new_orders = _generate_orders(10)
    instance = _make_mock_instance()
    mock_db = _make_incremental_mock_db(new_orders, instance=instance, latest_pnl=latest)

    engine = PnlAccountingEngine()
    with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
        start = time.perf_counter()
        snapshot = await engine.incremental_update(strategy_instance_id=1, client=None)
        elapsed_ms = (time.perf_counter() - start) * 1000

    print(f"\n[perf] incremental_update 10 orders: {elapsed_ms:.3f}ms")
    assert snapshot is not None
    assert snapshot.order_count == 15  # 5 base + 10 new
    assert elapsed_ms < 10.0, f"10 条订单 incremental_update 耗时 {elapsed_ms:.2f}ms 超过 10ms"


# ============================================================
# 基准测试：_compute_pnl_metrics 纯计算耗时（附加）
# ============================================================


def test_compute_pnl_metrics_1000_orders():
    """_compute_pnl_metrics 纯计算 1000 条订单 < 50ms。

    隔离 DB 查询开销，测量掌柜算法核心计算的 CPU 性能。
    """
    orders = _generate_orders(1000)
    buy_orders = [o for o in orders if o.side == "buy"]
    sell_orders = [o for o in orders if o.side == "sell"]

    # warm up
    PnlAccountingEngine._compute_pnl_metrics(buy_orders, sell_orders, orders)

    start = time.perf_counter()
    for _ in range(10):
        PnlAccountingEngine._compute_pnl_metrics(buy_orders, sell_orders, orders)
    elapsed_ms = (time.perf_counter() - start) * 1000 / 10

    print(f"\n[perf] _compute_pnl_metrics 1000 orders: {elapsed_ms:.3f}ms/次")
    assert elapsed_ms < 50.0, f"_compute_pnl_metrics 1000 orders 耗时 {elapsed_ms:.2f}ms 超过 50ms"
