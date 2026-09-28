"""P0：账户 PnL 聚合、零基线、clOrdId 幂等、total_pnl 不变量、恢复状态视图。"""
import sys
import os
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from routers.pnl import get_pnl_summary
from services.order_ids import generate_cl_ord_id
from services.pnl_accounting_engine import compose_total_pnl
from services.strategy_engine import StrategyEngine


def _rec(**kwargs):
    base = dict(
        id=1,
        account_id=1,
        strategy_instance_id=1,
        realized_pnl=0,
        unrealized_pnl=0,
        total_pnl=0,
        equity=0,
        net_position=0,
        avg_buy_price=0,
        total_fee=0,
        order_count=0,
        recorded_at=datetime.now(timezone.utc),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _mock_db(records):
    mock_db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = records
    mock_db.query.return_value = q
    return mock_db


class TestAccountPnlSum:
    def test_account_sum_latest_by_strategy(self):
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        records = [
            _rec(id=4, strategy_instance_id=1, realized_pnl=10, unrealized_pnl=5, total_pnl=15,
                 equity=100, net_position=1, order_count=2, recorded_at=t0 + timedelta(seconds=30)),
            _rec(id=3, strategy_instance_id=2, realized_pnl=20, unrealized_pnl=8, total_pnl=28,
                 equity=200, net_position=2, order_count=3, recorded_at=t0 + timedelta(seconds=20)),
            _rec(id=2, strategy_instance_id=1, realized_pnl=1, unrealized_pnl=1, total_pnl=2,
                 equity=50, net_position=1, order_count=1, recorded_at=t0),
        ]
        result = get_pnl_summary(account_id=1, strategy_instance_id=None, db=_mock_db(records), user=MagicMock())
        assert result["total_realized_pnl"] == 10 + 20
        assert result["total_unrealized_pnl"] == 5 + 8
        assert result["total_pnl"] == 43
        assert result["latest_equity"] == 100 + 200
        assert len(result["by_strategy"]) == 2


class TestComposeTotalPnl:
    def test_compose_total_pnl_invariant(self):
        assert compose_total_pnl(10, 5) == 15
        assert compose_total_pnl(None, 3) == 3
        assert compose_total_pnl(2, None) == 2


class TestClOrdId:
    def test_generate_cl_ord_id_constraints(self):
        cid = generate_cl_ord_id(42)
        assert cid.isalnum()
        assert 1 <= len(cid) <= 32
        assert len({generate_cl_ord_id(1) for _ in range(20)}) == 20

    @pytest.mark.asyncio
    async def test_place_order_injects_cl_ord_id(self):
        from services.okx_client import OKXClient

        client = OKXClient.__new__(OKXClient)
        client._ensure_time_synced = AsyncMock()
        client.trade = MagicMock()
        client.trade.place_order = AsyncMock(return_value={"code": "0", "data": [{"ordId": "oid1", "sCode": "0"}]})

        resp = await OKXClient.place_order(client, inst_id="BTC-USDT", side="buy", ord_type="limit", sz="1", px="100")
        kwargs = client.trade.place_order.await_args.kwargs
        assert "clOrdId" in kwargs
        assert kwargs["clOrdId"]
        assert resp["data"][0]["clOrdId"] == kwargs["clOrdId"]
        assert resp["_clOrdId"] == kwargs["clOrdId"]


class TestStatusView:
    def test_status_view_detects_drift(self):
        engine = StrategyEngine()
        saved = dict(StrategyEngine._tasks)
        StrategyEngine._tasks.clear()
        try:
            view = engine.get_status_view(1, desired_status="running", db_status="running")
            assert view["runtime_status"] == "stopped"
            assert view["status_drift"] is True
            assert view["desired_status"] == "running"
            assert view["status"] == "degraded"
        finally:
            StrategyEngine._tasks.clear()
            StrategyEngine._tasks.update(saved)
