"""position_conflicts 端点单元测试（Task 7: 代数和算法 + 对冲组标注）。

覆盖 SubTask 7.4 四个用例：
1. test_endpoint_returns_algebraic_sum：同账户同 symbol 一多一空策略净持仓对冲，端点返回 is_conflict=False
2. test_endpoint_conflict_when_exceeds_real：策略净持仓超过真实持仓时 is_conflict=True
3. test_hedge_group_annotation：同账户同 symbol 多空策略标注为同一对冲组
4. test_single_direction_normal：单向持仓（只有多或只有空）正常不冲突

参考 test_position_conflict.py 风格，用 Mock client + Mock db_session。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from models.pnl import PnlRecord
from models.strategy import StrategyInstance


# ============================================================
# 辅助构造
# ============================================================


def _make_instance(instance_id, symbol="ETH-USDT-SWAP", account_id=1, status="running"):
    """构造 mock StrategyInstance。"""
    inst = MagicMock()
    inst.id = instance_id
    inst.account_id = account_id
    inst.symbol = symbol
    inst.status = status
    inst.params = {"fee_rate": 0.001}
    return inst


def _make_pnl_record(net_position):
    """构造 mock PnlRecord 对象。"""
    r = MagicMock()
    r.net_position = net_position
    return r


def _make_per_instance_mock_db(instances, pnl_records_by_id):
    """构造 mock DB session，按 strategy_instance_id 返回不同 PnlRecord。

    端点查询链路：
      - StrategyInstance: .filter()....all() → instances
      - PnlRecord: .filter(strategy_instance_id == X).order_by().first() → 按 X 返回不同 record

    通过捕获 filter 表达式中的 inst.id（SQLAlchemy BinaryExpression.right.value）
    实现按实例 id 返回不同 PnlRecord。
    """
    mock_db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        chain.filter.return_value = chain
        chain.order_by.return_value = chain
        if model is StrategyInstance:
            chain.all.return_value = instances
        elif model is PnlRecord:
            # 捕获 filter 参数中的 strategy_instance_id
            def filter_side_effect(*args, **kwargs):
                filter_arg = args[0] if args else None
                inst_id = _extract_instance_id(filter_arg)
                chain.first.return_value = pnl_records_by_id.get(inst_id)
                return chain
            chain.filter.side_effect = filter_side_effect
        return chain

    mock_db.query.side_effect = query_side_effect
    return mock_db


def _extract_instance_id(filter_arg):
    """从 PnlRecord.strategy_instance_id == inst.id 表达式中提取 inst.id。

    SQLAlchemy 的 BinaryExpression，.right 是 BindParameter，.value 是原始 Python 值。
    """
    if filter_arg is None:
        return None
    # SQLAlchemy 1.x/2.0: BinaryExpression.right.value
    try:
        return int(filter_arg.right.value)
    except (AttributeError, ValueError, TypeError):
        pass
    # 兜底：直接取 right
    try:
        return int(filter_arg.right)
    except (AttributeError, ValueError, TypeError):
        return None


@pytest.fixture(autouse=True)
def _stub_notification():
    """禁用真实通知，避免测试副作用。"""
    with patch("services.notification_service.notification_service") as mock_ns:
        mock_ns.notify = AsyncMock(return_value=0)
        yield


# ============================================================
# SubTask 7.4: 测试用例
# ============================================================


class TestPositionConflictsEndpointAlgebraic:
    """position_conflicts 端点代数和算法测试。"""

    async def test_endpoint_returns_algebraic_sum(self):
        """同账户同 symbol 一多一空策略净持仓对冲，端点返回 is_conflict=False。

        场景：A=+5（多），B=-5（空），real_pos=0（完全对冲）。
        期望：两个策略都不冲突（代数和=真实持仓，符合傅里叶叠加原理）。
        """
        from routers.monitoring import get_position_conflicts

        instances = [_make_instance(1), _make_instance(2)]
        pnl_records_by_id = {
            1: _make_pnl_record(net_position=5.0),    # A 多
            2: _make_pnl_record(net_position=-5.0),   # B 空
        }
        mock_db = _make_per_instance_mock_db(instances, pnl_records_by_id)

        mock_client = AsyncMock()
        # 真实持仓 0（完全对冲）
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "0"})

        with patch(
            "services.pnl_accounting_engine.pnl_accounting_engine._get_client",
            AsyncMock(return_value=mock_client),
        ):
            result = await get_position_conflicts(
                account_id=1, db=mock_db, user=MagicMock(),
            )

        # 两个策略都应不冲突
        assert result["total"] == 2
        for item in result["conflicts"]:
            assert item["is_conflict"] is False
            assert item["real_pos"] == pytest.approx(0.0)
        # 验证代数和字段（带符号）
        a_item = next(c for c in result["conflicts"] if c["strategy_instance_id"] == 1)
        b_item = next(c for c in result["conflicts"] if c["strategy_instance_id"] == 2)
        # A=+5, others_occupied=-5, available=0-(-5)=5, usable=abs(5)=5, |+5|>5=False
        assert a_item["others_occupied"] == pytest.approx(-5.0)
        assert a_item["available"] == pytest.approx(5.0)
        assert a_item["usable"] == pytest.approx(5.0)
        # B=-5, others_occupied=+5, available=0-5=-5, usable=abs(-5)=5, |-5|>5=False
        assert b_item["others_occupied"] == pytest.approx(5.0)
        assert b_item["available"] == pytest.approx(-5.0)
        assert b_item["usable"] == pytest.approx(5.0)

    async def test_endpoint_conflict_when_exceeds_real(self):
        """策略净持仓超过真实持仓时 is_conflict=True。

        场景：A=+12（多），无其他策略，real_pos=+10。
        期望：A 冲突（|12| > usable=10）。
        """
        from routers.monitoring import get_position_conflicts

        instances = [_make_instance(1)]
        pnl_records_by_id = {1: _make_pnl_record(net_position=12.0)}
        mock_db = _make_per_instance_mock_db(instances, pnl_records_by_id)

        mock_client = AsyncMock()
        # 真实持仓 +10，策略净持仓 +12，超出 2
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "10"})

        with patch(
            "services.pnl_accounting_engine.pnl_accounting_engine._get_client",
            AsyncMock(return_value=mock_client),
        ):
            result = await get_position_conflicts(
                account_id=1, db=mock_db, user=MagicMock(),
            )

        assert result["total"] == 1
        item = result["conflicts"][0]
        assert item["is_conflict"] is True
        assert item["real_pos"] == pytest.approx(10.0)
        assert item["net_position"] == pytest.approx(12.0)
        # others_occupied=0, available=10-0=10, real_pos>0 → usable=10, |12|>10=True
        assert item["others_occupied"] == pytest.approx(0.0)
        assert item["available"] == pytest.approx(10.0)
        assert item["usable"] == pytest.approx(10.0)

    async def test_hedge_group_annotation(self):
        """同账户同 symbol 多空策略标注为同一对冲组。

        场景：A=+5（多），B=-5（空），同 symbol → 同属对冲组 G1。
        期望：两个策略的 hedge_group 字段相同（"G1"）。
        """
        from routers.monitoring import get_position_conflicts

        instances = [_make_instance(1), _make_instance(2)]
        pnl_records_by_id = {
            1: _make_pnl_record(net_position=5.0),
            2: _make_pnl_record(net_position=-5.0),
        }
        mock_db = _make_per_instance_mock_db(instances, pnl_records_by_id)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "0"})

        with patch(
            "services.pnl_accounting_engine.pnl_accounting_engine._get_client",
            AsyncMock(return_value=mock_client),
        ):
            result = await get_position_conflicts(
                account_id=1, db=mock_db, user=MagicMock(),
            )

        # 两个策略都应标注为对冲组 G1
        assert result["total"] == 2
        groups = {c["hedge_group"] for c in result["conflicts"]}
        assert groups == {"G1"}
        for item in result["conflicts"]:
            assert item["hedge_group"] == "G1"

    async def test_single_direction_normal(self):
        """单向持仓（只有多或只有空）正常不冲突，且不标注对冲组。

        场景：A=+5（多），B=+3（多），real_pos=+8（同向相加）。
        期望：两个策略都不冲突，且 hedge_group=None（无对冲组）。
        """
        from routers.monitoring import get_position_conflicts

        instances = [_make_instance(1), _make_instance(2)]
        pnl_records_by_id = {
            1: _make_pnl_record(net_position=5.0),
            2: _make_pnl_record(net_position=3.0),
        }
        mock_db = _make_per_instance_mock_db(instances, pnl_records_by_id)

        mock_client = AsyncMock()
        # 真实持仓 +8（5+3 同向相加）
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "8"})

        with patch(
            "services.pnl_accounting_engine.pnl_accounting_engine._get_client",
            AsyncMock(return_value=mock_client),
        ):
            result = await get_position_conflicts(
                account_id=1, db=mock_db, user=MagicMock(),
            )

        # 两个策略都不冲突，且无对冲组
        assert result["total"] == 2
        for item in result["conflicts"]:
            assert item["is_conflict"] is False
            assert item["hedge_group"] is None
        # 验证代数和：A=+5, others_occupied=+3, available=8-3=5, usable=5, |5|>5=False
        a_item = next(c for c in result["conflicts"] if c["strategy_instance_id"] == 1)
        assert a_item["others_occupied"] == pytest.approx(3.0)
        assert a_item["available"] == pytest.approx(5.0)
        assert a_item["usable"] == pytest.approx(5.0)
