"""多策略同品种持仓冲突检测单元测试（Task 5: SubTask 5.1-5.3）。

覆盖：
- BaseStrategy.check_position_conflict：
  - 无其他策略占用返回 True
  - 其他策略占用导致可用不足返回 False 并记录 position_conflict 事件
  - 刚好够返回 True
- BaseStrategy.close_position_with_conflict_check：冲突时返回拒绝响应不调 client
- 节流：10s 内第二次不查 API
- /api/monitoring/position_conflicts 端点返回结构正确（用 Mock）

参考 test_position_reconcile.py 风格，用 Mock client + Mock db_session_factory。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from strategies.base_strategy import BaseStrategy
from models.pnl import PnlRecord
from models.strategy import StrategyInstance


# ============================================================
# 辅助构造
# ============================================================


class _DummyStrategy(BaseStrategy):
    """最小可实例化策略子类，用于测试 BaseStrategy 能力。"""

    async def execute(self):
        pass

    async def validate_params(self) -> bool:
        return True


def _make_strategy(params: dict, client=None) -> tuple[_DummyStrategy, MagicMock]:
    """构造带 Mock 依赖的策略实例与 mock db。"""
    db = MagicMock()
    db_session_factory = MagicMock(return_value=db)
    mock_client = client or AsyncMock()
    strategy = _DummyStrategy(
        instance_id=1,
        params=params,
        client=mock_client,
        db_session_factory=db_session_factory,
        account_id=1,
        order_manager=MagicMock(),
        ws_client=None,
    )
    return strategy, db


def _make_pnl_record(net_position, avg_buy_price=0.0, realized_pnl=0.0):
    """构造 mock PnlRecord 对象。"""
    r = MagicMock()
    r.net_position = net_position
    r.avg_buy_price = avg_buy_price
    r.realized_pnl = realized_pnl
    return r


def _make_instance(instance_id, symbol="ETH-USDT-SWAP", account_id=1, status="running"):
    """构造 mock StrategyInstance。"""
    inst = MagicMock()
    inst.id = instance_id
    inst.account_id = account_id
    inst.symbol = symbol
    inst.status = status
    inst.params = {"fee_rate": 0.001}
    return inst


def _make_conflict_mock_db(instances, pnl_record=None):
    """构造 mock DB session，适配 check_position_conflict 与 position_conflicts 端点的查询链路。

    查询链路：
      - StrategyInstance: .filter()....all() → instances
      - PnlRecord: .filter().order_by().first() → pnl record
    通过让 filter / order_by 返回 chain 自身实现任意层级链式调用。
    """
    mock_db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        chain.filter.return_value = chain
        chain.order_by.return_value = chain
        if model is StrategyInstance:
            chain.all.return_value = instances
        elif model is PnlRecord:
            chain.first.return_value = pnl_record
        return chain

    mock_db.query.side_effect = query_side_effect
    return mock_db


@pytest.fixture(autouse=True)
def _stub_notification():
    """禁用真实通知，避免测试副作用。"""
    with patch("services.notification_service.notification_service") as mock_ns:
        mock_ns.notify = AsyncMock(return_value=0)
        yield


# ============================================================
# SubTask 5.1: check_position_conflict 测试
# ============================================================


class TestCheckPositionConflict:
    async def test_no_other_strategies_returns_true(self):
        """无其他策略占用时返回 True。"""
        params = {"symbol": "ETH-USDT-SWAP", "investment_amount": 1000}
        strategy, db = _make_strategy(params)
        # 模拟无其他策略
        db = _make_conflict_mock_db(instances=[], pnl_record=None)
        strategy.db_session_factory = MagicMock(return_value=db)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "2.0"})
        strategy.client = mock_client

        # real_pos=2.0, others_occupied=0, available=2.0, close_qty=1.0 → True
        result = await strategy.check_position_conflict("ETH-USDT-SWAP", 1.0)
        assert result is True

    async def test_conflict_returns_false_and_records_event(self):
        """其他策略占用导致可用不足时返回 False 并记录 position_conflict 事件。"""
        params = {"symbol": "ETH-USDT-SWAP", "investment_amount": 1000}
        strategy, _ = _make_strategy(params)

        # 1 个其他策略，虚拟持仓 1.5
        others = [_make_instance(2)]
        pnl_record = _make_pnl_record(net_position=1.5)
        db = _make_conflict_mock_db(instances=others, pnl_record=pnl_record)
        strategy.db_session_factory = MagicMock(return_value=db)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "2.0"})
        strategy.client = mock_client

        # real_pos=2.0, others_occupied=1.5, available=0.5, close_qty=1.0 > 0.5 → False
        with patch.object(strategy, "_record_event") as mock_record:
            result = await strategy.check_position_conflict("ETH-USDT-SWAP", 1.0)

        assert result is False
        # position_conflict 事件被记录
        mock_record.assert_called()
        call_args = mock_record.call_args
        assert call_args.args[0] == "position_conflict"
        details = call_args.args[2]
        assert details["close_qty"] == pytest.approx(1.0)
        assert details["real_pos"] == pytest.approx(2.0)
        assert details["others_occupied"] == pytest.approx(1.5)
        assert details["available"] == pytest.approx(0.5)

    async def test_just_enough_returns_true(self):
        """可用仓位刚好等于 close_qty 时返回 True。"""
        params = {"symbol": "ETH-USDT-SWAP", "investment_amount": 1000}
        strategy, _ = _make_strategy(params)

        # 1 个其他策略，虚拟持仓 1.0
        others = [_make_instance(2)]
        pnl_record = _make_pnl_record(net_position=1.0)
        db = _make_conflict_mock_db(instances=others, pnl_record=pnl_record)
        strategy.db_session_factory = MagicMock(return_value=db)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "2.0"})
        strategy.client = mock_client

        # real_pos=2.0, others_occupied=1.0, available=1.0, close_qty=1.0 → 1.0 > 1.0 False → True
        result = await strategy.check_position_conflict("ETH-USDT-SWAP", 1.0)
        assert result is True

    async def test_negative_real_position_uses_abs(self):
        """真实持仓为负（空头）时取绝对值计算可用仓位。"""
        params = {"symbol": "ETH-USDT-SWAP", "investment_amount": 1000}
        strategy, _ = _make_strategy(params)

        others = [_make_instance(2)]
        pnl_record = _make_pnl_record(net_position=1.0)
        db = _make_conflict_mock_db(instances=others, pnl_record=pnl_record)
        strategy.db_session_factory = MagicMock(return_value=db)

        mock_client = AsyncMock()
        # 空头持仓 pos="-2.0"（带符号），其他策略多头 +1.0
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "-2.0"})
        strategy.client = mock_client

        # real_pos=-2.0, others_occupied=+1.0, available=-3.0,
        # real_pos<0 → usable=max(0,-(-3.0))=3.0, close_qty=1.0, 1>3=False → True
        result = await strategy.check_position_conflict("ETH-USDT-SWAP", 1.0)
        assert result is True


# ============================================================
# Task 6: 代数和冲突校验测试（多空对冲不误报）
# ============================================================


class TestAlgebraicConflict:
    """代数和冲突校验测试。

    验证多策略虚拟持仓代数叠加 = 真实持仓（"傅里叶叠加"原理），
    多空对冲策略（A=+5, B=-5, real=0）不应被误报冲突。
    """

    async def test_hedge_long_short_not_false_positive(self):
        """多空对冲不误报：A=+5, B=-5, real=0, A 平 5 → 不冲突。

        others_occupied=-5, available=0-(-5)=5, real_pos==0 → usable=abs(5)=5,
        close_qty=5, 5>5=False → 不冲突。
        """
        params = {"symbol": "ETH-USDT-SWAP", "investment_amount": 1000}
        strategy, _ = _make_strategy(params)
        # B 策略虚拟持仓 -5（空头）
        others = [_make_instance(2)]
        pnl_record = _make_pnl_record(net_position=-5.0)
        db = _make_conflict_mock_db(instances=others, pnl_record=pnl_record)
        strategy.db_session_factory = MagicMock(return_value=db)

        mock_client = AsyncMock()
        # 真实持仓 0（A +5 与 B -5 完全对冲）
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "0"})
        strategy.client = mock_client

        result = await strategy.check_position_conflict("ETH-USDT-SWAP", 5.0)
        assert result is True

    async def test_same_direction_long_normal(self):
        """单向持仓正常：A=+10, B=+5, real=+15, A 平 10 → 不冲突。

        others_occupied=+5, available=15-5=10, real_pos>0 → usable=max(0,10)=10,
        close_qty=10, 10>10=False → 不冲突。
        """
        params = {"symbol": "ETH-USDT-SWAP", "investment_amount": 1000}
        strategy, _ = _make_strategy(params)
        # B 策略虚拟持仓 +5（多头）
        others = [_make_instance(2)]
        pnl_record = _make_pnl_record(net_position=5.0)
        db = _make_conflict_mock_db(instances=others, pnl_record=pnl_record)
        strategy.db_session_factory = MagicMock(return_value=db)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "15"})
        strategy.client = mock_client

        result = await strategy.check_position_conflict("ETH-USDT-SWAP", 10.0)
        assert result is True

    async def test_exceed_real_position_conflicts(self):
        """超真实持仓才冲突：A=+10, B=+5, real=+15, A 平 12 → 冲突。

        others_occupied=+5, available=15-5=10, real_pos>0 → usable=max(0,10)=10,
        close_qty=12, 12>10=True → 冲突。
        """
        params = {"symbol": "ETH-USDT-SWAP", "investment_amount": 1000}
        strategy, _ = _make_strategy(params)
        others = [_make_instance(2)]
        pnl_record = _make_pnl_record(net_position=5.0)
        db = _make_conflict_mock_db(instances=others, pnl_record=pnl_record)
        strategy.db_session_factory = MagicMock(return_value=db)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "15"})
        strategy.client = mock_client

        with patch.object(strategy, "_record_event") as mock_record:
            result = await strategy.check_position_conflict("ETH-USDT-SWAP", 12.0)

        assert result is False
        # 验证事件详情中的代数和字段（带符号）
        mock_record.assert_called_once()
        details = mock_record.call_args.args[2]
        assert details["real_pos"] == pytest.approx(15.0)
        assert details["others_occupied"] == pytest.approx(5.0)
        assert details["available"] == pytest.approx(10.0)

    async def test_short_position_no_conflict(self):
        """空头持仓：A=-10, B=-5, real=-15, A 平 10 → 不冲突。

        others_occupied=-5, available=-15-(-5)=-10, real_pos<0 → usable=max(0,-(-10))=10,
        close_qty=10, 10>10=False → 不冲突。
        """
        params = {"symbol": "ETH-USDT-SWAP", "investment_amount": 1000}
        strategy, _ = _make_strategy(params)
        # B 策略虚拟持仓 -5（空头）
        others = [_make_instance(2)]
        pnl_record = _make_pnl_record(net_position=-5.0)
        db = _make_conflict_mock_db(instances=others, pnl_record=pnl_record)
        strategy.db_session_factory = MagicMock(return_value=db)

        mock_client = AsyncMock()
        # 真实持仓 -15（空头）
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "-15"})
        strategy.client = mock_client

        result = await strategy.check_position_conflict("ETH-USDT-SWAP", 10.0)
        assert result is True


# ============================================================
# SubTask 5.1: close_position_with_conflict_check 测试
# ============================================================


class TestClosePositionWithConflictCheck:
    async def test_conflict_returns_rejection_and_skips_client(self):
        """冲突时返回拒绝响应且不调 client.place_order。"""
        params = {"symbol": "ETH-USDT-SWAP", "investment_amount": 1000}
        strategy, _ = _make_strategy(params)

        # 其他策略占用导致冲突
        others = [_make_instance(2)]
        pnl_record = _make_pnl_record(net_position=1.5)
        db = _make_conflict_mock_db(instances=others, pnl_record=pnl_record)
        strategy.db_session_factory = MagicMock(return_value=db)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "2.0"})
        mock_client.place_order = AsyncMock(return_value={"code": "0"})
        strategy.client = mock_client

        # close_qty=1.0 > available=0.5 → 冲突
        result = await strategy.close_position_with_conflict_check(
            symbol="ETH-USDT-SWAP", side="sell", ord_type="limit", sz="1.0", px="3000",
        )

        assert result["code"] == "-1"
        assert result["msg"] == "position_conflict"
        # client.place_order 未被调用
        mock_client.place_order.assert_not_awaited()

    async def test_no_conflict_calls_client_place_order(self):
        """无冲突时正常调 client.place_order。"""
        params = {"symbol": "ETH-USDT-SWAP", "investment_amount": 1000}
        strategy, _ = _make_strategy(params)

        # 无其他策略
        db = _make_conflict_mock_db(instances=[], pnl_record=None)
        strategy.db_session_factory = MagicMock(return_value=db)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "2.0"})
        mock_client.place_order = AsyncMock(return_value={"code": "0", "data": [{"sCode": "0"}]})
        strategy.client = mock_client

        result = await strategy.close_position_with_conflict_check(
            symbol="ETH-USDT-SWAP", side="sell", ord_type="limit", sz="1.0", px="3000",
        )

        assert result["code"] == "0"
        mock_client.place_order.assert_awaited_once()


# ============================================================
# SubTask 5.1: 节流测试
# ============================================================


class TestConflictCheckThrottle:
    async def test_throttle_skips_api_within_interval(self):
        """10s 内第二次调用不查 API（get_position_risk 只调一次）。"""
        params = {"symbol": "ETH-USDT-SWAP", "investment_amount": 1000}
        strategy, _ = _make_strategy(params)

        db = _make_conflict_mock_db(instances=[], pnl_record=None)
        strategy.db_session_factory = MagicMock(return_value=db)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "2.0"})
        strategy.client = mock_client

        # 第一次调用：查 API
        result1 = await strategy.check_position_conflict("ETH-USDT-SWAP", 1.0)
        assert result1 is True

        # 第二次调用（立即）：节流，不查 API
        result2 = await strategy.check_position_conflict("ETH-USDT-SWAP", 1.0)
        assert result2 is True

        # get_position_risk 只被调用一次（节流生效）
        assert mock_client.get_position_risk.await_count == 1


# ============================================================
# SubTask 5.2: /api/monitoring/position_conflicts 端点测试
# ============================================================


class TestPositionConflictsEndpoint:
    async def test_endpoint_returns_correct_structure(self):
        """端点返回结构正确：account_id / conflicts / total + 每项字段齐全。"""
        from routers.monitoring import get_position_conflicts

        # 2 个实例，各持 1.0，真实持仓 2.0
        instances = [_make_instance(1), _make_instance(2)]
        pnl_record = _make_pnl_record(net_position=1.0)
        mock_db = _make_conflict_mock_db(instances=instances, pnl_record=pnl_record)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "2.0"})

        with patch(
            "services.pnl_accounting_engine.pnl_accounting_engine._get_client",
            AsyncMock(return_value=mock_client),
        ):
            result = await get_position_conflicts(
                account_id=1, db=mock_db, user=MagicMock(),
            )

        assert result["account_id"] == 1
        assert "conflicts" in result
        assert "total" in result
        assert result["total"] == 2
        assert isinstance(result["conflicts"], list)

        # 每项字段齐全
        for item in result["conflicts"]:
            assert "strategy_instance_id" in item
            assert "symbol" in item
            assert "net_position" in item
            assert "others_occupied" in item
            assert "available" in item
            assert "is_conflict" in item

        # real_pos=2.0, others_occupied=1.0, available=1.0
        # is_conflict = 1.0 < 0 (False) or 1.0 < 1.0 (False) → False
        for item in result["conflicts"]:
            assert item["is_conflict"] is False
            assert item["available"] == pytest.approx(1.0, rel=1e-9)

    async def test_endpoint_detects_conflict(self):
        """真实持仓不足以覆盖其他策略占用时标记冲突。"""
        from routers.monitoring import get_position_conflicts

        # 2 个实例各持 1.0，真实持仓仅 1.5
        instances = [_make_instance(1), _make_instance(2)]
        pnl_record = _make_pnl_record(net_position=1.0)
        mock_db = _make_conflict_mock_db(instances=instances, pnl_record=pnl_record)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "1.5"})

        with patch(
            "services.pnl_accounting_engine.pnl_accounting_engine._get_client",
            AsyncMock(return_value=mock_client),
        ):
            result = await get_position_conflicts(
                account_id=1, db=mock_db, user=MagicMock(),
            )

        # available = 1.5 - 1.0 = 0.5 < abs(1.0) → 冲突
        for item in result["conflicts"]:
            assert item["is_conflict"] is True
            assert item["available"] == pytest.approx(0.5, rel=1e-9)

    async def test_endpoint_no_instances_returns_empty(self):
        """无活跃策略时返回空列表。"""
        from routers.monitoring import get_position_conflicts

        mock_db = _make_conflict_mock_db(instances=[], pnl_record=None)

        result = await get_position_conflicts(
            account_id=1, db=mock_db, user=MagicMock(),
        )

        assert result["account_id"] == 1
        assert result["conflicts"] == []
        assert result["total"] == 0
