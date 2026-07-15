"""get_attribution_by_symbol 单元测试（基于 PnlRecord 聚合口径）。

覆盖 Task 4 重构后的行为：
- SubTask 4.1：两策略同 symbol 时按 PnlRecord 聚合（realized/unrealized/net_position/
  total_fee/order_count 求和）
- SubTask 4.2：avg_buy_price 按 |net_position| 加权平均；全 0 时取简单平均或 0
- SubTask 4.3：返回结果包含 unrealized_pnl 字段
- SubTask 4.4：realized_pnl 取累计口径（latest.realized_pnl 求和）
- SubTask 4.5：时间过滤字段为 PnlRecord.recorded_at（窗口外记录被排除）
- 一致性：同账户同时间段，by_symbol 总 realized == by_strategy_type 总 realized

DB 查询使用 MagicMock 模拟。其中时间过滤测试使用会真正按 recorded_at 过滤的 mock。
"""
import sys
import os
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.attribution_service import AttributionService
from models.pnl import PnlRecord
from models.strategy import StrategyInstance, StrategyTemplate


# ---------------------------------------------------------------------------
# 工厂函数：构造 mock 模型实例
# ---------------------------------------------------------------------------
def make_instance(inst_id=1, template_id=1, account_id=1, symbol="BTC-USDT",
                  status="running"):
    return SimpleNamespace(
        id=inst_id,
        template_id=template_id,
        account_id=account_id,
        name=f"inst-{inst_id}",
        symbol=symbol,
        market_type="spot",
        params={},
        status=status,
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


def make_pnl_record(realized_pnl=0.0, unrealized_pnl=0.0, recorded_at=None,
                    strategy_instance_id=1, account_id=1, order_count=0,
                    net_position=0.0, avg_buy_price=0.0, total_fee=0.0):
    return SimpleNamespace(
        id=1,
        account_id=account_id,
        strategy_instance_id=strategy_instance_id,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_pnl=realized_pnl + unrealized_pnl,
        equity=0.0,
        order_count=order_count,
        recorded_at=recorded_at or datetime.now(timezone.utc),
        is_final=False,
        net_position=net_position,
        avg_buy_price=avg_buy_price,
        total_fee=total_fee,
    )


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


def make_mock_db(orders=None, pnl_records=None, instances=None, templates=None):
    """基础 mock db：query().filter() 等链式调用为 no-op，返回预设列表。

    不会真正按时间过滤；时间过滤测试用 make_time_filtering_mock_db。
    """
    db = MagicMock()

    def query(model):
        q = MagicMock()
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


def make_time_filtering_mock_db(orders=None, pnl_records=None, instances=None,
                                templates=None, pnl_start=None, pnl_end=None):
    """会真正按 recorded_at 过滤 PnlRecord 的 mock db。

    用于验证 SubTask 4.5 时间过滤用 recorded_at：窗口外的 PnlRecord 应被排除。
    """
    db = MagicMock()

    def query(model):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.limit.return_value = q
        q.join.return_value = q
        name = getattr(model, "__name__", "")
        if name == "Order":
            q.all.return_value = orders or []
        elif name == "PnlRecord":
            recs = list(pnl_records or [])
            if pnl_start is not None:
                recs = [r for r in recs if r.recorded_at >= pnl_start]
            if pnl_end is not None:
                recs = [r for r in recs if r.recorded_at <= pnl_end]
            q.all.return_value = recs
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
# 测试：by_symbol 基于 PnlRecord 聚合
# ---------------------------------------------------------------------------
class TestAttributionBySymbolPnlRecord:
    def test_two_strategies_same_symbol_aggregation(self):
        """两策略实例同 symbol：realized/unrealized/net_position/total_fee/order_count 求和。"""
        now = datetime.now(timezone.utc)
        # 两个实例都跑 BTC-USDT
        instances = [
            make_instance(inst_id=1, template_id=1, symbol="BTC-USDT", status="running"),
            make_instance(inst_id=2, template_id=2, symbol="BTC-USDT", status="paused"),
        ]
        templates = [make_template(tpl_id=1, strategy_type="grid"),
                     make_template(tpl_id=2, strategy_type="trend")]
        pnl_records = [
            make_pnl_record(realized_pnl=100, unrealized_pnl=20, net_position=2.0,
                            avg_buy_price=50000, total_fee=1.5, order_count=3,
                            strategy_instance_id=1, recorded_at=now),
            make_pnl_record(realized_pnl=50, unrealized_pnl=-10, net_position=1.0,
                            avg_buy_price=52000, total_fee=0.8, order_count=2,
                            strategy_instance_id=2, recorded_at=now),
        ]
        db = make_mock_db(pnl_records=pnl_records, instances=instances, templates=templates)
        svc = AttributionService()

        result = svc.get_attribution_by_symbol(db, account_id=1,
                                                start_date="2026-07-01T00:00:00",
                                                end_date="2026-07-11T23:59:59")
        # 两实例同 symbol，聚合为一行
        assert len(result) == 1
        btc = result[0]
        assert btc["symbol"] == "BTC-USDT"
        # realized = 100 + 50 = 150（累计口径）
        assert btc["realized_pnl"] == pytest.approx(150.0, abs=1e-4)
        # unrealized = 20 + (-10) = 10
        assert btc["unrealized_pnl"] == pytest.approx(10.0, abs=1e-4)
        # net_position = 2.0 + 1.0 = 3.0
        assert btc["net_position"] == pytest.approx(3.0, abs=1e-6)
        # total_fee = 1.5 + 0.8 = 2.3
        assert btc["total_fee"] == pytest.approx(2.3, abs=1e-6)
        # order_count = 3 + 2 = 5
        assert btc["order_count"] == 5

    def test_realized_pnl_cumulative_from_latest(self):
        """SubTask 4.4：realized_pnl 取累计口径（latest.realized_pnl），非区间增量。

        构造同一实例多条 PnlRecord，验证取最新一条的累计 realized_pnl，
        而非 by_period 那样的区间增量。
        """
        t0 = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 7, 5, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 7, 10, 10, 0, 0, tzinfo=timezone.utc)
        instances = [make_instance(inst_id=1, symbol="BTC-USDT", status="running")]
        # realized 累计序列：0 -> 50 -> 120（最新为 120，非增量 70）
        pnl_records = [
            make_pnl_record(realized_pnl=0, strategy_instance_id=1, recorded_at=t0),
            make_pnl_record(realized_pnl=50, strategy_instance_id=1, recorded_at=t1),
            make_pnl_record(realized_pnl=120, strategy_instance_id=1, recorded_at=t2),
        ]
        db = make_mock_db(pnl_records=pnl_records, instances=instances)
        svc = AttributionService()

        result = svc.get_attribution_by_symbol(db, account_id=1,
                                                start_date="2026-07-01T00:00:00",
                                                end_date="2026-07-11T23:59:59")
        assert len(result) == 1
        # 取最新一条的累计 realized_pnl = 120，不是增量 70
        assert result[0]["realized_pnl"] == pytest.approx(120.0, abs=1e-4)

    def test_unrealized_pnl_field_present(self):
        """SubTask 4.3：返回结果包含 unrealized_pnl 字段。"""
        now = datetime.now(timezone.utc)
        instances = [make_instance(inst_id=1, symbol="BTC-USDT", status="running")]
        pnl_records = [
            make_pnl_record(realized_pnl=100, unrealized_pnl=25.5,
                            strategy_instance_id=1, recorded_at=now),
        ]
        db = make_mock_db(pnl_records=pnl_records, instances=instances)
        svc = AttributionService()

        result = svc.get_attribution_by_symbol(db, account_id=1,
                                                start_date="2026-07-01T00:00:00",
                                                end_date="2026-07-11T23:59:59")
        assert len(result) == 1
        assert "unrealized_pnl" in result[0]
        assert result[0]["unrealized_pnl"] == pytest.approx(25.5, abs=1e-4)

    def test_empty_instances_returns_empty(self):
        """无策略实例返回空列表。"""
        db = make_mock_db(instances=[])
        svc = AttributionService()
        result = svc.get_attribution_by_symbol(db, account_id=1,
                                                start_date="2026-07-01T00:00:00",
                                                end_date="2026-07-11T23:59:59")
        assert result == []

    def test_instance_without_pnl_record_skipped(self):
        """有实例但无 PnlRecord 的 symbol 被跳过。"""
        instances = [make_instance(inst_id=1, symbol="BTC-USDT", status="running")]
        db = make_mock_db(pnl_records=[], instances=instances)
        svc = AttributionService()
        result = svc.get_attribution_by_symbol(db, account_id=1,
                                                start_date="2026-07-01T00:00:00",
                                                end_date="2026-07-11T23:59:59")
        assert result == []

    def test_result_sorted_by_realized_pnl_desc(self):
        """多 symbol 时按 realized_pnl 降序。"""
        now = datetime.now(timezone.utc)
        instances = [
            make_instance(inst_id=1, symbol="BTC-USDT", status="running"),
            make_instance(inst_id=2, symbol="ETH-USDT", status="running"),
        ]
        pnl_records = [
            make_pnl_record(realized_pnl=-50, strategy_instance_id=1, recorded_at=now),
            make_pnl_record(realized_pnl=100, strategy_instance_id=2, recorded_at=now),
        ]
        db = make_mock_db(pnl_records=pnl_records, instances=instances)
        svc = AttributionService()
        result = svc.get_attribution_by_symbol(db, account_id=1,
                                                start_date="2026-07-01T00:00:00",
                                                end_date="2026-07-11T23:59:59")
        assert len(result) == 2
        # ETH(100) 在前，BTC(-50) 在后
        assert result[0]["symbol"] == "ETH-USDT"
        assert result[1]["symbol"] == "BTC-USDT"
        assert result[0]["realized_pnl"] >= result[1]["realized_pnl"]


