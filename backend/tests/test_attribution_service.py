"""PnL 归因分析服务的单元测试。

覆盖：
- get_attribution_by_symbol：按币种聚合 realized_pnl / fee / trade_count / win_rate
- get_attribution_by_strategy_type：按策略类型聚合（关联 strategy_type）
- get_attribution_by_period：按时间段聚合（daily/weekly/monthly）
- get_drill_down：下钻查看订单明细（symbol / strategy_type 过滤）
- _max_drawdown 辅助函数

导入风格参考 conftest.py 与 test_pnl_algorithm_fix.py：顶部注入 backend 根目录到 sys.path。
DB 查询使用 MagicMock 模拟 SQLAlchemy session 的链式调用。
"""
import sys
import os
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.attribution_service import AttributionService, _max_drawdown
from models.order import Order
from models.pnl import PnlRecord
from models.strategy import StrategyInstance, StrategyTemplate


# ---------------------------------------------------------------------------
# 工厂函数：构造 mock 模型实例（SimpleNamespace 模拟 ORM 对象属性）
# ---------------------------------------------------------------------------
def make_order(symbol="BTC-USDT", side="buy", status="filled", fill_px=100.0,
               fill_sz=1.0, fee=0.1, created_at=None, strategy_instance_id=1,
               account_id=1, order_id=1):
    return SimpleNamespace(
        id=order_id,
        symbol=symbol,
        side=side,
        status=status,
        order_type="limit",
        price=fill_px,
        fill_px=fill_px,
        fill_sz=fill_sz,
        filled_quantity=fill_sz or 0,
        fee=fee,
        state=None,
        strategy_instance_id=strategy_instance_id,
        account_id=account_id,
        created_at=created_at or datetime.now(timezone.utc),
        updated_at=created_at or datetime.now(timezone.utc),
    )


def make_pnl_record(realized_pnl=0.0, unrealized_pnl=0.0, recorded_at=None,
                    strategy_instance_id=1, account_id=1, order_count=0, equity=0.0):
    return SimpleNamespace(
        id=1,
        account_id=account_id,
        strategy_instance_id=strategy_instance_id,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_pnl=realized_pnl + unrealized_pnl,
        equity=equity,
        order_count=order_count,
        recorded_at=recorded_at or datetime.now(timezone.utc),
        is_final=False,
        net_position=0,
        avg_buy_price=0,
        total_fee=0,
    )


def make_instance(inst_id=1, template_id=1, account_id=1, symbol="BTC-USDT"):
    return SimpleNamespace(
        id=inst_id,
        template_id=template_id,
        account_id=account_id,
        name=f"inst-{inst_id}",
        symbol=symbol,
        market_type="spot",
        params={},
        status="stopped",
    )


def make_template(tpl_id=1, strategy_type="grid"):
    return SimpleNamespace(
        id=tpl_id,
        name="tpl",
        strategy_type=strategy_type,
        description=None,
        default_params={},
        param_schema=None,
        is_builtin=True,
        is_custom=False,
    )


def make_mock_db(orders=None, pnl_records=None, instances=None, templates=None):
    """构造一个 mock db，query() 返回链式可调用的 mock。

    .filter() / .order_by() / .limit() / .join() 均返回自身，.all() 返回预设列表。
    根据查询的模型类名返回对应的预设数据。
    """
    db = MagicMock()

    def query(model):
        q = MagicMock()
        # 链式调用返回自身
        q.filter.return_value = q
        q.order_by.return_value = q
        q.limit.return_value = q
        q.join.return_value = q
        name = getattr(model, "__name__", "")
        if name == "Order":
            q.all.return_value = orders or []
        elif name == "PnlRecord":
            q.all.return_value = pnl_records or []
        elif name == "StrategyInstance":
            q.all.return_value = instances or []
        elif name == "StrategyTemplate":
            q.all.return_value = templates or []
        else:
            q.all.return_value = []
        return q

    db.query.side_effect = query
    return db


