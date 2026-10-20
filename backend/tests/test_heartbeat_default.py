from test_pnl_execution_regressions import ledger, trade, market
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
# 1. 无基准 PnlRecord 且无成交订单 → 返回内存零快照，不落库
# ===========================================================================
class TestHeartbeatNoBaselineNoOrders:
    @pytest.mark.asyncio
    async def test_heartbeat_no_baseline_no_orders_writes_zero(self):
        """无基准 PnlRecord 且无成交订单时，heartbeat_snapshot 返回内存零快照且不写库。

        P0：新建策略零基线——无成交不写入全零 PnlRecord，避免污染曲线与账户汇总。
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
        # 不写入 PnlRecord
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()


# ===========================================================================
# 2. 有基准 PnlRecord 但无新成交 → 正常写心跳（重算 unrealized_pnl）
# ===========================================================================
class TestHeartbeatWithBaseline:
    @pytest.mark.asyncio
    async def test_heartbeat_with_baseline_updates_unrealized(self, ledger):
        db, engine = ledger
        trade(db, "buy", 100, 2)
        await engine.heartbeat_snapshot(1, market(120))
        snapshot = await engine.heartbeat_snapshot(1, market(110))
        assert snapshot.realized_pnl == 0
        assert snapshot.unrealized_pnl == 20


class TestHeartbeatMarketError:
    @pytest.mark.asyncio
    async def test_heartbeat_market_error_writes_zero_unrealized(self, ledger):
        """A failed valuation must not erase the last valid profit."""
        db, engine = ledger
        trade(db, "buy", 100, 2)
        await engine.heartbeat_snapshot(1, market(120))
        with pytest.raises(ValueError, match="current market price"):
            await engine.heartbeat_snapshot(1, market(0))
        assert db.query(PnlRecord).count() == 1
        assert db.query(PnlRecord).first().total_pnl == 40