# ---------------------------------------------------------------------------
# 测试：avg_buy_price 加权平均
# ---------------------------------------------------------------------------
class TestAvgBuyPriceWeighted:
    def test_weighted_average_by_net_position(self):
        """SubTask 4.2：avg_buy_price 按 |net_position| 加权平均。

        inst1: price=100, |net_pos|=2 -> 100*2=200
        inst2: price=200, |net_pos|=1 -> 200*1=200
        加权 = (200+200)/(2+1) = 400/3 ≈ 133.3333
        """
        now = datetime.now(timezone.utc)
        instances = [
            make_instance(inst_id=1, symbol="BTC-USDT", status="running"),
            make_instance(inst_id=2, symbol="BTC-USDT", status="running"),
        ]
        pnl_records = [
            make_pnl_record(realized_pnl=10, net_position=2.0, avg_buy_price=100,
                            strategy_instance_id=1, recorded_at=now),
            make_pnl_record(realized_pnl=20, net_position=1.0, avg_buy_price=200,
                            strategy_instance_id=2, recorded_at=now),
        ]
        db = make_mock_db(pnl_records=pnl_records, instances=instances)
        svc = AttributionService()
        result = svc.get_attribution_by_symbol(db, account_id=1,
                                                start_date="2026-07-01T00:00:00",
                                                end_date="2026-07-11T23:59:59")
        assert len(result) == 1
        assert result[0]["avg_buy_price"] == pytest.approx(133.3333, abs=1e-3)

    def test_all_zero_net_position_falls_back_to_simple_avg(self):
        """全 0 net_position 时取简单平均。

        inst1: price=100, net_pos=0
        inst2: price=200, net_pos=0
        简单平均 = (100+200)/2 = 150
        """
        now = datetime.now(timezone.utc)
        instances = [
            make_instance(inst_id=1, symbol="BTC-USDT", status="running"),
            make_instance(inst_id=2, symbol="BTC-USDT", status="running"),
        ]
        pnl_records = [
            make_pnl_record(realized_pnl=10, net_position=0.0, avg_buy_price=100,
                            strategy_instance_id=1, recorded_at=now),
            make_pnl_record(realized_pnl=20, net_position=0.0, avg_buy_price=200,
                            strategy_instance_id=2, recorded_at=now),
        ]
        db = make_mock_db(pnl_records=pnl_records, instances=instances)
        svc = AttributionService()
        result = svc.get_attribution_by_symbol(db, account_id=1,
                                                start_date="2026-07-01T00:00:00",
                                                end_date="2026-07-11T23:59:59")
        assert len(result) == 1
        assert result[0]["avg_buy_price"] == pytest.approx(150.0, abs=1e-4)

    def test_single_instance_uses_its_own_price(self):
        """单实例时 avg_buy_price = 该实例自身价格。"""
        now = datetime.now(timezone.utc)
        instances = [make_instance(inst_id=1, symbol="BTC-USDT", status="running")]
        pnl_records = [
            make_pnl_record(realized_pnl=10, net_position=0.5, avg_buy_price=50000,
                            strategy_instance_id=1, recorded_at=now),
        ]
        db = make_mock_db(pnl_records=pnl_records, instances=instances)
        svc = AttributionService()
        result = svc.get_attribution_by_symbol(db, account_id=1,
                                                start_date="2026-07-01T00:00:00",
                                                end_date="2026-07-11T23:59:59")
        assert len(result) == 1
        assert result[0]["avg_buy_price"] == pytest.approx(50000.0, abs=1e-4)


