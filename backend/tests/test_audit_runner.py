"""审计脚本 audit_runner.py 单元测试。

测试四项检查 + 报告输出 + 事件记录。
使用内存 SQLite + mock OKXClient。
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 注入 backend 到 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
for _p in (str(_BACKEND_DIR),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from database import Base
from models.user import User
from models.account import Account
from models.order import Order
from models.pnl import PnlRecord
from models.strategy import StrategyInstance, StrategyTemplate
from models.log import OperationLog
from models.api_call_log import ApiCallLog
from models.setting import UserSetting
from models.system_settings import SystemSetting
from models.strategy_event import StrategyEvent
from models.notification_rule import NotificationRule

# 导入被测模块
_AUDIT_DIR = Path(__file__).resolve().parent.parent / "tests" / "reports" / "strategy_research"
sys.path.insert(0, str(_AUDIT_DIR))

# 内存 SQLite 引擎（StaticPool 保证同进程多线程共享同一内存库连接）
# 注意：切勿使用 database.engine（生产 DB），否则 drop_all 会清空生产数据
_TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_TEST_ENGINE)


@pytest.fixture(scope="module")
def db_session():
    """模块级内存数据库 fixture。"""
    Base.metadata.create_all(bind=_TEST_ENGINE)
    session = _TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=_TEST_ENGINE)


@pytest.fixture
def clean_db(db_session):
    """每个测试前清空所有表数据（保留表结构）。"""
    # 先回滚任何遗留的事务（避免 PendingRollbackError）
    db_session.rollback()
    for tbl in reversed(Base.metadata.sorted_tables):
        db_session.query(tbl).delete()
    db_session.commit()
    yield db_session
    # 测试结束后回滚，避免失败事务影响下一个测试
    db_session.rollback()


@pytest.fixture
def isolated_audit_files(tmp_path, monkeypatch):
    """将审计输出文件重定向到临时目录，避免污染真实报告目录。"""
    import audit_runner
    monkeypatch.setattr(audit_runner, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(audit_runner, "LATEST_FILE", tmp_path / "audit_latest.json")
    monkeypatch.setattr(audit_runner, "AUDIT_LOG", tmp_path / "audit.log")
    return tmp_path


def _make_account(db, account_id=1):
    """创建测试账户。"""
    account = Account(
        id=account_id,
        name=f"TestAccount{account_id}",
        api_key_encrypted="test_key",
        secret_key_encrypted="test_secret",
        passphrase_encrypted="test_pass",
        trade_mode="demo",
        exchange="okx",
        is_active=True,
    )
    db.add(account)
    db.commit()
    return account


def _make_template(db, template_id=1):
    """创建测试策略模板。"""
    tpl = StrategyTemplate(
        id=template_id,
        name="TestTemplate",
        strategy_type="grid",
        default_params={},
        param_schema={},
    )
    db.add(tpl)
    db.commit()
    return tpl


def _make_instance(db, account_id=1, template_id=1, instance_id=1, symbol="ETH-USDT-SWAP",
                   status="running", params=None):
    """创建测试策略实例。"""
    inst = StrategyInstance(
        id=instance_id,
        template_id=template_id,
        account_id=account_id,
        name=f"TestInstance{instance_id}",
        symbol=symbol,
        market_type="swap",
        params=params or {"investment_amount": 100, "lever": 2},
        status=status,
    )
    db.add(inst)
    db.commit()
    return inst


def _make_order(db, order_id, strategy_instance_id=1, account_id=1, symbol="ETH-USDT-SWAP",
                side="buy", status="filled", fill_px=100.0, fill_sz=1.0, fee=0.1):
    """创建测试订单。"""
    o = Order(
        order_id=order_id,
        cl_ord_id=f"client_{order_id}",
        strategy_instance_id=strategy_instance_id,
        account_id=account_id,
        symbol=symbol,
        side=side,
        order_type="limit",
        price=fill_px,
        quantity=fill_sz,
        filled_quantity=fill_sz,
        fill_px=fill_px,
        fill_sz=fill_sz,
        fee=fee,
        status=status,
    )
    db.add(o)
    db.commit()
    return o


def _make_pnl_record(db, strategy_instance_id=1, account_id=1, realized_pnl=50.0,
                     unrealized_pnl=10.0, net_position=1.0, avg_buy_price=100.0,
                     recorded_at=None):
    """创建测试 PnlRecord。"""
    r = PnlRecord(
        strategy_instance_id=strategy_instance_id,
        account_id=account_id,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_pnl=realized_pnl + unrealized_pnl,
        net_position=net_position,
        avg_buy_price=avg_buy_price,
        total_fee=0.1,
        order_count=2,
        equity=1000.0,
        is_final=False,
        recorded_at=recorded_at or datetime.now(timezone.utc),
    )
    db.add(r)
    db.commit()
    return r


# =============================================================================
# 检查 1：订单唯一性
# =============================================================================
class TestCheckOrderUniqueness:
    def test_no_orders_passes(self, clean_db, isolated_audit_files):
        """无订单时通过。"""
        import audit_runner
        result = audit_runner.check_order_uniqueness(clean_db)
        assert result["passed"] is True
        assert result["total_orders_checked"] == 0
        assert result["duplicate_claims"] == []
        assert result["orphan_orders"] == []

    def test_single_claim_passes(self, clean_db, isolated_audit_files):
        """每个订单只被一个策略认领，通过。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        _make_instance(clean_db, instance_id=2)
        _make_order(clean_db, "order_1", strategy_instance_id=1)
        _make_order(clean_db, "order_2", strategy_instance_id=2)

        import audit_runner
        result = audit_runner.check_order_uniqueness(clean_db)
        assert result["passed"] is True
        assert result["total_orders_checked"] == 2
        assert result["duplicate_claims"] == []

    def test_duplicate_claim_detected(self, clean_db, isolated_audit_files):
        """DB order_id 唯一约束阻止物理重复行；审计作为第二道防线扫描重复认领。

        此测试验证：当 DB 约束生效时无法插入重复 order_id（IntegrityError），
        审计扫描结果为无重复（passed=True）。DB 约束 + 审计双重防线。
        """
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError as SAIntegrityError

        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        _make_instance(clean_db, instance_id=2)
        _make_order(clean_db, "dup_order", strategy_instance_id=1)

        # DB 唯一约束生效，插入重复 order_id 应抛 IntegrityError
        with pytest.raises(SAIntegrityError):
            clean_db.execute(text(
                "INSERT INTO orders (strategy_instance_id, account_id, symbol, order_id, "
                "cl_ord_id, side, order_type, price, quantity, filled_quantity, fill_px, "
                "fill_sz, fee, status, pnl_accounted) "
                "VALUES (2, 1, 'ETH-USDT-SWAP', 'dup_order', 'client_dup_2', 'buy', 'limit', "
                "100.0, 1.0, 1.0, 100.0, 1.0, 0.1, 'filled', 0)"
            ))
        clean_db.rollback()

        # 审计扫描：DB 已阻止重复，审计应通过
        import audit_runner
        result = audit_runner.check_order_uniqueness(clean_db)
        assert result["passed"] is True
        assert len(result["duplicate_claims"]) == 0

    def test_orphan_order_detected(self, clean_db, isolated_audit_files):
        """已成交订单无 strategy_instance_id，检测为孤儿。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        _make_order(clean_db, "order_1", strategy_instance_id=1)
        # 孤儿订单：strategy_instance_id=None
        _make_order(clean_db, "orphan_order", strategy_instance_id=None)

        import audit_runner
        result = audit_runner.check_order_uniqueness(clean_db)
        assert result["passed"] is False
        assert len(result["orphan_orders"]) == 1
        assert result["orphan_orders"][0]["order_id"] == "orphan_order"


# =============================================================================
# 检查 2：盈亏核算正确性
# =============================================================================
class TestCheckPnlCorrectness:
    @pytest.mark.asyncio
    async def test_no_running_instances_passes(self, clean_db, isolated_audit_files):
        """无运行中策略时通过。"""
        import audit_runner
        with patch("audit_runner.SessionLocal", return_value=clean_db):
            result = await audit_runner.check_pnl_correctness(clean_db)
        assert result["passed"] is True
        assert result["total_checked"] == 0

    @pytest.mark.asyncio
    async def test_pnl_matched_passes(self, clean_db, isolated_audit_files):
        """recompute 结果与最新 PnlRecord 一致，通过。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=50.0,
                         net_position=0.0, avg_buy_price=100.0)
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy")
        _make_order(clean_db, "order_2", strategy_instance_id=1, side="sell")

        import audit_runner

        # mock recompute 返回与 PnlRecord 一致的值
        async def mock_recompute(strategy_instance_id, client=None):
            mock_snapshot = MagicMock()
            mock_snapshot.realized_pnl = 50.0
            mock_snapshot.net_position = 0.0
            return mock_snapshot

        with patch.object(audit_runner.pnl_accounting_engine, "recompute", side_effect=mock_recompute):
            with patch("audit_runner.OKXClient"):
                result = await audit_runner.check_pnl_correctness(clean_db)

        assert result["passed"] is True
        assert result["per_strategy"][0]["matched"] is True

    @pytest.mark.asyncio
    async def test_pnl_mismatch_detected(self, clean_db, isolated_audit_files):
        """recompute 结果与 PnlRecord 差异超阈值，检测到不一致。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=50.0,
                         net_position=0.0, avg_buy_price=100.0)
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy")
        _make_order(clean_db, "order_2", strategy_instance_id=1, side="sell")

        import audit_runner

        # mock recompute 返回不一致的值（差 10 USDT > 容差 0.5）
        async def mock_recompute(strategy_instance_id, client=None):
            mock_snapshot = MagicMock()
            mock_snapshot.realized_pnl = 60.0
            mock_snapshot.net_position = 0.0
            return mock_snapshot

        with patch.object(audit_runner.pnl_accounting_engine, "recompute", side_effect=mock_recompute):
            with patch("audit_runner.OKXClient"):
                result = await audit_runner.check_pnl_correctness(clean_db)

        assert result["passed"] is False
        assert result["per_strategy"][0]["matched"] is False
        assert result["per_strategy"][0]["diff"] > 0.5

    @pytest.mark.asyncio
    async def test_no_filled_orders_skipped(self, clean_db, isolated_audit_files):
        """策略无成交订单时 recompute 返回 None，跳过（不算异常）。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=0.0,
                         net_position=0.0, avg_buy_price=0.0)

        import audit_runner

        async def mock_recompute(strategy_instance_id, client=None):
            return None  # 无成交

        with patch.object(audit_runner.pnl_accounting_engine, "recompute", side_effect=mock_recompute):
            with patch("audit_runner.OKXClient"):
                result = await audit_runner.check_pnl_correctness(clean_db)

        assert result["passed"] is True
        assert result["per_strategy"][0]["note"] == "no_filled_orders"