# ---------------------------------------------------------------------------
# 测试：按币种聚合
# ---------------------------------------------------------------------------
class TestAttributionBySymbol:
    def test_aggregates_realized_pnl_and_fee(self):
        """两个 symbol，验证 realized_pnl / fee / trade_count 正确聚合。"""
        now = datetime.now(timezone.utc)
        # BTC: 买入 2@100 (notional=200), 卖出 1@110 -> realized=(110-100)*1=10
        # ETH: 买入 1@50, 卖出 1@45 -> realized=(45-50)*1=-5
        orders = [
            make_order(symbol="BTC-USDT", side="buy", fill_px=100, fill_sz=2, fee=0.2, created_at=now, order_id=1),
            make_order(symbol="BTC-USDT", side="sell", fill_px=110, fill_sz=1, fee=0.1, created_at=now, order_id=2),
            make_order(symbol="ETH-USDT", side="buy", fill_px=50, fill_sz=1, fee=0.05, created_at=now, order_id=3),
            make_order(symbol="ETH-USDT", side="sell", fill_px=45, fill_sz=1, fee=0.05, created_at=now, order_id=4),
        ]
        db = make_mock_db(orders=orders)
        svc = AttributionService()

        result = svc.get_attribution_by_symbol(db, account_id=1,
                                                start_date="2026-07-01T00:00:00",
                                                end_date="2026-07-11T23:59:59")

        assert len(result) == 2
        # 按 realized_pnl 降序，BTC(10) 在前
        btc = next(r for r in result if r["symbol"] == "BTC-USDT")
        eth = next(r for r in result if r["symbol"] == "ETH-USDT")
        assert btc["realized_pnl"] == pytest.approx(10.0, abs=1e-4)
        assert btc["fee"] == pytest.approx(0.3, abs=1e-6)
        assert btc["trade_count"] == 2
        # BTC 卖出价 110 > 均价 100 -> 胜率 1.0
        assert btc["win_rate"] == pytest.approx(1.0, abs=1e-4)
        # ETH 卖出价 45 < 均价 50 -> 胜率 0.0
        assert eth["realized_pnl"] == pytest.approx(-5.0, abs=1e-4)
        assert eth["fee"] == pytest.approx(0.1, abs=1e-6)
        assert eth["win_rate"] == pytest.approx(0.0, abs=1e-4)
        # 降序校验
        assert result[0]["realized_pnl"] >= result[1]["realized_pnl"]

    def test_empty_orders_returns_empty_list(self):
        db = make_mock_db(orders=[])
        svc = AttributionService()
        result = svc.get_attribution_by_symbol(db, account_id=1,
                                               start_date="2026-07-01T00:00:00",
                                               end_date="2026-07-11T23:59:59")
        assert result == []

    def test_non_filled_orders_excluded(self):
        """canceled 订单不纳入聚合。"""
        now = datetime.now(timezone.utc)
        orders = [
            make_order(symbol="BTC-USDT", side="buy", status="canceled", fill_px=100, fill_sz=1, created_at=now, order_id=1),
            make_order(symbol="BTC-USDT", side="sell", status="filled", fill_px=110, fill_sz=1, created_at=now, order_id=2),
        ]
        db = make_mock_db(orders=orders)
        svc = AttributionService()
        result = svc.get_attribution_by_symbol(db, account_id=1,
                                               start_date="2026-07-01T00:00:00",
                                               end_date="2026-07-11T23:59:59")
        # canceled 被过滤，只剩 1 笔 filled
        assert len(result) == 1
        assert result[0]["trade_count"] == 1


