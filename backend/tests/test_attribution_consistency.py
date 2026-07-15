"""三维度口径统一与验证测试（Task 5）。

验证 by_symbol / by_strategy_type / by_period 三个维度的 realized_pnl / unrealized_pnl
口径一致，均基于 PnlRecord：

- SubTask 5.3.1：三维度 realized_pnl 总和一致
  （by_period 用区间增量，首条记录 realized=0 时增量之和 = 期末累计值）
- SubTask 5.3.2：三维度 unrealized_pnl 期末总和一致
  （by_period 取期末值，单周期桶时 = 各实例最后一条 unrealized 求和）
- SubTask 5.3.3：by_strategy_type 数据源是 PnlRecord（非 orders）
- SubTask 5.3.4：by_period 的 unrealized 取期末值（非首条、非求和）

DB 查询使用 MagicMock 模拟，与 test_attribution_by_symbol.py 风格一致。
"""
import sys
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.attribution_service import AttributionService
from models.pnl import PnlRecord
from models.strategy import StrategyInstance, StrategyTemplate


# ---------------------------------------------------------------------------
# 工厂函数：构造 mock 模型实例（与 test_attribution_by_symbol.py 保持一致）
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
    """基础 mock db：query().filter() 等链式调用为 no-op，返回预设列表。"""
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


# ---------------------------------------------------------------------------
# SubTask 5.3.1 & 5.3.2：三维度 realized / unrealized 一致
# ---------------------------------------------------------------------------
class TestThreeDimensionsConsistency:
    def test_three_dimensions_realized_consistent(self):
        """同一账户同一时间段，三维度 realized_pnl 总和一致。

        测试数据：两实例，首条 realized=0（策略启动），末条为累计值。
        - by_symbol：取 latest.realized_pnl 求和 = 100 + 50 = 150
        - by_strategy_type：取 latest.realized_pnl 求和 = 150
        - by_period：区间增量求和 = (100-0) + (50-0) = 150
        """
        # 同一天，保证 by_period 只有单个周期桶
        t0 = datetime(2026, 7, 5, 10, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 7, 5, 14, 0, 0, tzinfo=timezone.utc)
        instances = [
            make_instance(inst_id=1, template_id=1, symbol="BTC-USDT", status="running"),
            make_instance(inst_id=2, template_id=2, symbol="ETH-USDT", status="running"),
        ]
        templates = [make_template(tpl_id=1, strategy_type="grid"),
                     make_template(tpl_id=2, strategy_type="trend")]
        pnl_records = [
            # inst1：realized 累计 0 -> 100
            make_pnl_record(realized_pnl=0, unrealized_pnl=10, strategy_instance_id=1, recorded_at=t0),
            make_pnl_record(realized_pnl=100, unrealized_pnl=20, strategy_instance_id=1, recorded_at=t1),
            # inst2：realized 累计 0 -> 50
            make_pnl_record(realized_pnl=0, unrealized_pnl=5, strategy_instance_id=2, recorded_at=t0),
            make_pnl_record(realized_pnl=50, unrealized_pnl=15, strategy_instance_id=2, recorded_at=t1),
        ]
        db = make_mock_db(orders=[], pnl_records=pnl_records, instances=instances,
                          templates=templates)
        svc = AttributionService()
        params = dict(account_id=1,
                      start_date="2026-07-01T00:00:00",
                      end_date="2026-07-11T23:59:59")

        by_symbol = svc.get_attribution_by_symbol(db, **params)
        by_stype = svc.get_attribution_by_strategy_type(db, **params)
        by_period = svc.get_attribution_by_period(db, period="daily", **params)

        total_symbol = sum(r["realized_pnl"] for r in by_symbol)
        total_stype = sum(r["realized_pnl"] for r in by_stype)
        total_period = sum(r["realized_pnl"] for r in by_period)

        # 三维度 realized 总和一致（均基于 PnlRecord.realized_pnl）
        assert total_symbol == pytest.approx(150.0, abs=1e-4)
        assert total_stype == pytest.approx(150.0, abs=1e-4)
        assert total_period == pytest.approx(150.0, abs=1e-4)
        # 三者互等
        assert total_symbol == pytest.approx(total_stype, abs=1e-4)
        assert total_stype == pytest.approx(total_period, abs=1e-4)

    def test_three_dimensions_unrealized_consistent(self):
        """同一账户同一时间段，三维度 unrealized_pnl 期末总和一致。

        单周期桶下：
        - by_symbol：latest.unrealized 求和 = 20 + 15 = 35
        - by_strategy_type：latest.unrealized 求和 = 35
        - by_period：期末值（各实例桶内最后一条 unrealized）求和 = 20 + 15 = 35
        """
        t0 = datetime(2026, 7, 5, 10, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 7, 5, 14, 0, 0, tzinfo=timezone.utc)
        instances = [
            make_instance(inst_id=1, template_id=1, symbol="BTC-USDT", status="running"),
            make_instance(inst_id=2, template_id=2, symbol="ETH-USDT", status="running"),
        ]
        templates = [make_template(tpl_id=1, strategy_type="grid"),
                     make_template(tpl_id=2, strategy_type="trend")]
        pnl_records = [
            make_pnl_record(realized_pnl=0, unrealized_pnl=10, strategy_instance_id=1, recorded_at=t0),
            make_pnl_record(realized_pnl=100, unrealized_pnl=20, strategy_instance_id=1, recorded_at=t1),
            make_pnl_record(realized_pnl=0, unrealized_pnl=5, strategy_instance_id=2, recorded_at=t0),
            make_pnl_record(realized_pnl=50, unrealized_pnl=15, strategy_instance_id=2, recorded_at=t1),
        ]
        db = make_mock_db(orders=[], pnl_records=pnl_records, instances=instances,
                          templates=templates)
        svc = AttributionService()
        params = dict(account_id=1,
                      start_date="2026-07-01T00:00:00",
                      end_date="2026-07-11T23:59:59")

        by_symbol = svc.get_attribution_by_symbol(db, **params)
        by_stype = svc.get_attribution_by_strategy_type(db, **params)
        by_period = svc.get_attribution_by_period(db, period="daily", **params)

        total_symbol = sum(r["unrealized_pnl"] for r in by_symbol)
        total_stype = sum(r["unrealized_pnl"] for r in by_stype)
        total_period = sum(r["unrealized_pnl"] for r in by_period)

        # 三维度 unrealized 期末总和一致
        assert total_symbol == pytest.approx(35.0, abs=1e-4)
        assert total_stype == pytest.approx(35.0, abs=1e-4)
        assert total_period == pytest.approx(35.0, abs=1e-4)
        assert total_symbol == pytest.approx(total_stype, abs=1e-4)
        assert total_stype == pytest.approx(total_period, abs=1e-4)


