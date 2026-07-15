"""Task 3 测试：summary 跳过全 0 记录与行情告警（spec: fix-pnl-attribution-qsm-loop）。

覆盖：
- SubTask 3.1: get_pnl_summary 跳过全 0 无意义记录，向前追溯有效记录
- SubTask 3.2: _get_current_price 失败时记录 market_data_unavailable 事件
- SubTask 3.3: avg_buy_price=0 且 net_position>0 时记录 pnl_anomaly_zero_avg_buy 事件

导入风格与 mock 约定参考 test_pnl_curve_fix.py / test_recompute_no_zero.py。
"""
import sys
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.pnl_accounting_engine import PnlAccountingEngine
from models.pnl import PnlRecord
from models.strategy import StrategyInstance


# ---------------------------------------------------------------------------
# 辅助函数：构造 mock PnlRecord / mock DB session
# ---------------------------------------------------------------------------

def _make_pnl_record(
    id=1,
    account_id=1,
    strategy_instance_id=1,
    realized_pnl=0.0,
    unrealized_pnl=0.0,
    total_pnl=0.0,
    equity=0.0,
    net_position=0.0,
    avg_buy_price=0.0,
    total_fee=0.0,
    order_count=0,
    recorded_at=None,
):
    """构造 mock PnlRecord 对象（SimpleNamespace 模拟 ORM 行）。"""
    return SimpleNamespace(
        id=id,
        account_id=account_id,
        strategy_instance_id=strategy_instance_id,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_pnl=total_pnl,
        equity=equity,
        is_final=False,
        net_position=net_position,
        avg_buy_price=avg_buy_price,
        total_fee=total_fee,
        order_count=order_count,
        recorded_at=recorded_at or datetime.now(timezone.utc),
    )


def _make_summary_mock_db(records):
    """构造适配 get_pnl_summary 查询链路的 mock DB。

    链路: db.query(PnlRecord).filter(...).order_by(...).limit(...).all() -> records
    filter 链式可叠加（account_id / strategy_instance_id 均可选）。
    """
    mock_db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = records
    mock_db.query.return_value = q
    return mock_db