# ---------------------------------------------------------------------------
# 测试：按策略类型聚合
# ---------------------------------------------------------------------------
class TestAttributionByStrategyType:
    def test_aggregates_by_strategy_type(self):
        now = datetime.now(timezone.utc)
        # 两个实例：inst1=grid, inst2=trend
        instances = [make_instance(inst_id=1, template_id=1, symbol="BTC-USDT"),
                     make_instance(inst_id=2, template_id=2, symbol="ETH-USDT")]
        templates = [make_template(tpl_id=1, strategy_type="grid"),
                     make_template(tpl_id=2, strategy_type="trend")]
        # PnL 记录
        pnl_records = [
            make_pnl_record(realized_pnl=100, unrealized_pnl=20, strategy_instance_id=1, recorded_at=now),
            make_pnl_record(realized_pnl=50, unrealized_pnl=-10, strategy_instance_id=2, recorded_at=now),
        ]
        # 订单（grid: 1买1卖；trend: 1买1卖）
        orders = [
            make_order(symbol="BTC-USDT", side="buy", fill_px=100, fill_sz=1, strategy_instance_id=1, created_at=now, order_id=1),
            make_order(symbol="BTC-USDT", side="sell", fill_px=110, fill_sz=1, strategy_instance_id=1, created_at=now, order_id=2),
            make_order(symbol="ETH-USDT", side="buy", fill_px=50, fill_sz=1, strategy_instance_id=2, created_at=now, order_id=3),
            make_order(symbol="ETH-USDT", side="sell", fill_px=45, fill_sz=1, strategy_instance_id=2, created_at=now, order_id=4),
        ]
        db = make_mock_db(orders=orders, pnl_records=pnl_records, instances=instances, templates=templates)
        svc = AttributionService()

        result = svc.get_attribution_by_strategy_type(db, account_id=1,
                                                      start_date="2026-07-01T00:00:00",
                                                      end_date="2026-07-11T23:59:59")
        assert len(result) == 2
        grid = next(r for r in result if r["strategy_type"] == "grid")
        trend = next(r for r in result if r["strategy_type"] == "trend")
        # realized 来自 PnlRecord（取最新）
        assert grid["realized_pnl"] == pytest.approx(100.0, abs=1e-4)
        assert grid["unrealized_pnl"] == pytest.approx(20.0, abs=1e-4)
        assert grid["trade_count"] == 2
        # grid 卖出 110 > 均价 100 -> 胜率 1.0
        assert grid["win_rate"] == pytest.approx(1.0, abs=1e-4)
        assert trend["realized_pnl"] == pytest.approx(50.0, abs=1e-4)
        assert trend["trade_count"] == 2
        # trend 卖出 45 < 均价 50 -> 胜率 0.0
        assert trend["win_rate"] == pytest.approx(0.0, abs=1e-4)

    def test_no_instances_returns_empty(self):
        db = make_mock_db(instances=[])
        svc = AttributionService()
        result = svc.get_attribution_by_strategy_type(db, account_id=1,
                                                      start_date="2026-07-01T00:00:00",
                                                      end_date="2026-07-11T23:59:59")
        assert result == []

    def test_max_drawdown_computed(self):
        """验证最大回撤从 realized_pnl 序列计算。"""
        t0 = datetime.now(timezone.utc)
        t1 = t0 + timedelta(hours=1)
        t2 = t0 + timedelta(hours=2)
        instances = [make_instance(inst_id=1, template_id=1)]
        templates = [make_template(tpl_id=1, strategy_type="grid")]
        # realized 序列: 0 -> 100 (peak) -> 60 (dd=40) -> 80
        pnl_records = [
            make_pnl_record(realized_pnl=0, strategy_instance_id=1, recorded_at=t0),
            make_pnl_record(realized_pnl=100, strategy_instance_id=1, recorded_at=t1),
            make_pnl_record(realized_pnl=60, strategy_instance_id=1, recorded_at=t2),
        ]
        db = make_mock_db(orders=[], pnl_records=pnl_records, instances=instances, templates=templates)
        svc = AttributionService()
        result = svc.get_attribution_by_strategy_type(db, account_id=1,
                                                      start_date="2026-07-01T00:00:00",
                                                      end_date="2026-07-11T23:59:59")
        assert len(result) == 1
        # peak=100, trough=60 -> max_drawdown=40
        assert result[0]["max_drawdown"] == pytest.approx(40.0, abs=1e-4)


