"""heartbeat_snapshot 默认值心跳单元测试。

覆盖策略运行时无成交也能定期写入心跳 PnlRecord 的三种场景：
1. 无基准 PnlRecord 且无成交订单 → 写一条全零初始心跳
2. 有基准 PnlRecord 但无新成交 → 正常写心跳（复用基准值，用当前价重算 unrealized_pnl）
3. 行情获取失败 → unrealized_pnl=0，仍写心跳（不中断）

导入风格与 mock 约定参考 test_pnl_curve_fix.py。
"""
import sys
import os
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.pnl_accounting_engine import PnlAccountingEngine, PnlSnapshot
from models.order import Order
from models.pnl import PnlRecord
from models.strategy import StrategyInstance


# ---------------------------------------------------------------------------
# 辅助函数：构造 mock StrategyInstance / mock DB session
# ---------------------------------------------------------------------------

def _make_instance(account_id=1, symbol="BTC-USDT", params=None):
    """构造 mock StrategyInstance。"""
    inst = MagicMock()
    inst.account_id = account_id
    inst.symbol = symbol
    inst.params = params if params is not None else {"fee_rate": 0.001}
    return inst


def _make_heartbeat_mock_db(instance=None, latest_pnl=None, orders=None):
    """构造 mock DB session，适配 heartbeat_snapshot 的查询链路。

    heartbeat_snapshot 涉及的 query 链路：
      - StrategyInstance: .filter().first()
      - PnlRecord: .filter().order_by().first()
      - Order: .filter().filter().all()  （recompute 兜底时查询 filled 订单）

    orders 默认为空列表，模拟无成交场景。
    """
    if orders is None:
        orders = []
    mock_db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        if model is StrategyInstance:
            chain.filter.return_value.first.return_value = instance
        elif model is PnlRecord:
            chain.filter.return_value.order_by.return_value.first.return_value = latest_pnl
        elif model is Order:
            # recompute 查询 Order 时返回指定订单列表（默认空 → recompute 返回 None）
            chain.filter.return_value.filter.return_value.all.return_value = orders
        return chain

    mock_db.query.side_effect = query_side_effect
    return mock_db


# ===========================================================================
# 1. 无基准 PnlRecord 且无成交订单 → 写全零初始心跳
# ===========================================================================
class TestHeartbeatNoBaselineNoOrders:
    @pytest.mark.asyncio
    async def test_heartbeat_no_baseline_no_orders_writes_zero(self):
        """无基准 PnlRecord 且无成交订单时，heartbeat_snapshot 写一条全零初始心跳。

        修复前：recompute 返回 None 时 heartbeat 也返回 None，不写记录。
        修复后：用全零默认值写一条心跳，确保盈亏曲线有持续数据点。
        """
        instance = _make_instance(account_id=1, symbol="BTC-USDT")
        mock_db = _make_heartbeat_mock_db(instance=instance, latest_pnl=None, orders=[])

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            snapshot = await engine.heartbeat_snapshot(strategy_instance_id=1, client=None)

        # 应返回 PnlSnapshot 而非 None
        assert snapshot is not None
        assert isinstance(snapshot, PnlSnapshot)
        # 所有字段均为零/默认值
        assert snapshot.realized_pnl == pytest.approx(0.0, abs=1e-12)
        assert snapshot.unrealized_pnl == pytest.approx(0.0, abs=1e-12)
        assert snapshot.total_pnl == pytest.approx(0.0, abs=1e-12)
        assert snapshot.net_position == pytest.approx(0.0, abs=1e-12)
        assert snapshot.avg_buy_price == pytest.approx(0.0, abs=1e-12)
        assert snapshot.total_fee == pytest.approx(0.0, abs=1e-12)
        assert snapshot.order_count == 0
        assert snapshot.equity == pytest.approx(0.0, abs=1e-12)
        # 写入一条 PnlRecord 并提交
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()