def _make_heartbeat_mock_db(instance=None, latest_pnl=None):
    """构造适配 heartbeat_snapshot 查询链路的 mock DB。

    链路:
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
# SubTask 3.1: get_pnl_summary 跳过全 0 无意义记录
# ===========================================================================
class TestSummarySkipAllZero:
    def test_summary_skips_all_zero_record(self):
        """latest 是全 0 记录，前一条非 0 → summary 使用前一条数据。"""
        from routers.pnl import get_pnl_summary

        t_old = datetime(2024, 1, 1, tzinfo=timezone.utc)
        t_new = datetime(2024, 1, 2, tzinfo=timezone.utc)
        # 新的是全 0，旧的是有效记录
        records = [
            _make_pnl_record(
                id=2, realized_pnl=0, unrealized_pnl=0, total_pnl=0,
                net_position=0, order_count=0, equity=0,
                recorded_at=t_new,
            ),
            _make_pnl_record(
                id=1, realized_pnl=100, unrealized_pnl=20, total_pnl=120,
                net_position=2, order_count=3, equity=5000, avg_buy_price=100,
                recorded_at=t_old,
            ),
        ]
        mock_db = _make_summary_mock_db(records)

        result = get_pnl_summary(
            account_id=1,
            strategy_instance_id=None,
            db=mock_db,
            user=MagicMock(),
        )
        # summary 基准应为旧的有效记录
        assert result["total_realized_pnl"] == 100
        assert result["total_unrealized_pnl"] == 20
        assert result["total_pnl"] == 120
        assert result["latest_equity"] == 5000

    def test_summary_all_zero_no_fallback(self):
        """所有 PnlRecord 都是全 0 → summary 返回全 0（不报错）。"""
        from routers.pnl import get_pnl_summary

        t1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2024, 1, 2, tzinfo=timezone.utc)
        records = [
            _make_pnl_record(
                id=2, realized_pnl=0, unrealized_pnl=0, total_pnl=0,
                net_position=0, order_count=0, equity=0,
                recorded_at=t2,
            ),
            _make_pnl_record(
                id=1, realized_pnl=0, unrealized_pnl=0, total_pnl=0,
                net_position=0, order_count=0, equity=0,
                recorded_at=t1,
            ),
        ]
        mock_db = _make_summary_mock_db(records)

        result = get_pnl_summary(
            account_id=1,
            strategy_instance_id=None,
            db=mock_db,
            user=MagicMock(),
        )
        # 全 0，不报错
        assert result["total_realized_pnl"] == 0
        assert result["total_unrealized_pnl"] == 0
        assert result["total_pnl"] == 0
        assert result["latest_equity"] == 0

    def test_summary_no_records(self):
        """无 PnlRecord → summary 返回空/默认值。"""
        from routers.pnl import get_pnl_summary

        mock_db = _make_summary_mock_db([])

        result = get_pnl_summary(
            account_id=1,
            strategy_instance_id=None,
            db=mock_db,
            user=MagicMock(),
        )
        assert result == {
            "total_realized_pnl": 0,
            "total_unrealized_pnl": 0,
            "total_pnl": 0,
            "latest_equity": 0,
            "by_strategy": [],
        }


# ===========================================================================
# SubTask 3.2: _get_current_price 失败记录 market_data_unavailable 事件
# ===========================================================================
class TestMarketDataUnavailableEvent:
    @pytest.mark.asyncio
    async def test_market_data_unavailable_event(self):
        """_get_current_price 抛异常时记录 market_data_unavailable 事件，不中断主流程。"""
        engine = PnlAccountingEngine()

        mock_client = MagicMock()
        mock_client.get_ticker = AsyncMock(side_effect=RuntimeError("connect timeout"))

        with patch.object(engine, "_record_event") as mock_record:
            price = await engine._get_current_price(
                "BTC-USDT", mock_client, strategy_instance_id=42
            )

        # 不中断主流程，返回 0
        assert price == 0.0
        # 记录 market_data_unavailable 事件
        mock_record.assert_called_once()
        args, _ = mock_record.call_args
        # 签名: (strategy_instance_id, event_type, message, details)
        assert args[0] == 42
        assert args[1] == "market_data_unavailable"
        assert "BTC-USDT" in args[2]
        details = args[3]
        assert details["symbol"] == "BTC-USDT"
        assert "connect timeout" in details["reason"]


# ===========================================================================
# SubTask 3.3: avg_buy_price=0 且 net_position>0 记录 pnl_anomaly_zero_avg_buy 事件
# ===========================================================================
class TestPnlAnomalyZeroAvgBuyEvent:
    @pytest.mark.asyncio
    async def test_pnl_anomaly_zero_avg_buy_event(self):
        """avg_buy_price=0 且 net_position>0 时记录 pnl_anomaly_zero_avg_buy 事件。

        使用 heartbeat_snapshot 触发兜底分支：基准 avg_buy_price=0, net_position=2，
        当前价 50000 → 命中 avg_buy_price=0 && net_position>0 兜底。
        """
        latest = MagicMock()
        latest.realized_pnl = 5.0
        latest.net_position = 2.0
        latest.avg_buy_price = 0.0  # 异常基准
        latest.total_fee = 0.3
        latest.order_count = 3
        latest.equity = 1000.0

        instance = MagicMock()
        instance.account_id = 1
        instance.symbol = "BTC-USDT"
        instance.params = {"fee_rate": 0.001}

        mock_db = _make_heartbeat_mock_db(instance=instance, latest_pnl=latest)

        mock_client = MagicMock()
        mock_client.get_ticker = AsyncMock(return_value=[{"last": "50000"}])

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db), \
             patch.object(engine, "_record_event") as mock_record:
            snapshot = await engine.heartbeat_snapshot(
                strategy_instance_id=1, client=mock_client
            )

        assert snapshot is not None
        # 兜底生效：unrealized_pnl=0
        assert snapshot.unrealized_pnl == pytest.approx(0.0, abs=1e-12)
        # 记录 pnl_anomaly_zero_avg_buy 事件
        mock_record.assert_called_once()
        args, _ = mock_record.call_args
        assert args[0] == 1  # strategy_instance_id
        assert args[1] == "pnl_anomaly_zero_avg_buy"
        details = args[3]
        assert details["strategy_instance_id"] == 1
        assert details["symbol"] == "BTC-USDT"
        assert details["net_position"] == 2.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