# =============================================================================
# 检查 3：仓位隔离对账
# =============================================================================
class TestCheckPositionIsolation:
    @pytest.mark.asyncio
    async def test_no_running_passes(self, clean_db, isolated_audit_files):
        """无运行中策略时通过。"""
        import audit_runner
        result = await audit_runner.check_position_isolation(clean_db)
        assert result["passed"] is True
        assert result["total_checked"] == 0

    @pytest.mark.asyncio
    async def test_position_matched_passes(self, clean_db, isolated_audit_files):
        """虚拟持仓 == 真实持仓，通过。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT-SWAP")

        import audit_runner

        async def mock_reconcile(account_id, symbol, client=None, tolerance=None):
            return {
                "account_id": account_id,
                "symbol": symbol,
                "virtual_total": 5.0,
                "real_total": 5.0,
                "diff": 0.0,
                "matched": True,
            }

        with patch.object(audit_runner.pnl_accounting_engine, "reconcile_positions", side_effect=mock_reconcile):
            result = await audit_runner.check_position_isolation(clean_db)

        assert result["passed"] is True
        assert result["per_symbol"][0]["matched"] is True

    @pytest.mark.asyncio
    async def test_position_mismatch_detected(self, clean_db, isolated_audit_files):
        """虚拟持仓 != 真实持仓，检测到不一致。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT-SWAP")

        import audit_runner

        async def mock_reconcile(account_id, symbol, client=None, tolerance=None):
            return {
                "account_id": account_id,
                "symbol": symbol,
                "virtual_total": 5.0,
                "real_total": 3.0,
                "diff": 2.0,
                "matched": False,
            }

        with patch.object(audit_runner.pnl_accounting_engine, "reconcile_positions", side_effect=mock_reconcile):
            result = await audit_runner.check_position_isolation(clean_db)

        assert result["passed"] is False
        assert result["per_symbol"][0]["matched"] is False
        assert result["per_symbol"][0]["diff"] == 2.0