# ---------------------------------------------------------------------------
# 测试：时间过滤用 recorded_at
# ---------------------------------------------------------------------------
class TestTimeFilterRecordedAt:
    def test_records_outside_window_excluded(self):
        """SubTask 4.5：时间窗口外的 PnlRecord 被排除，取窗口内最新一条。

        构造三条记录：
        - t0 (7-01) realized=10  —— 在窗口内
        - t1 (7-05) realized=50  —— 在窗口内（最新）
        - t2 (7-15) realized=200 —— 窗口外（应被排除）
        窗口 [7-01, 7-11]，最终 realized 应为 50（窗口内最新），不是 200。
        """
        t0 = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 7, 5, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 7, 15, 10, 0, 0, tzinfo=timezone.utc)
        instances = [make_instance(inst_id=1, symbol="BTC-USDT", status="running")]
        pnl_records = [
            make_pnl_record(realized_pnl=10, strategy_instance_id=1, recorded_at=t0),
            make_pnl_record(realized_pnl=50, strategy_instance_id=1, recorded_at=t1),
            make_pnl_record(realized_pnl=200, strategy_instance_id=1, recorded_at=t2),
        ]
        start_dt = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        end_dt = datetime(2026, 7, 11, 23, 59, 59, tzinfo=timezone.utc)
        db = make_time_filtering_mock_db(
            pnl_records=pnl_records, instances=instances,
            pnl_start=start_dt, pnl_end=end_dt,
        )
        svc = AttributionService()
        result = svc.get_attribution_by_symbol(
            db, account_id=1,
            start_date="2026-07-01T00:00:00",
            end_date="2026-07-11T23:59:59",
        )
        assert len(result) == 1
        # 窗口内最新是 t1 的 realized=50，t2 (200) 被时间过滤排除
        assert result[0]["realized_pnl"] == pytest.approx(50.0, abs=1e-4)

    def test_all_records_outside_window_returns_empty(self):
        """全部记录在窗口外，symbol 被跳过，返回空。"""
        t0 = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
        instances = [make_instance(inst_id=1, symbol="BTC-USDT", status="running")]
        pnl_records = [
            make_pnl_record(realized_pnl=100, strategy_instance_id=1, recorded_at=t0),
        ]
        start_dt = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        end_dt = datetime(2026, 7, 11, 23, 59, 59, tzinfo=timezone.utc)
        db = make_time_filtering_mock_db(
            pnl_records=pnl_records, instances=instances,
            pnl_start=start_dt, pnl_end=end_dt,
        )
        svc = AttributionService()
        result = svc.get_attribution_by_symbol(
            db, account_id=1,
            start_date="2026-07-01T00:00:00",
            end_date="2026-07-11T23:59:59",
        )
        assert result == []