# ---------------------------------------------------------------------------
# SubTask 5.3.3：by_strategy_type 数据源是 PnlRecord（非 orders）
# ---------------------------------------------------------------------------
class TestByStrategyTypeUsesPnlRecord:
    def test_by_strategy_type_uses_pnl_record(self):
        """by_strategy_type 的 realized_pnl 取自 PnlRecord，而非 orders。

        构造：
        - PnlRecord realized=100
        - 订单：1 买 (100*1) + 1 卖 (150*1)，若按 orders 聚合 realized 应为 50
        断言 by_strategy_type 返回 realized_pnl == 100（PnlRecord 值）。
        """
        t1 = datetime(2026, 7, 5, 14, 0, 0, tzinfo=timezone.utc)
        instances = [make_instance(inst_id=1, template_id=1, symbol="BTC-USDT", status="running")]
        templates = [make_template(tpl_id=1, strategy_type="grid")]
        pnl_records = [
            make_pnl_record(realized_pnl=100, unrealized_pnl=20,
                            strategy_instance_id=1, recorded_at=t1),
        ]
        # 订单：买入 100@1，卖出 150@1 —— orders 维度 realized = 50（≠ PnlRecord 的 100）
        orders = [
            make_order(side="buy", fill_px=100.0, fill_sz=1.0, created_at=t1,
                       strategy_instance_id=1, order_id=1),
            make_order(side="sell", fill_px=150.0, fill_sz=1.0, created_at=t1,
                       strategy_instance_id=1, order_id=2),
        ]
        db = make_mock_db(orders=orders, pnl_records=pnl_records, instances=instances,
                          templates=templates)
        svc = AttributionService()
        result = svc.get_attribution_by_strategy_type(
            db, account_id=1,
            start_date="2026-07-01T00:00:00",
            end_date="2026-07-11T23:59:59",
        )
        assert len(result) == 1
        # realized_pnl 来自 PnlRecord（100），不是 orders（50）
        assert result[0]["realized_pnl"] == pytest.approx(100.0, abs=1e-4)

    def test_by_strategy_type_no_pnl_record_realized_zero(self):
        """有订单但无 PnlRecord 时，by_strategy_type realized_pnl 应为 0。

        进一步证明 realized_pnl 不依赖 orders：即使有盈利卖出订单，
        没有 PnlRecord 则 realized_pnl = 0。
        """
        t1 = datetime(2026, 7, 5, 14, 0, 0, tzinfo=timezone.utc)
        instances = [make_instance(inst_id=1, template_id=1, symbol="BTC-USDT", status="running")]
        templates = [make_template(tpl_id=1, strategy_type="grid")]
        # 无 PnlRecord
        orders = [
            make_order(side="buy", fill_px=100.0, fill_sz=1.0, created_at=t1,
                       strategy_instance_id=1, order_id=1),
            make_order(side="sell", fill_px=150.0, fill_sz=1.0, created_at=t1,
                       strategy_instance_id=1, order_id=2),
        ]
        db = make_mock_db(orders=orders, pnl_records=[], instances=instances,
                          templates=templates)
        svc = AttributionService()
        result = svc.get_attribution_by_strategy_type(
            db, account_id=1,
            start_date="2026-07-01T00:00:00",
            end_date="2026-07-11T23:59:59",
        )
        assert len(result) == 1
        # 无 PnlRecord，realized_pnl = 0（即便有盈利订单）
        assert result[0]["realized_pnl"] == pytest.approx(0.0, abs=1e-4)