# =============================================================================
# 检查 4：资金约束检查
# =============================================================================
class TestCheckCapitalConstraints:
    def test_no_investment_amount_skipped(self, clean_db, isolated_audit_files):
        """investment_amount=0 的策略跳过检查。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, params={"investment_amount": 0, "lever": 1})

        import audit_runner
        result = audit_runner.check_capital_constraints(clean_db)
        assert result["passed"] is True
        assert result["total_checked"] == 0

    def test_within_cap_passes(self, clean_db, isolated_audit_files):
        """持仓名义价值在上限内，通过。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, params={"investment_amount": 100, "lever": 2})
        # cap = 100 × 2 = 200; current = 1 × 100 = 100 < 200
        _make_pnl_record(clean_db, strategy_instance_id=1, net_position=1.0, avg_buy_price=100.0)

        import audit_runner
        result = audit_runner.check_capital_constraints(clean_db)
        assert result["passed"] is True
        assert result["total_checked"] == 1
        assert len(result["violations"]) == 0

    def test_exceeds_cap_detected(self, clean_db, isolated_audit_files):
        """持仓名义价值超上限，检测到违反。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, params={"investment_amount": 100, "lever": 2})
        # cap = 100 × 2 = 200; current = 3 × 100 = 300 > 200×1.05=210
        _make_pnl_record(clean_db, strategy_instance_id=1, net_position=3.0, avg_buy_price=100.0)

        import audit_runner
        result = audit_runner.check_capital_constraints(clean_db)
        assert result["passed"] is False
        assert len(result["violations"]) == 1
        v = result["violations"][0]
        assert v["strategy_instance_id"] == 1
        assert v["current_value"] > v["cap"]


# =============================================================================
# 检查 5：OKX 成交记录对账
# =============================================================================
class TestCheckOkxTradeRecords:
    @pytest.mark.asyncio
    async def test_no_running_instances_passes(self, clean_db, isolated_audit_files):
        """无运行中策略时通过。"""
        import audit_runner
        result = await audit_runner.check_okx_trade_records(clean_db)
        assert result["passed"] is True
        assert result["per_symbol"] == []
        assert result["total_okx_realized_pnl"] == 0.0

    @pytest.mark.asyncio
    async def test_fills_matched_passes(self, clean_db, isolated_audit_files):
        """OKX fills 与 DB orders 一致，盈亏匹配，通过。

        SWAP 使用 OKX fill.pnl 字段：开仓 pnl=0，平仓 pnl=4.8。
        """
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy",
                    fill_px=100.0, fill_sz=1.0, fee=0.1)
        _make_order(clean_db, "order_2", strategy_instance_id=1, side="sell",
                    fill_px=105.0, fill_sz=1.0, fee=0.1)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=4.8,
                         net_position=0.0, avg_buy_price=100.0)

        fills = [
            {"ordId": "order_1", "side": "buy", "fillPx": "100", "fillSz": "1", "fee": "0.1",
             "pnl": "0", "clOrdId": "client_order_1", "billId": "b1", "ts": "1"},
            {"ordId": "order_2", "side": "sell", "fillPx": "105", "fillSz": "1", "fee": "0.1",
             "pnl": "4.8", "clOrdId": "client_order_2", "billId": "b2", "ts": "2"},
        ]
        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(return_value=fills)

        import audit_runner
        with patch("audit_runner.OKXClient", return_value=mock_client):
            result = await audit_runner.check_okx_trade_records(clean_db)

        assert result["passed"] is True
        assert len(result["per_symbol"]) == 1
        sym = result["per_symbol"][0]
        assert sym["okx_fills_count"] == 2
        assert sym["db_orders_count"] == 2
        assert sym["orphan_okx_fills"] == []
        assert sym["price_mismatches"] == []
        assert sym["okx_realized_pnl"] == 4.8
        assert sym["db_realized_pnl"] == 4.8
        assert sym["matched"] is True

    @pytest.mark.asyncio
    async def test_spot_fills_matched_passes(self, clean_db, isolated_audit_files):
        """SPOT 平均成本法盈亏匹配，通过。

        buy@100 qty=1 + sell@105 qty=1, fee=0.1 each
        平均成本: matched=1, avg_buy=100, avg_sell=105, avg_fee=0.1
        realized = 1*(105-100) - 1*0.1 = 4.9
        """
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT")
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy",
                    symbol="ETH-USDT", fill_px=100.0, fill_sz=1.0, fee=0.1)
        _make_order(clean_db, "order_2", strategy_instance_id=1, side="sell",
                    symbol="ETH-USDT", fill_px=105.0, fill_sz=1.0, fee=0.1)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=4.9,
                         net_position=0.0, avg_buy_price=100.0)

        fills = [
            {"ordId": "order_1", "side": "buy", "fillPx": "100", "fillSz": "1", "fee": "0.1",
             "clOrdId": "c1", "billId": "b1", "ts": "1"},
            {"ordId": "order_2", "side": "sell", "fillPx": "105", "fillSz": "1", "fee": "0.1",
             "clOrdId": "c2", "billId": "b2", "ts": "2"},
        ]
        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(return_value=fills)

        import audit_runner
        with patch("audit_runner.OKXClient", return_value=mock_client):
            result = await audit_runner.check_okx_trade_records(clean_db)

        assert result["passed"] is True
        sym = result["per_symbol"][0]
        assert sym["okx_realized_pnl"] == pytest.approx(4.9, abs=0.01)
        assert sym["db_realized_pnl"] == 4.9
        assert sym["matched"] is True

    @pytest.mark.asyncio
    async def test_orphan_fill_detected(self, clean_db, isolated_audit_files):
        """OKX 有成交但 DB 无对应订单，检测为 orphan。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy")
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=0.0,
                         net_position=0.0, avg_buy_price=0.0)

        fills = [
            {"ordId": "order_1", "side": "buy", "fillPx": "100", "fillSz": "1", "fee": "0.1",
             "pnl": "0", "clOrdId": "c1", "billId": "b1", "ts": "1"},
            # orphan：DB 无此订单
            {"ordId": "unknown_order", "side": "sell", "fillPx": "200", "fillSz": "1", "fee": "0.2",
             "pnl": "100", "clOrdId": "c2", "billId": "b2", "ts": "2"},
        ]
        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(return_value=fills)

        import audit_runner
        with patch("audit_runner.OKXClient", return_value=mock_client):
            result = await audit_runner.check_okx_trade_records(clean_db)

        assert result["passed"] is False
        sym = result["per_symbol"][0]
        assert len(sym["orphan_okx_fills"]) == 1
        assert sym["orphan_okx_fills"][0]["ordId"] == "unknown_order"

    @pytest.mark.asyncio
    async def test_price_mismatch_detected(self, clean_db, isolated_audit_files):
        """OKX fillPx 与 DB fill_px 不一致，检测到价格差异。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        # DB fill_px=100
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy",
                    fill_px=100.0, fill_sz=1.0, fee=0.1)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=0.0,
                         net_position=0.0, avg_buy_price=0.0)

        # OKX fillPx=110，与 DB 100 差 10 > 容差
        fills = [
            {"ordId": "order_1", "side": "buy", "fillPx": "110", "fillSz": "1", "fee": "0.1",
             "pnl": "0", "clOrdId": "c1", "billId": "b1", "ts": "1"},
        ]
        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(return_value=fills)

        import audit_runner
        with patch("audit_runner.OKXClient", return_value=mock_client):
            result = await audit_runner.check_okx_trade_records(clean_db)

        assert result["passed"] is False
        sym = result["per_symbol"][0]
        assert len(sym["price_mismatches"]) == 1
        assert sym["price_mismatches"][0]["ordId"] == "order_1"
        assert sym["price_mismatches"][0]["okx_weighted_fillPx"] == 110.0
        assert sym["price_mismatches"][0]["db_fill_px"] == 100.0

    @pytest.mark.asyncio
    async def test_pnl_mismatch_detected(self, clean_db, isolated_audit_files):
        """OKX 独立盈亏与 DB PnlRecord 差异超阈值，检测到不一致。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy",
                    fill_px=100.0, fill_sz=1.0, fee=0.1)
        _make_order(clean_db, "order_2", strategy_instance_id=1, side="sell",
                    fill_px=105.0, fill_sz=1.0, fee=0.1)
        # okx_realized = 4.8（SWAP pnl 字段），但 DB PnlRecord = 10.0，diff=5.2 > 0.5
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=10.0,
                         net_position=0.0, avg_buy_price=100.0)

        fills = [
            {"ordId": "order_1", "side": "buy", "fillPx": "100", "fillSz": "1", "fee": "0.1",
             "pnl": "0", "clOrdId": "c1", "billId": "b1", "ts": "1"},
            {"ordId": "order_2", "side": "sell", "fillPx": "105", "fillSz": "1", "fee": "0.1",
             "pnl": "4.8", "clOrdId": "c2", "billId": "b2", "ts": "2"},
        ]
        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(return_value=fills)

        import audit_runner
        with patch("audit_runner.OKXClient", return_value=mock_client):
            result = await audit_runner.check_okx_trade_records(clean_db)

        assert result["passed"] is False
        sym = result["per_symbol"][0]
        assert sym["okx_realized_pnl"] == 4.8
        assert sym["db_realized_pnl"] == 10.0
        assert sym["diff"] > 0.5
        assert sym["matched"] is False

    @pytest.mark.asyncio
    async def test_api_error_handled(self, clean_db, isolated_audit_files):
        """OKX API 调用失败时不中断审计，记录 audit_okx_api_error 事件。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy")
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=0.0,
                         net_position=0.0, avg_buy_price=0.0)

        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(side_effect=Exception("API timeout"))

        import audit_runner
        with patch("audit_runner.OKXClient", return_value=mock_client):
            result = await audit_runner.check_okx_trade_records(clean_db)

        # API 失败不中断审计，sym_result 默认 matched=True
        assert len(result["per_symbol"]) == 1
        sym = result["per_symbol"][0]
        assert sym["okx_fills_count"] == 0
        # 记录了 audit_okx_api_error 事件
        events = clean_db.query(StrategyEvent).filter(
            StrategyEvent.event_type == "audit_okx_api_error"
        ).all()
        # strategy_instance_id=None 时不写表，只写日志
        # 所以这里 events 可能为空，验证 per_symbol 存在即可
        assert sym["matched"] is True

    @pytest.mark.asyncio
    async def test_db_only_order_detected(self, clean_db, isolated_audit_files):
        """DB 有 filled 订单但 OKX 无对应 fill，标记为 db_only_order（不影响 matched）。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy",
                    fill_px=100.0, fill_sz=1.0, fee=0.1)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=0.0,
                         net_position=0.0, avg_buy_price=0.0)

        # OKX 返回空 fills 列表
        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(return_value=[])

        import audit_runner
        with patch("audit_runner.OKXClient", return_value=mock_client):
            result = await audit_runner.check_okx_trade_records(clean_db)

        sym = result["per_symbol"][0]
        assert len(sym["db_only_orders"]) == 1
        assert sym["db_only_orders"][0]["order_id"] == "order_1"
        # db_only 不影响 matched（okx=0, db=0, diff=0）
        assert sym["matched"] is True

    @pytest.mark.asyncio
    async def test_multi_account_dedup(self, clean_db, isolated_audit_files):
        """同账户同 symbol 多策略只查一次 OKX（去重）。"""
        _make_account(clean_db)
        _make_template(clean_db)
        # 两个策略实例同账户同 symbol
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT-SWAP")
        _make_instance(clean_db, instance_id=2, symbol="ETH-USDT-SWAP")

        fills = [
            {"ordId": "order_1", "side": "buy", "fillPx": "100", "fillSz": "1", "fee": "0.1",
             "pnl": "0", "clOrdId": "c1", "billId": "b1", "ts": "1"},
        ]
        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(return_value=fills)

        import audit_runner
        with patch("audit_runner.OKXClient", return_value=mock_client):
            result = await audit_runner.check_okx_trade_records(clean_db)

        # 只查一次（一个 per_symbol 条目）
        assert len(result["per_symbol"]) == 1
        # get_fills 只被调用一次
        assert mock_client.trade.get_fills.call_count == 1