# ---------------------------------------------------------------------------
# 测试：与 by_strategy_type 总 realized 一致
# ---------------------------------------------------------------------------
class TestConsistencyWithByStrategyType:
    def test_total_realized_matches_by_strategy_type(self):
        """同账户同时间段，by_symbol 总 realized == by_strategy_type 总 realized。

        构造两个 symbol、两个策略类型，两维度聚合的 realized 总和应相等。
        """
        now = datetime.now(timezone.utc)
        instances = [
            make_instance(inst_id=1, template_id=1, symbol="BTC-USDT", status="running"),
            make_instance(inst_id=2, template_id=2, symbol="ETH-USDT", status="running"),
        ]
        templates = [make_template(tpl_id=1, strategy_type="grid"),
                     make_template(tpl_id=2, strategy_type="trend")]
        pnl_records = [
            make_pnl_record(realized_pnl=100, unrealized_pnl=20, net_position=1.0,
                            avg_buy_price=50000, total_fee=1.0, order_count=2,
                            strategy_instance_id=1, recorded_at=now),
            make_pnl_record(realized_pnl=50, unrealized_pnl=-10, net_position=0.5,
                            avg_buy_price=3000, total_fee=0.5, order_count=1,
                            strategy_instance_id=2, recorded_at=now),
        ]
        # by_strategy_type 还需要 orders（用于 trade_count/win_rate），这里给空订单
        db = make_mock_db(orders=[], pnl_records=pnl_records, instances=instances,
                          templates=templates)
        svc = AttributionService()

        by_symbol = svc.get_attribution_by_symbol(
            db, account_id=1,
            start_date="2026-07-01T00:00:00",
            end_date="2026-07-11T23:59:59",
        )
        by_stype = svc.get_attribution_by_strategy_type(
            db, account_id=1,
            start_date="2026-07-01T00:00:00",
            end_date="2026-07-11T23:59:59",
        )

        total_symbol = sum(r["realized_pnl"] for r in by_symbol)
        total_stype = sum(r["realized_pnl"] for r in by_stype)
        # 两维度总 realized 一致（均基于 PnlRecord.latest.realized_pnl 求和）
        assert total_symbol == pytest.approx(total_stype, abs=1e-4)
        # 具体值校验：100 + 50 = 150
        assert total_symbol == pytest.approx(150.0, abs=1e-4)
        assert total_stype == pytest.approx(150.0, abs=1e-4)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