# ---------------------------------------------------------------------------
# SubTask 5.3.4：by_period 的 unrealized 取期末值
# ---------------------------------------------------------------------------
class TestByPeriodUnrealizedIsEndOfPeriod:
    def test_by_period_unrealized_is_end_of_period(self):
        """by_period 的 unrealized_pnl 取期末（周期桶内最后一条）值。

        构造单实例同一天三条记录：
        - t0 unrealized=10
        - t1 unrealized=25
        - t2 unrealized=40（期末值）
        断言 by_period 该桶 unrealized_pnl == 40（期末），不是 10（首条）或 75（求和）。
        """
        t0 = datetime(2026, 7, 5, 8, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 7, 5, 16, 0, 0, tzinfo=timezone.utc)
        instances = [make_instance(inst_id=1, template_id=1, symbol="BTC-USDT", status="running")]
        pnl_records = [
            make_pnl_record(realized_pnl=0, unrealized_pnl=10, strategy_instance_id=1, recorded_at=t0),
            make_pnl_record(realized_pnl=30, unrealized_pnl=25, strategy_instance_id=1, recorded_at=t1),
            make_pnl_record(realized_pnl=80, unrealized_pnl=40, strategy_instance_id=1, recorded_at=t2),
        ]
        db = make_mock_db(orders=[], pnl_records=pnl_records, instances=instances)
        svc = AttributionService()
        result = svc.get_attribution_by_period(
            db, account_id=1, period="daily",
            start_date="2026-07-01T00:00:00",
            end_date="2026-07-11T23:59:59",
        )
        # 单周期桶
        assert len(result) == 1
        # unrealized 取期末值 40，非首条 10、非求和 75
        assert result[0]["unrealized_pnl"] == pytest.approx(40.0, abs=1e-4)

    def test_by_period_unrealized_not_summed_across_records(self):
        """by_period 的 unrealized 不应是周期内各记录 unrealized 的求和。

        同一周期桶内多条记录，unrealized 应只取最后一条，而非累加。
        """
        t0 = datetime(2026, 7, 5, 8, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
        instances = [make_instance(inst_id=1, template_id=1, symbol="BTC-USDT", status="running")]
        pnl_records = [
            make_pnl_record(realized_pnl=0, unrealized_pnl=15, strategy_instance_id=1, recorded_at=t0),
            make_pnl_record(realized_pnl=20, unrealized_pnl=30, strategy_instance_id=1, recorded_at=t1),
        ]
        db = make_mock_db(orders=[], pnl_records=pnl_records, instances=instances)
        svc = AttributionService()
        result = svc.get_attribution_by_period(
            db, account_id=1, period="daily",
            start_date="2026-07-01T00:00:00",
            end_date="2026-07-11T23:59:59",
        )
        assert len(result) == 1
        # 取期末 30，不是 15+30=45
        assert result[0]["unrealized_pnl"] == pytest.approx(30.0, abs=1e-4)
        assert result[0]["unrealized_pnl"] != pytest.approx(45.0, abs=1e-4)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
