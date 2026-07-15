"""虚拟仓位账本与对账单元测试（Task 4: SubTask 4.1-4.4）。

覆盖：
- BaseStrategy.get_virtual_position：有 PnlRecord 返回其值；无记录返回 0/0/_realized_pnl
- BaseStrategy._get_current_position_value：基于虚拟持仓 × 当前价估算名义价值
- PnlAccountingEngine.reconcile_positions：虚拟之和 vs 真实持仓
  - 匹配返回 matched=True
  - 差异超容差返回 matched=False 并触发 position_mismatch
- 差异超容差触发 position_mismatch 通知（检查 notification_service.notify 调用）

参考 test_capital_limit.py / test_pnl_accounting_engine.py 风格，
用 Mock client + Mock db_session_factory + patch SessionLocal。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from strategies.base_strategy import BaseStrategy
from services.pnl_accounting_engine import PnlAccountingEngine
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


def _make_reconcile_mock_db(instances, pnl_record=None):
    """构造 mock DB session，适配 reconcile_positions 的查询链路。

    reconcile_positions 涉及的 query 链路：
      - StrategyInstance: .filter().filter().filter().all() → instances
      - PnlRecord: .filter().order_by().first() → latest pnl record（每个实例一次）

    通过让 filter / order_by 返回 chain 自身实现任意层级链式调用。
    """
    mock_db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        # 自引用：filter / order_by 返回 chain 自身，支持任意层级链式调用
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
# SubTask 4.1: BaseStrategy.get_virtual_position 测试
# ============================================================


def test_get_virtual_position_with_pnl_record_returns_values():
    """有 PnlRecord 时返回其 net_position / avg_buy_price / realized_pnl。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 1000}
    strategy, db = _make_strategy(params)

    # 构造 query 链：filter().order_by().first() 返回 mock PnlRecord
    latest = _make_pnl_record(net_position=1.5, avg_buy_price=50000.0, realized_pnl=120.0)
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.first.return_value = latest
    db.query.return_value = chain

    result = strategy.get_virtual_position()

    assert result["net_position"] == pytest.approx(1.5, rel=1e-9)
    assert result["avg_buy_price"] == pytest.approx(50000.0, rel=1e-9)
    assert result["realized_pnl"] == pytest.approx(120.0, rel=1e-9)


def test_get_virtual_position_without_pnl_record_returns_zeros_and_realized():
    """无 PnlRecord 时返回 0/0/_realized_pnl。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 1000}
    strategy, db = _make_strategy(params)
    strategy._realized_pnl = 88.5

    # 查询返回 None
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.first.return_value = None
    db.query.return_value = chain

    result = strategy.get_virtual_position()

    assert result["net_position"] == 0.0
    assert result["avg_buy_price"] == 0.0
    assert result["realized_pnl"] == pytest.approx(88.5, rel=1e-9)


def test_get_virtual_position_db_exception_returns_fallback():
    """DB 查询异常时返回兜底值（不抛异常）。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 1000}
    strategy, db = _make_strategy(params)
    strategy._realized_pnl = 5.0

    # query 抛异常
    db.query.side_effect = Exception("db error")

    result = strategy.get_virtual_position()

    assert result["net_position"] == 0.0
    assert result["avg_buy_price"] == 0.0
    assert result["realized_pnl"] == pytest.approx(5.0, rel=1e-9)


# ============================================================
# SubTask 4.1: BaseStrategy._get_current_position_value 测试
# ============================================================


def test_get_current_position_value_uses_latest_price():
    """net_position × _latest_price 计算名义价值。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 1000}
    strategy, db = _make_strategy(params)
    strategy._latest_price = 50000.0  # 策略子类维护的最新价

    latest = _make_pnl_record(net_position=0.5, avg_buy_price=48000.0)
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.first.return_value = latest
    db.query.return_value = chain

    # 0.5 × 50000 = 25000
    value = strategy._get_current_position_value("BTC-USDT")
    assert value == pytest.approx(25000.0, rel=1e-9)


def test_get_current_position_value_falls_back_to_market_data():
    """无 _latest_price 时回退到 market_data_service 缓存。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 1000}
    strategy, db = _make_strategy(params)
    # 不设置 _latest_price

    latest = _make_pnl_record(net_position=2.0, avg_buy_price=48000.0)
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.first.return_value = latest
    db.query.return_value = chain

    with patch("services.market_data_service.market_data_service") as mock_mds:
        mock_mds.get_latest_ticker.return_value = {"last": "51000"}
        value = strategy._get_current_position_value("BTC-USDT")

    # 2.0 × 51000 = 102000
    assert value == pytest.approx(102000.0, rel=1e-9)