# ---------------------------------------------------------------------------
# 测试：按时间段聚合
# ---------------------------------------------------------------------------
class TestAttributionByPeriod:
    def test_daily_aggregation(self):
        """跨两天的 PnL 记录按天聚合，realized 取区间增量。"""
        day1 = datetime(2026, 7, 10, 10, 0, 0, tzinfo=timezone.utc)
        day2 = datetime(2026, 7, 11, 10, 0, 0, tzinfo=timezone.utc)
        # inst1: day1 realized=0, day2 realized=50 -> day2 增量=50
        pnl_records = [
            make_pnl_record(realized_pnl=0, unrealized_pnl=5, strategy_instance_id=1, recorded_at=day1),
            make_pnl_record(realized_pnl=50, unrealized_pnl=10, strategy_instance_id=1, recorded_at=day2),
        ]
        orders = [
            make_order(created_at=day1, strategy_instance_id=1, order_id=1),
            make_order(created_at=day2, strategy_instance_id=1, order_id=2),
            make_order(created_at=day2, strategy_instance_id=1, order_id=3),
        ]
        db = make_mock_db(orders=orders, pnl_records=pnl_records)
        svc = AttributionService()

        result = svc.get_attribution_by_period(db, account_id=1,
                                               start_date="2026-07-10T00:00:00",
                                               end_date="2026-07-11T23:59:59",
                                               period="daily")
        assert len(result) == 2
        # 按时间升序
        assert result[0]["period_start"] < result[1]["period_start"]
        # day1: delta = 0 - 0 = 0
        d1 = result[0]
        assert d1["realized_pnl"] == pytest.approx(0.0, abs=1e-4)
        assert d1["trade_count"] == 1
        # day2: delta = 50 - 0 = 50, unrealized = 10
        d2 = result[1]
        assert d2["realized_pnl"] == pytest.approx(50.0, abs=1e-4)
        assert d2["unrealized_pnl"] == pytest.approx(10.0, abs=1e-4)
        assert d2["total_pnl"] == pytest.approx(60.0, abs=1e-4)
        assert d2["trade_count"] == 2

    def test_invalid_period_defaults_to_daily(self):
        now = datetime.now(timezone.utc)
        pnl_records = [make_pnl_record(realized_pnl=10, strategy_instance_id=1, recorded_at=now)]
        db = make_mock_db(orders=[], pnl_records=pnl_records)
        svc = AttributionService()
        # 传入非法 period 不应报错，回退为 daily
        result = svc.get_attribution_by_period(db, account_id=1,
                                               start_date="2026-07-01T00:00:00",
                                               end_date="2026-07-11T23:59:59",
                                               period="hourly")
        assert isinstance(result, list)

    def test_empty_data_returns_empty(self):
        db = make_mock_db(orders=[], pnl_records=[])
        svc = AttributionService()
        result = svc.get_attribution_by_period(db, account_id=1,
                                               start_date="2026-07-01T00:00:00",
                                               end_date="2026-07-11T23:59:59",
                                               period="daily")
        assert result == []


# ---------------------------------------------------------------------------
# 测试：下钻查询
# ---------------------------------------------------------------------------
class TestDrillDown:
    def test_filter_by_symbol(self):
        now = datetime.now(timezone.utc)
        orders = [
            make_order(symbol="BTC-USDT", side="buy", fill_px=100, fill_sz=1, created_at=now, order_id=1),
            make_order(symbol="ETH-USDT", side="buy", fill_px=50, fill_sz=1, created_at=now, order_id=2),
        ]
        db = make_mock_db(orders=orders)
        svc = AttributionService()
        # mock db 不真正按 filter 过滤，但验证调用不报错且返回列表
        result = svc.get_drill_down(db,
                                    start_date="2026-07-01T00:00:00",
                                    end_date="2026-07-11T23:59:59",
                                    symbol="BTC-USDT",
                                    account_id=1)
        assert isinstance(result, list)
        assert len(result) == 2  # mock 返回全部订单
        assert "symbol" in result[0]
        assert "fill_px" in result[0]
        assert "side" in result[0]

    def test_filter_by_strategy_type(self):
        now = datetime.now(timezone.utc)
        orders = [make_order(symbol="BTC-USDT", created_at=now, order_id=1)]
        db = make_mock_db(orders=orders)
        svc = AttributionService()
        # strategy_type 触发 join 路径，验证链式调用不报错
        result = svc.get_drill_down(db,
                                    start_date="2026-07-01T00:00:00",
                                    end_date="2026-07-11T23:59:59",
                                    strategy_type="grid",
                                    account_id=1)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_no_filters_returns_all(self):
        now = datetime.now(timezone.utc)
        orders = [
            make_order(symbol="BTC-USDT", created_at=now, order_id=1),
            make_order(symbol="ETH-USDT", created_at=now, order_id=2),
            make_order(symbol="SOL-USDT", created_at=now, order_id=3),
        ]
        db = make_mock_db(orders=orders)
        svc = AttributionService()
        result = svc.get_drill_down(db,
                                    start_date="2026-07-01T00:00:00",
                                    end_date="2026-07-11T23:59:59")
        assert len(result) == 3


# ---------------------------------------------------------------------------
# 测试：辅助函数 _max_drawdown
# ---------------------------------------------------------------------------
class TestMaxDrawdown:
    def test_monotonic_increasing_no_drawdown(self):
        assert _max_drawdown([1, 2, 3, 4, 5]) == 0.0

    def test_simple_drawdown(self):
        # peak=100 at idx1, trough=60 at idx2 -> dd=40
        assert _max_drawdown([0, 100, 60, 80]) == 40.0

    def test_empty_series(self):
        assert _max_drawdown([]) == 0.0

    def test_single_value(self):
        assert _max_drawdown([42]) == 0.0

    def test_all_decreasing(self):
        # peak=first, then decreasing -> dd = 10 - 2 = 8
        assert _max_drawdown([10, 8, 5, 2]) == 8.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