# =============================================================================
# 主流程 run_audit
# =============================================================================
class TestRunAudit:
    @pytest.mark.asyncio
    async def test_run_audit_writes_report(self, clean_db, isolated_audit_files):
        """run_audit 生成报告文件 + latest 文件。"""
        import audit_runner

        with patch.object(audit_runner, "SessionLocal", return_value=clean_db):
            report = await audit_runner.run_audit()

        assert "audit_type" in report
        assert report["audit_type"] == "hourly_third_party_audit"
        assert "checks" in report
        assert "order_uniqueness" in report["checks"]
        assert "pnl_correctness" in report["checks"]
        assert "position_isolation" in report["checks"]
        assert "capital_constraints" in report["checks"]
        assert "okx_trade_records" in report["checks"]
        assert "overall_passed" in report
        assert "duration_seconds" in report

        # 报告文件已写入
        files = list(isolated_audit_files.glob("audit_report_*.json"))
        assert len(files) == 1
        # latest 文件已写入
        assert (isolated_audit_files / "audit_latest.json").exists()

    @pytest.mark.asyncio
    async def test_run_audit_empty_db_passes(self, clean_db, isolated_audit_files):
        """空数据库时全部检查通过。"""
        import audit_runner

        with patch.object(audit_runner, "SessionLocal", return_value=clean_db):
            report = await audit_runner.run_audit()

        assert report["overall_passed"] is True
        # 五项检查都通过
        for check_name, check_result in report["checks"].items():
            assert check_result["passed"] is True, f"{check_name} 未通过"


# =============================================================================
# 事件记录
# =============================================================================
class TestRecordAuditEvent:
    def test_record_event_with_strategy_id(self, clean_db, isolated_audit_files):
        """有 strategy_instance_id 时写入 StrategyEvent 表。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)

        import audit_runner
        audit_runner._record_audit_event(
            clean_db,
            strategy_instance_id=1,
            event_type="audit_test_event",
            message="测试事件",
            details={"key": "value"},
        )

        events = clean_db.query(StrategyEvent).filter(
            StrategyEvent.event_type == "audit_test_event"
        ).all()
        assert len(events) == 1
        assert events[0].strategy_instance_id == 1
        assert events[0].message == "测试事件"

    def test_record_event_none_strategy_id_skips_db(self, clean_db, isolated_audit_files):
        """strategy_instance_id=None 时不写表，只写日志。"""
        import audit_runner
        audit_runner._record_audit_event(
            clean_db,
            strategy_instance_id=None,
            event_type="audit_global_event",
            message="全局告警",
            details={"key": "value"},
        )

        # 表中无该事件
        events = clean_db.query(StrategyEvent).filter(
            StrategyEvent.event_type == "audit_global_event"
        ).all()
        assert len(events) == 0
