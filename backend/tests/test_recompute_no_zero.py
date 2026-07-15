"""Task 2 测试：recompute 无成交不写全 0 记录（spec: fix-pnl-attribution-qsm-loop）。

覆盖：
- recompute 无 filled 订单时返回 None，不写 PnlRecord
- recompute 有 filled 订单时正常写入
- heartbeat_snapshot 无基准记录时调 recompute 兜底
- heartbeat_snapshot recompute 也返回 None 时返回 None

导入风格参考 test_pnl_accounting_engine.py：顶部注入 backend 根目录到 sys.path。
"""
import sys
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.pnl_accounting_engine import PnlAccountingEngine, PnlSnapshot
from models.order import Order
from models.pnl import PnlRecord
from models.strategy import StrategyInstance


# ---------------------------------------------------------------------------
# 辅助函数：构造 mock Order / mock StrategyInstance / mock DB session
# ---------------------------------------------------------------------------

def _make_order(id, side, px, qty, fee, actual_qty=None, symbol="BTC-USDT"):
    """构造 mock Order 对象，模拟 filled 订单。"""
    o = MagicMock()
    o.id = id
    o.side = side
    o.fill_px = px
    o.fill_sz = qty
    o.actual_qty = actual_qty
    o.filled_quantity = None
    o.quantity = None
    o.fee = fee
    o.symbol = symbol
    o.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return o


def _make_instance(account_id=1, symbol="BTC-USDT", params=None):
    """构造 mock StrategyInstance。"""
    inst = MagicMock()
    inst.account_id = account_id
    inst.symbol = symbol
    inst.params = params if params is not None else {"fee_rate": 0.001}
    return inst


def _make_recompute_mock_db(orders, instance=None, latest_pnl=None):
    """构造 mock DB session，适配 recompute 的查询链路。

    recompute 涉及的 query 链路：
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


def _make_heartbeat_mock_db(instance=None, latest_pnl=None):
    """构造 mock DB session，适配 heartbeat_snapshot 的查询链路。

    heartbeat_snapshot 涉及的 query 链路：
      - StrategyInstance: .filter().first()
      - PnlRecord: .filter().order_by().first()
    """
    mock_db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        if model is StrategyInstance:
            chain.filter.return_value.first.return_value = instance
        elif model is PnlRecord:
            chain.filter.return_value.order_by.return_value.first.return_value = latest_pnl
        return chain

    mock_db.query.side_effect = query_side_effect
    return mock_db


# ===========================================================================
# 1. SubTask 2.1: recompute 无成交返回 None 不写库
# ===========================================================================
class TestRecomputeNoFilled:
    @pytest.mark.asyncio
    async def test_recompute_no_filled_returns_none(self):
        """无 filled 订单时 recompute 返回 None，不写 PnlRecord"""
        instance = _make_instance()
        mock_db = _make_recompute_mock_db([], instance=instance, latest_pnl=None)

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            result = await engine.recompute(strategy_instance_id=1, client=None)

        # 返回 None
        assert result is None
        # 不写 PnlRecord
        mock_db.add.assert_not_called()
        # 不提交
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_recompute_with_filled_writes_record(self):
        """有 filled 订单时 recompute 正常写入 PnlRecord"""
        orders = [
            _make_order(1, "buy", 100.0, 1.0, 0.1, actual_qty=1.0),
            _make_order(2, "sell", 110.0, 1.0, 0.1, actual_qty=1.0),
        ]
        instance = _make_instance()
        mock_db = _make_recompute_mock_db(orders, instance=instance, latest_pnl=None)

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            snapshot = await engine.recompute(strategy_instance_id=1, client=None)

        # 返回 PnlSnapshot
        assert isinstance(snapshot, PnlSnapshot)
        # 写入并提交
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()


# ===========================================================================
# 2. SubTask 2.2: heartbeat_snapshot 无基准调 recompute 兜底
# ===========================================================================
class TestHeartbeatFallback:
    @pytest.mark.asyncio
    async def test_heartbeat_no_latest_calls_recompute(self):
        """无基准 PnlRecord 时调 recompute 兜底，返回 recompute 的 snapshot"""
        instance = _make_instance()
        # heartbeat 的 DB 查询：StrategyInstance → instance, PnlRecord latest → None
        mock_db = _make_heartbeat_mock_db(instance=instance, latest_pnl=None)

        expected_snapshot = PnlSnapshot(
            strategy_instance_id=1,
            realized_pnl=10.0,
            unrealized_pnl=5.0,
            total_pnl=15.0,
            equity=1000.0,
            net_position=1.0,
            avg_buy_price=100.0,
            total_fee=0.2,
            order_count=2,
            recorded_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db), \
             patch.object(engine, "recompute", new_callable=AsyncMock, return_value=expected_snapshot) as mock_recompute:
            result = await engine.heartbeat_snapshot(strategy_instance_id=1, client=None)

        # 返回 recompute 的 snapshot
        assert result is expected_snapshot
        # recompute 被调用兜底
        mock_recompute.assert_awaited_once_with(1, None)
        # heartbeat 自身不写 PnlRecord（recompute 已写）
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_recompute_none_returns_zero_snapshot(self):
        """无基准且 recompute 也返回 None（无成交）时 heartbeat 写全零初始心跳

        确保盈亏曲线有持续数据点，避免策略运行很久却只有 1 条记录。
        """
        instance = _make_instance()
        mock_db = _make_heartbeat_mock_db(instance=instance, latest_pnl=None)

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db), \
             patch.object(engine, "recompute", new_callable=AsyncMock, return_value=None) as mock_recompute:
            result = await engine.heartbeat_snapshot(strategy_instance_id=1, client=None)

        # 返回全零快照（而非 None）
        assert result is not None
        assert result.realized_pnl == 0.0
        assert result.unrealized_pnl == 0.0
        assert result.total_pnl == 0.0
        assert result.net_position == 0.0
        assert result.order_count == 0
        # recompute 被调用兜底
        mock_recompute.assert_awaited_once_with(1, None)
        # 写入全零 PnlRecord
        mock_db.add.assert_called_once()


# ===========================================================================
# 3. SubTask 2.4: recompute API 端点处理 None
# ===========================================================================
class TestRecomputeEndpointNone:
    @pytest.mark.asyncio
    async def test_recompute_endpoint_no_filled_returns_message(self):
        """recompute 返回 None 时端点返回 {success: false, message: 无成交订单}"""
        from routers.pnl import recompute_pnl
        from services.pnl_accounting_engine import pnl_accounting_engine

        mock_client = MagicMock()

        with patch.object(
            pnl_accounting_engine, "_get_client", new_callable=AsyncMock, return_value=mock_client
        ), patch.object(
            pnl_accounting_engine, "recompute", new_callable=AsyncMock, return_value=None
        ) as mock_recompute:
            result = await recompute_pnl(
                strategy_id=1,
                request=MagicMock(),
                db=MagicMock(),
                user=MagicMock(),
            )

        # recompute 被调用
        mock_recompute.assert_awaited_once_with(1, mock_client)
        # 返回失败信息
        assert result == {"success": False, "message": "无成交订单"}