# ===========================================================================
# 2. 有基准 PnlRecord 但无新成交 → 正常写心跳（重算 unrealized_pnl）
# ===========================================================================
class TestHeartbeatWithBaseline:
    @pytest.mark.asyncio
    async def test_heartbeat_with_baseline_updates_unrealized(self):
        """有基准 PnlRecord 时，复用基准累计值并用当前价重算 unrealized_pnl。

        基准: realized=10, net_position=2, avg_buy=100, total_fee=0.5, order_count=5, equity=5000
        当前价: 120, fee_rate=0.001
        unrealized = (120-100)*2 - 2*120*0.001 = 40 - 0.24 = 39.76
        total_pnl = 10 + 39.76 = 49.76
        """
        latest = MagicMock()
        latest.realized_pnl = 10.0
        latest.net_position = 2.0
        latest.avg_buy_price = 100.0
        latest.total_fee = 0.5
        latest.order_count = 5
        latest.equity = 5000.0

        instance = _make_instance(account_id=1, symbol="BTC-USDT", params={"fee_rate": 0.001})
        mock_db = _make_heartbeat_mock_db(instance=instance, latest_pnl=latest)

        # mock OKX client：get_ticker 返回当前价 120
        mock_client = MagicMock()
        mock_client.get_ticker = AsyncMock(return_value=[{"last": "120"}])

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            snapshot = await engine.heartbeat_snapshot(strategy_instance_id=1, client=mock_client)

        assert snapshot is not None
        assert isinstance(snapshot, PnlSnapshot)
        # realized_pnl 沿用最新记录
        assert snapshot.realized_pnl == pytest.approx(10.0, rel=1e-9)
        # unrealized_pnl 基于当前价重新计算
        assert snapshot.unrealized_pnl == pytest.approx(39.76, rel=1e-9)
        assert snapshot.total_pnl == pytest.approx(49.76, rel=1e-9)
        # 累计字段沿用基准
        assert snapshot.net_position == pytest.approx(2.0, rel=1e-9)
        assert snapshot.avg_buy_price == pytest.approx(100.0, rel=1e-9)
        assert snapshot.total_fee == pytest.approx(0.5, rel=1e-9)
        assert snapshot.order_count == 5
        assert snapshot.equity == pytest.approx(5000.0, rel=1e-9)
        # 写入新 PnlRecord 并提交
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()


# ===========================================================================
# 3. 行情获取失败 → unrealized_pnl=0，仍写心跳（不中断）
# ===========================================================================
class TestHeartbeatMarketError:
    @pytest.mark.asyncio
    async def test_heartbeat_market_error_writes_zero_unrealized(self):
        """行情获取失败时，unrealized_pnl=0，仍写心跳记录（不中断）。

        基准: realized=10, net_position=2, avg_buy=100（有持仓，需取行情）
        mock client.get_ticker 抛异常 → _get_current_price 返回 0.0
        → unrealized_pnl 保持 0.0，心跳照常写入。
        """
        latest = MagicMock()
        latest.realized_pnl = 10.0
        latest.net_position = 2.0
        latest.avg_buy_price = 100.0
        latest.total_fee = 0.5
        latest.order_count = 5
        latest.equity = 5000.0

        instance = _make_instance(account_id=1, symbol="BTC-USDT", params={"fee_rate": 0.001})
        mock_db = _make_heartbeat_mock_db(instance=instance, latest_pnl=latest)

        # mock OKX client：get_ticker 抛异常模拟行情获取失败
        mock_client = MagicMock()
        mock_client.get_ticker = AsyncMock(side_effect=Exception("market data unavailable"))

        engine = PnlAccountingEngine()
        # 屏蔽 _record_event 避免 market_data_unavailable 事件干扰 mock_db.add 计数
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db), \
             patch.object(engine, "_record_event"):
            snapshot = await engine.heartbeat_snapshot(strategy_instance_id=1, client=mock_client)

        assert snapshot is not None
        assert isinstance(snapshot, PnlSnapshot)
        # 行情失败 → unrealized_pnl=0
        assert snapshot.unrealized_pnl == pytest.approx(0.0, abs=1e-12)
        # realized_pnl 沿用基准
        assert snapshot.realized_pnl == pytest.approx(10.0, rel=1e-9)
        # total_pnl = realized + unrealized = 10 + 0 = 10
        assert snapshot.total_pnl == pytest.approx(10.0, rel=1e-9)
        # 累计字段沿用基准
        assert snapshot.net_position == pytest.approx(2.0, rel=1e-9)
        assert snapshot.avg_buy_price == pytest.approx(100.0, rel=1e-9)
        # 心跳照常写入（不中断）
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