def test_get_current_position_value_falls_back_to_avg_buy_price():
    """无 _latest_price 且 market_data 无缓存时，用 avg_buy_price 兜底。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 1000}
    strategy, db = _make_strategy(params)

    latest = _make_pnl_record(net_position=1.0, avg_buy_price=45000.0)
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.first.return_value = latest
    db.query.return_value = chain

    with patch("services.market_data_service.market_data_service") as mock_mds:
        mock_mds.get_latest_ticker.return_value = None
        value = strategy._get_current_position_value("BTC-USDT")

    # 1.0 × 45000 = 45000（用 avg_buy_price 兜底）
    assert value == pytest.approx(45000.0, rel=1e-9)


def test_get_current_position_value_zero_position_returns_zero():
    """net_position <= 0 时直接返回 0（不查价格）。"""
    params = {"symbol": "BTC-USDT", "investment_amount": 1000}
    strategy, db = _make_strategy(params)

    latest = _make_pnl_record(net_position=0.0)
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.first.return_value = latest
    db.query.return_value = chain

    assert strategy._get_current_position_value("BTC-USDT") == 0.0


# ============================================================
# SubTask 4.2 / 4.3: PnlAccountingEngine.reconcile_positions 测试
# ============================================================


class TestReconcilePositions:
    async def test_matched_returns_true(self):
        """虚拟持仓之和 == 真实持仓，matched=True。"""
        # 2 个实例，各持 1.0，合计 2.0；真实持仓 pos="2.0"
        instances = [_make_instance(1), _make_instance(2)]
        pnl_record = _make_pnl_record(net_position=1.0)
        mock_db = _make_reconcile_mock_db(instances, pnl_record=pnl_record)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "2.0"})

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            result = await engine.reconcile_positions(
                account_id=1, symbol="ETH-USDT-SWAP", client=mock_client,
            )

        assert result["matched"] is True
        assert result["virtual_total"] == pytest.approx(2.0, rel=1e-9)
        assert result["real_total"] == pytest.approx(2.0, rel=1e-9)
        assert result["diff"] == pytest.approx(0.0, abs=1e-12)
        assert result["symbol"] == "ETH-USDT-SWAP"
        assert result["account_id"] == 1

    async def test_mismatch_returns_false(self):
        """虚拟持仓之和 != 真实持仓，差异超容差时 matched=False。"""
        # 2 个实例各持 1.0，合计 2.0；真实持仓 pos="2.5"，diff=0.5
        instances = [_make_instance(1), _make_instance(2)]
        pnl_record = _make_pnl_record(net_position=1.0)
        mock_db = _make_reconcile_mock_db(instances, pnl_record=pnl_record)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "2.5"})

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            result = await engine.reconcile_positions(
                account_id=1, symbol="ETH-USDT-SWAP", client=mock_client,
            )

        assert result["matched"] is False
        assert result["virtual_total"] == pytest.approx(2.0, rel=1e-9)
        assert result["real_total"] == pytest.approx(2.5, rel=1e-9)
        assert result["diff"] == pytest.approx(0.5, rel=1e-9)
        # 差异超容差时写入 strategy_event
        assert mock_db.add.call_count >= 1

    async def test_mismatch_within_tolerance_returns_true(self):
        """差异在容差内时 matched=True。"""
        instances = [_make_instance(1)]
        pnl_record = _make_pnl_record(net_position=1.0)
        mock_db = _make_reconcile_mock_db(instances, pnl_record=pnl_record)

        mock_client = AsyncMock()
        # 真实持仓 1.00005，diff=0.00005 < tolerance 0.0001
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "1.00005"})

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            result = await engine.reconcile_positions(
                account_id=1, symbol="ETH-USDT-SWAP", client=mock_client,
                tolerance=0.0001,
            )

        assert result["matched"] is True
        assert result["diff"] == pytest.approx(0.00005, rel=1e-9)

    async def test_negative_real_position_matched(self):
        """真实持仓为负（空头）时，与虚拟持仓之和匹配返回 matched=True。"""
        instances = [_make_instance(1)]
        pnl_record = _make_pnl_record(net_position=-1.5)
        mock_db = _make_reconcile_mock_db(instances, pnl_record=pnl_record)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "-1.5"})

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            result = await engine.reconcile_positions(
                account_id=1, symbol="ETH-USDT-SWAP", client=mock_client,
            )

        assert result["matched"] is True
        assert result["virtual_total"] == pytest.approx(-1.5, rel=1e-9)
        assert result["real_total"] == pytest.approx(-1.5, rel=1e-9)

    async def test_no_instances_returns_zero_virtual(self):
        """无活跃策略实例时，virtual_total=0。"""
        mock_db = _make_reconcile_mock_db(instances=[], pnl_record=None)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "0"})

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            result = await engine.reconcile_positions(
                account_id=1, symbol="ETH-USDT-SWAP", client=mock_client,
            )

        assert result["virtual_total"] == 0.0
        assert result["real_total"] == 0.0
        assert result["matched"] is True

    async def test_mismatch_triggers_notification(self):
        """差异超容差时触发 notification_service.notify(position_mismatch)。"""
        instances = [_make_instance(1)]
        pnl_record = _make_pnl_record(net_position=1.0)
        mock_db = _make_reconcile_mock_db(instances, pnl_record=pnl_record)

        mock_client = AsyncMock()
        # 真实持仓 2.0，虚拟 1.0，diff=1.0
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "2.0"})

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db), \
             patch("services.notification_service.notification_service") as mock_ns:
            mock_ns.notify = AsyncMock(return_value=0)
            result = await engine.reconcile_positions(
                account_id=1, symbol="ETH-USDT-SWAP", client=mock_client,
            )

        assert result["matched"] is False
        # 由于在事件循环中，create_task 已调度 notify
        # 让 pending task 执行完
        import asyncio
        await asyncio.sleep(0)
        # notify 至少被调用一次（事件类型为 position_mismatch）
        mock_ns.notify.assert_called()
        call_args = mock_ns.notify.call_args
        assert call_args.args[0] == "position_mismatch"

    async def test_client_none_uses_engine_get_client(self):
        """client=None 且有实例时，延迟调用 _get_client 获取 client。"""
        instances = [_make_instance(1)]
        pnl_record = _make_pnl_record(net_position=1.0)
        mock_db = _make_reconcile_mock_db(instances, pnl_record=pnl_record)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "1.0"})

        get_client_mock = AsyncMock(return_value=mock_client)
        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db), \
             patch.object(engine, "_get_client", get_client_mock):
            result = await engine.reconcile_positions(
                account_id=1, symbol="ETH-USDT-SWAP", client=None,
            )

        assert result["matched"] is True
        # _get_client 被调用
        get_client_mock.assert_awaited()

    async def test_position_risk_none_returns_zero_real(self):
        """交易所返回 None（无持仓）时 real_total=0。"""
        instances = [_make_instance(1)]
        pnl_record = _make_pnl_record(net_position=1.0)
        mock_db = _make_reconcile_mock_db(instances, pnl_record=pnl_record)

        mock_client = AsyncMock()
        mock_client.get_position_risk = AsyncMock(return_value=None)

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            result = await engine.reconcile_positions(
                account_id=1, symbol="ETH-USDT-SWAP", client=mock_client,
            )

        assert result["real_total"] == 0.0
        assert result["virtual_total"] == pytest.approx(1.0, rel=1e-9)
        assert result["matched"] is False  # diff=1.0 > tolerance
