"""功能检测脚本 function_checker.py 单元测试。

测试三项检查 + 主流程 + 事件记录。
使用内存 SQLite + mock OKXClient。
"""
import asyncio
import json
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

# 导入被测模块（与 test_audit_runner.py 同模式）
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
    db_session.rollback()
    for tbl in reversed(Base.metadata.sorted_tables):
        db_session.query(tbl).delete()
    db_session.commit()
    yield db_session
    db_session.rollback()


@pytest.fixture
def isolated_check_files(tmp_path, monkeypatch):
    """将检测输出文件重定向到临时目录，避免污染真实报告目录。"""
    import function_checker
    monkeypatch.setattr(function_checker, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(function_checker, "LATEST_FILE", tmp_path / "function_check_latest.json")
    monkeypatch.setattr(function_checker, "CHECK_LOG", tmp_path / "function_check.log")
    return tmp_path


# =============================================================================
# 辅助构造函数
# =============================================================================
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
        market_type="swap" if "-SWAP" in symbol else "spot",
        params=params or {
            "upper_price": 200.0,
            "lower_price": 100.0,
            "grid_count": 11,
            "order_qty": 1,
            "symbol": symbol,
        },
        status=status,
    )
    db.add(inst)
    db.commit()
    return inst


def _make_order(db, order_id, strategy_instance_id=1, account_id=1, symbol="ETH-USDT-SWAP",
                side="buy", status="live", price=100.0, quantity=1.0,
                fill_px=None, fill_sz=None, fee=None):
    """创建测试订单。"""
    o = Order(
        order_id=order_id,
        cl_ord_id=f"client_{order_id}",
        strategy_instance_id=strategy_instance_id,
        account_id=account_id,
        symbol=symbol,
        side=side,
        order_type="limit",
        price=price,
        quantity=quantity,
        filled_quantity=fill_sz or 0,
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


def _make_error_event(db, strategy_instance_id=1, message="order_place_failed: 参数错误",
                      event_type="error", created_at=None):
    """创建测试错误事件。"""
    ev = StrategyEvent(
        strategy_instance_id=strategy_instance_id,
        event_type=event_type,
        message=message,
        details="{}",
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(ev)
    db.commit()
    return ev


# =============================================================================
# 检查 1：理论挂单 vs 实际挂单
# =============================================================================
class TestCheckTheoreticalVsActualOrders:
    async def test_no_running_instances_passes(self, clean_db, isolated_check_files):
        """无运行中策略时通过。"""
        import function_checker
        result = await function_checker.check_theoretical_vs_actual_orders(clean_db)
        assert result["passed"] is True
        assert result["per_strategy"] == []

    async def test_param_error_handled(self, clean_db, isolated_check_files):
        """参数缺失时记录错误，不算作 matched=False 的失败（记录 error）。

        参数非法时 per_strategy 含 error 字段，matched=False。
        """
        _make_account(clean_db)
        _make_template(clean_db)
        # 缺 upper_price
        _make_instance(clean_db, instance_id=1, params={"lower_price": 100, "grid_count": 5})
        import function_checker
        result = await function_checker.check_theoretical_vs_actual_orders(clean_db)
        assert result["passed"] is False
        assert "error" in result["per_strategy"][0]
        assert result["per_strategy"][0]["matched"] is False

    async def test_orders_matched_passes(self, clean_db, isolated_check_files):
        """理论档位与实际 live 订单一致（在容差内），通过。

        网格：upper=200, lower=100, grid_count=11, step=10
        levels = [100, 110, 120, ..., 200]
        current_price = 150
        theoretical_buy = [100, 110, 120, 130, 140]  (< 150)
        theoretical_sell = [160, 170, 180, 190, 200]  (> 150)
        实际 live 订单：在每个理论档位上挂一单
        """
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT-SWAP",
                       params={"upper_price": 200.0, "lower_price": 100.0,
                               "grid_count": 11, "order_qty": 1, "symbol": "ETH-USDT-SWAP"})
        # 在每个理论档位挂 live 订单
        for i, px in enumerate([100, 110, 120, 130, 140]):
            _make_order(clean_db, f"buy_{i}", strategy_instance_id=1, side="buy",
                        status="live", price=float(px))
        for i, px in enumerate([160, 170, 180, 190, 200]):
            _make_order(clean_db, f"sell_{i}", strategy_instance_id=1, side="sell",
                        status="live", price=float(px))

        # mock OKXClient（get_ticker 返回 current_price=150）
        mock_client = MagicMock()
        mock_client.get_ticker = AsyncMock(return_value=[{"last": "150"}])

        import function_checker
        with patch("function_checker.OKXClient", return_value=mock_client):
            # patch market_data_service 返回 None 强制走 OKX 路径
            with patch("services.market_data_service.market_data_service.get_latest_ticker",
                       return_value=None):
                result = await function_checker.check_theoretical_vs_actual_orders(clean_db)

        assert result["passed"] is True
        per = result["per_strategy"][0]
        assert per["matched"] is True
        assert per["actual_live_orders"] == 10
        # 150 档位无订单，但 ratio=1/11 < 0.2 → 仍通过
        assert per["missing_levels"] == [150.0]
        assert per["price_mismatches"] == []
        # 验证 grid_levels（SWAP tick=0.1，取整后不变）
        assert 100.0 in per["grid_levels"]
        assert 200.0 in per["grid_levels"]

    async def test_missing_orders_detected(self, clean_db, isolated_check_files):
        """理论档位缺失 → missing_levels（ratio > 20% 不通过）。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, params={
            "upper_price": 200.0, "lower_price": 100.0,
            "grid_count": 11, "order_qty": 1, "symbol": "ETH-USDT-SWAP"})
        # 只挂 2 个买单（理论 5 个）+ 2 个卖单（理论 5 个）→ 各缺 3 个
        _make_order(clean_db, "buy_1", strategy_instance_id=1, side="buy",
                    status="live", price=100.0)
        _make_order(clean_db, "buy_2", strategy_instance_id=1, side="buy",
                    status="live", price=110.0)
        _make_order(clean_db, "sell_1", strategy_instance_id=1, side="sell",
                    status="live", price=160.0)
        _make_order(clean_db, "sell_2", strategy_instance_id=1, side="sell",
                    status="live", price=170.0)

        mock_client = MagicMock()
        mock_client.get_ticker = AsyncMock(return_value=[{"last": "150"}])

        import function_checker
        with patch("function_checker.OKXClient", return_value=mock_client):
            with patch("services.market_data_service.market_data_service.get_latest_ticker",
                       return_value=None):
                result = await function_checker.check_theoretical_vs_actual_orders(clean_db)

        assert result["passed"] is False
        per = result["per_strategy"][0]
        assert per["matched"] is False
        # 11 档位 - 4 实际 = 7 缺失（missing_ratio > 0.2 → 不通过）
        assert len(per["missing_levels"]) == 7
        assert per["missing_ratio"] > 0.2
        # 4 个实际订单都在档位上 → 无价格不匹配
        assert per["price_mismatches"] == []

    async def test_extra_orders_detected(self, clean_db, isolated_check_files):
        """实际有但不在 grid_level 上的订单 → price_mismatches。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, params={
            "upper_price": 200.0, "lower_price": 100.0,
            "grid_count": 11, "order_qty": 1, "symbol": "ETH-USDT-SWAP"})
        # 在理论档位上挂单
        for px in [100, 110, 120, 130, 140]:
            _make_order(clean_db, f"buy_{px}", strategy_instance_id=1, side="buy",
                        status="live", price=float(px))
        for px in [160, 170, 180, 190, 200]:
            _make_order(clean_db, f"sell_{px}", strategy_instance_id=1, side="sell",
                        status="live", price=float(px))
        # 多挂一个不在理论档位的买单（155 不在 levels 中，且 diff > tick_size=0.1）
        _make_order(clean_db, "extra_buy", strategy_instance_id=1, side="buy",
                    status="live", price=155.0)

        mock_client = MagicMock()
        mock_client.get_ticker = AsyncMock(return_value=[{"last": "150"}])

        import function_checker
        with patch("function_checker.OKXClient", return_value=mock_client):
            with patch("services.market_data_service.market_data_service.get_latest_ticker",
                       return_value=None):
                result = await function_checker.check_theoretical_vs_actual_orders(clean_db)

        assert result["passed"] is False
        per = result["per_strategy"][0]
        # 155 不在任何 grid_level ±0.1 内 → price_mismatch
        assert len(per["price_mismatches"]) == 1
        assert per["price_mismatches"][0]["actual"] == 155.0
        assert per["price_mismatches"][0]["nearest_level"] == 150.0
        # 150 档位无订单（155 不匹配 150）→ missing
        assert 150.0 in per["missing_levels"]

    async def test_price_tolerance_within_tick(self, clean_db, isolated_check_files):
        """订单价格在 ±tick_size 容差内视为匹配。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, params={
            "upper_price": 200.0, "lower_price": 100.0,
            "grid_count": 11, "order_qty": 1, "symbol": "ETH-USDT-SWAP"})
        # 理论档位 100，实际挂 100.05（SWAP tick=0.1，容差 ±0.1 → 匹配）
        _make_order(clean_db, "buy_1", strategy_instance_id=1, side="buy",
                    status="live", price=100.05)
        _make_order(clean_db, "sell_1", strategy_instance_id=1, side="sell",
                    status="live", price=160.0)

        mock_client = MagicMock()
        mock_client.get_ticker = AsyncMock(return_value=[{"last": "150"}])

        import function_checker
        with patch("function_checker.OKXClient", return_value=mock_client):
            with patch("services.market_data_service.market_data_service.get_latest_ticker",
                       return_value=None):
                result = await function_checker.check_theoretical_vs_actual_orders(clean_db)

        per = result["per_strategy"][0]
        # 100.05 在 100 ±0.1 内 → 匹配，不算 price_mismatch
        # 但档位大量缺失（11 档位仅 2 个订单）→ matched=False
        assert per["matched"] is False
        # 100.05 不应出现在 price_mismatches 中
        mismatch_prices = [pm["actual"] for pm in per["price_mismatches"]]
        assert 100.05 not in mismatch_prices

    async def test_spot_tick_size_used(self, clean_db, isolated_check_files):
        """现货使用 tick_size=0.01。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT",
                       params={"upper_price": 200.0, "lower_price": 100.0,
                               "grid_count": 11, "order_qty": 1, "symbol": "ETH-USDT"})
        # 现货 tick=0.01，价格 100.005 在 ±0.01 内匹配
        _make_order(clean_db, "buy_1", strategy_instance_id=1, side="buy",
                    status="live", price=100.005, symbol="ETH-USDT")

        mock_client = MagicMock()
        mock_client.get_ticker = AsyncMock(return_value=[{"last": "150"}])

        import function_checker
        with patch("function_checker.OKXClient", return_value=mock_client):
            with patch("services.market_data_service.market_data_service.get_latest_ticker",
                       return_value=None):
                result = await function_checker.check_theoretical_vs_actual_orders(clean_db)

        per = result["per_strategy"][0]
        # 100.005 在 100 ±0.01 内 → 不算 price_mismatch
        mismatch_prices = [pm["actual"] for pm in per["price_mismatches"]]
        assert 100.005 not in mismatch_prices


# =============================================================================
# 检查 2：策略检测问题排查
# =============================================================================
class TestCheckStrategyErrors:
    def test_no_errors_passes(self, clean_db, isolated_check_files):
        """无 error 事件时通过。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)

        import function_checker
        result = function_checker.check_strategy_errors(clean_db)
        assert result["passed"] is True
        assert result["error_count"] == 0
        assert result["errors_by_type"] == []
        assert result["recent_errors"] == []

    def test_errors_detected_with_suggestion(self, clean_db, isolated_check_files):
        """检测到 error 事件并给出修复建议。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        _make_error_event(clean_db, strategy_instance_id=1,
                          message="order_place_failed: 参数错误 sz=0")
        _make_error_event(clean_db, strategy_instance_id=1,
                          message="order_place_failed: 资金不足")

        import function_checker
        result = function_checker.check_strategy_errors(clean_db)
        assert result["passed"] is False
        assert result["error_count"] == 2
        assert len(result["errors_by_type"]) >= 1
        # 错误类型含 order_place_failed
        types = [t["type"] for t in result["errors_by_type"]]
        assert any("order_place_failed" in t for t in types)
        # 修复建议不为空
        assert result["errors_by_type"][0]["suggestion"]
        assert len(result["recent_errors"]) == 2

    def test_error_type_classification(self, clean_db, isolated_check_files):
        """不同错误类型分类统计。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        # 三种不同错误类型
        _make_error_event(clean_db, strategy_instance_id=1,
                          message="refresh_price timeout: 轮询超时")
        _make_error_event(clean_db, strategy_instance_id=1,
                          message="position_mismatch: 虚拟仓位 5.0 真实仓位 3.0")
        _make_error_event(clean_db, strategy_instance_id=1,
                          message="capital_limit_exceeded: 超出投资上限")
        _make_error_event(clean_db, strategy_instance_id=1,
                          message="网络异常 (第1次)，退避 2s")

        import function_checker
        result = function_checker.check_strategy_errors(clean_db)
        assert result["passed"] is False
        assert result["error_count"] == 4
        # 至少 4 种类型（按消息前缀分类）
        assert len(result["errors_by_type"]) >= 3
        # 验证修复建议关键字
        suggestions = " ".join(t["suggestion"] for t in result["errors_by_type"])
        assert "限流" in suggestions or "轮询频率" in suggestions  # refresh_price timeout
        assert "仓位" in suggestions  # position_mismatch
        assert "资金" in suggestions  # capital_limit_exceeded

    def test_old_errors_excluded(self, clean_db, isolated_check_files):
        """超过 1 小时的 error 事件不计入。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        # 2 小时前的事件
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        _make_error_event(clean_db, strategy_instance_id=1,
                          message="order_place_failed: 旧错误",
                          created_at=old_time)

        import function_checker
        result = function_checker.check_strategy_errors(clean_db)
        # 旧事件不计入 → passed=True
        assert result["passed"] is True
        assert result["error_count"] == 0


# =============================================================================
# 检查 3：实际盈亏核验
# =============================================================================
class TestCheckActualPnl:
    async def test_no_running_instances_passes(self, clean_db, isolated_check_files):
        """无运行中策略时通过。"""
        import function_checker
        result = await function_checker.check_actual_pnl(clean_db)
        assert result["passed"] is True
        assert result["per_strategy"] == []
        assert result["total_okx_pnl"] == 0.0

    async def test_spot_fifo_matched_passes(self, clean_db, isolated_check_files):
        """SPOT FIFO 配对盈亏匹配，通过。

        buy@100 qty=1 + sell@105 qty=1, fee=0.1 each
        FIFO: realized = (105-100)*1 - 1*(0.1+0.1) = 5 - 0.2 = 4.8
        """
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT")
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy",
                    symbol="ETH-USDT", status="filled",
                    fill_px=100.0, fill_sz=1.0, fee=0.1)
        _make_order(clean_db, "order_2", strategy_instance_id=1, side="sell",
                    symbol="ETH-USDT", status="filled",
                    fill_px=105.0, fill_sz=1.0, fee=0.1)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=4.8)

        fills = [
            {"ordId": "order_1", "side": "buy", "fillPx": "100", "fillSz": "1",
             "fee": "0.1", "ts": "1"},
            {"ordId": "order_2", "side": "sell", "fillPx": "105", "fillSz": "1",
             "fee": "0.1", "ts": "2"},
        ]
        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(return_value=fills)
        mock_client.trade.get_fills_history = AsyncMock(return_value=[])

        import function_checker
        with patch("function_checker.OKXClient", return_value=mock_client):
            result = await function_checker.check_actual_pnl(clean_db)

        assert result["passed"] is True
        per = result["per_strategy"][0]
        assert per["okx_realized_pnl"] == pytest.approx(4.8, abs=0.01)
        assert per["db_realized_pnl"] == 4.8
        assert per["matched"] is True
        assert per["trade_count"] == 1  # 1 个匹配对

    async def test_swap_fifo_matched_passes(self, clean_db, isolated_check_files):
        """SWAP FIFO 配对盈亏匹配（ctVal=0.01 转换）。

        buy@100 fillSz=10 (ctVal=0.01, qty_base=0.1), fee=0.1
        sell@105 fillSz=10 (qty_base=0.1), fee=0.1
        FIFO: realized = (105-100)*0.1 - 0.1*(1.0+1.0) = 0.5 - 0.2 = 0.3
        """
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT-SWAP")
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy",
                    symbol="ETH-USDT-SWAP", status="filled",
                    fill_px=100.0, fill_sz=10.0, fee=0.1)
        _make_order(clean_db, "order_2", strategy_instance_id=1, side="sell",
                    symbol="ETH-USDT-SWAP", status="filled",
                    fill_px=105.0, fill_sz=10.0, fee=0.1)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=0.3)

        fills = [
            {"ordId": "order_1", "side": "buy", "fillPx": "100", "fillSz": "10",
             "fee": "0.1", "ts": "1"},
            {"ordId": "order_2", "side": "sell", "fillPx": "105", "fillSz": "10",
             "fee": "0.1", "ts": "2"},
        ]
        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(return_value=fills)
        mock_client.trade.get_fills_history = AsyncMock(return_value=[])

        import function_checker
        # mock instrument_cache.get_ct_val 返回 0.01（SWAP）
        with patch("function_checker.OKXClient", return_value=mock_client):
            with patch.object(function_checker.instrument_cache, "get_ct_val",
                              return_value=0.01):
                result = await function_checker.check_actual_pnl(clean_db)

        assert result["passed"] is True
        per = result["per_strategy"][0]
        assert per["okx_realized_pnl"] == pytest.approx(0.3, abs=0.01)
        assert per["db_realized_pnl"] == 0.3
        assert per["matched"] is True

    async def test_pnl_mismatch_detected(self, clean_db, isolated_check_files):
        """OKX 独立盈亏与 DB PnlRecord 差异超阈值，检测到不一致。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT")
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy",
                    symbol="ETH-USDT", status="filled",
                    fill_px=100.0, fill_sz=1.0, fee=0.1)
        _make_order(clean_db, "order_2", strategy_instance_id=1, side="sell",
                    symbol="ETH-USDT", status="filled",
                    fill_px=105.0, fill_sz=1.0, fee=0.1)
        # OKX 算出 4.8，DB 记 10.0 → diff=5.2 > 0.5
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=10.0)

        fills = [
            {"ordId": "order_1", "side": "buy", "fillPx": "100", "fillSz": "1",
             "fee": "0.1", "ts": "1"},
            {"ordId": "order_2", "side": "sell", "fillPx": "105", "fillSz": "1",
             "fee": "0.1", "ts": "2"},
        ]
        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(return_value=fills)
        mock_client.trade.get_fills_history = AsyncMock(return_value=[])

        import function_checker
        with patch("function_checker.OKXClient", return_value=mock_client):
            result = await function_checker.check_actual_pnl(clean_db)

        assert result["passed"] is False
        per = result["per_strategy"][0]
        assert per["okx_realized_pnl"] == pytest.approx(4.8, abs=0.01)
        assert per["db_realized_pnl"] == 10.0
        assert per["diff"] > 0.5
        assert per["matched"] is False
        # 验证写入了告警事件
        events = clean_db.query(StrategyEvent).filter(
            StrategyEvent.event_type == "function_check_pnl_mismatch"
        ).all()
        assert len(events) == 1

    async def test_api_error_handled(self, clean_db, isolated_check_files):
        """OKX API 调用失败时不中断检查，记录 function_check_okx_api_error 事件。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT")
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy",
                    symbol="ETH-USDT", status="filled",
                    fill_px=100.0, fill_sz=1.0, fee=0.1)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=0.0)

        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(side_effect=Exception("API timeout"))
        mock_client.trade.get_fills_history = AsyncMock(return_value=[])

        import function_checker
        with patch("function_checker.OKXClient", return_value=mock_client):
            result = await function_checker.check_actual_pnl(clean_db)

        # API 失败不中断，okx_realized_pnl=0, db_realized_pnl=0, diff=0 → matched
        assert len(result["per_strategy"]) == 1
        per = result["per_strategy"][0]
        assert per["okx_realized_pnl"] == 0.0
        assert per["trade_count"] == 0
        # 记录了 function_check_okx_api_error 事件
        events = clean_db.query(StrategyEvent).filter(
            StrategyEvent.event_type == "function_check_okx_api_error"
        ).all()
        assert len(events) == 1

    async def test_fifo_partial_fill(self, clean_db, isolated_check_files):
        """FIFO 部分成交配对：sell 部分匹配 buy1，部分匹配 buy2。

        buy1@100 qty=2, fee=0.2
        buy2@102 qty=1, fee=0.1
        sell@105 qty=1.5, fee=0.15
        FIFO: sell 先匹配 buy1 的 1.5（buy1 还剩 0.5）
        realized = (105-100)*1.5 - 1.5*(0.2/2 + 0.15/1.5)
                 = 7.5 - 1.5*(0.1 + 0.1) = 7.5 - 0.3 = 7.2
        """
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT")
        _make_order(clean_db, "buy_1", strategy_instance_id=1, side="buy",
                    symbol="ETH-USDT", status="filled",
                    fill_px=100.0, fill_sz=2.0, fee=0.2)
        _make_order(clean_db, "buy_2", strategy_instance_id=1, side="buy",
                    symbol="ETH-USDT", status="filled",
                    fill_px=102.0, fill_sz=1.0, fee=0.1)
        _make_order(clean_db, "sell_1", strategy_instance_id=1, side="sell",
                    symbol="ETH-USDT", status="filled",
                    fill_px=105.0, fill_sz=1.5, fee=0.15)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=7.2)

        fills = [
            {"ordId": "buy_1", "side": "buy", "fillPx": "100", "fillSz": "2",
             "fee": "0.2", "ts": "1"},
            {"ordId": "buy_2", "side": "buy", "fillPx": "102", "fillSz": "1",
             "fee": "0.1", "ts": "2"},
            {"ordId": "sell_1", "side": "sell", "fillPx": "105", "fillSz": "1.5",
             "fee": "0.15", "ts": "3"},
        ]
        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(return_value=fills)
        mock_client.trade.get_fills_history = AsyncMock(return_value=[])

        import function_checker
        with patch("function_checker.OKXClient", return_value=mock_client):
            result = await function_checker.check_actual_pnl(clean_db)

        per = result["per_strategy"][0]
        assert per["okx_realized_pnl"] == pytest.approx(7.2, abs=0.01)
        assert per["db_realized_pnl"] == 7.2
        assert per["matched"] is True
        assert per["trade_count"] == 1  # 1 个匹配对（部分成交）

    async def test_no_sells_zero_realized(self, clean_db, isolated_check_files):
        """只有买单无卖单 → realized=0（未平仓）。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT")
        _make_order(clean_db, "buy_1", strategy_instance_id=1, side="buy",
                    symbol="ETH-USDT", status="filled",
                    fill_px=100.0, fill_sz=1.0, fee=0.1)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=0.0)

        fills = [
            {"ordId": "buy_1", "side": "buy", "fillPx": "100", "fillSz": "1",
             "fee": "0.1", "ts": "1"},
        ]
        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(return_value=fills)
        mock_client.trade.get_fills_history = AsyncMock(return_value=[])

        import function_checker
        with patch("function_checker.OKXClient", return_value=mock_client):
            result = await function_checker.check_actual_pnl(clean_db)

        per = result["per_strategy"][0]
        assert per["okx_realized_pnl"] == 0.0
        assert per["trade_count"] == 0
        assert per["matched"] is True

    async def test_total_pnl_aggregation(self, clean_db, isolated_check_files):
        """多个策略总盈亏聚合正确。"""
        _make_account(clean_db)
        _make_template(clean_db)
        # 策略 1: ETH-USDT, realized=4.8
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT")
        _make_order(clean_db, "b1", strategy_instance_id=1, side="buy",
                    symbol="ETH-USDT", status="filled",
                    fill_px=100.0, fill_sz=1.0, fee=0.1)
        _make_order(clean_db, "s1", strategy_instance_id=1, side="sell",
                    symbol="ETH-USDT", status="filled",
                    fill_px=105.0, fill_sz=1.0, fee=0.1)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=4.8)
        # 策略 2: BTC-USDT, realized=0.0（无卖单）
        _make_instance(clean_db, instance_id=2, symbol="BTC-USDT")
        _make_order(clean_db, "b2", strategy_instance_id=2, side="buy",
                    symbol="BTC-USDT", status="filled",
                    fill_px=50000.0, fill_sz=0.01, fee=0.1)
        _make_pnl_record(clean_db, strategy_instance_id=2, realized_pnl=0.0)

        # 按 symbol 分开返回 fills
        async def mock_get_fills(instId=None, limit=None, after=None):
            if instId == "ETH-USDT":
                return [
                    {"ordId": "b1", "side": "buy", "fillPx": "100", "fillSz": "1",
                     "fee": "0.1", "ts": "1"},
                    {"ordId": "s1", "side": "sell", "fillPx": "105", "fillSz": "1",
                     "fee": "0.1", "ts": "2"},
                ]
            elif instId == "BTC-USDT":
                return [
                    {"ordId": "b2", "side": "buy", "fillPx": "50000", "fillSz": "0.01",
                     "fee": "0.1", "ts": "1"},
                ]
            return []

        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(side_effect=mock_get_fills)
        mock_client.trade.get_fills_history = AsyncMock(return_value=[])

        import function_checker
        with patch("function_checker.OKXClient", return_value=mock_client):
            result = await function_checker.check_actual_pnl(clean_db)

        # 总盈亏 = 4.8 + 0 = 4.8
        assert result["total_okx_pnl"] == pytest.approx(4.8, abs=0.01)
        assert result["total_db_pnl"] == 4.8
        assert result["total_diff"] < 0.5
        assert result["passed"] is True

    async def test_okx_drift_detected(self, clean_db, isolated_check_files):
        """OKX vs DB FIFO 差异超 OKX_DRIFT_TOLERANCE 时检测到不同步。

        DB orders 全部成交（buy@100 + sell@105 → db_fifo=4.8），PnlRecord=4.8（accounting 一致）。
        OKX fills 价格偏离（buy@100 + sell@120 → okx_fifo=19.8），drift=15.0 > 5.0 → 不通过。
        验证：accounting_match=True 但 okx_drift_match=False → matched=False。
        """
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT")
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy",
                    symbol="ETH-USDT", status="filled",
                    fill_px=100.0, fill_sz=1.0, fee=0.1)
        _make_order(clean_db, "order_2", strategy_instance_id=1, side="sell",
                    symbol="ETH-USDT", status="filled",
                    fill_px=105.0, fill_sz=1.0, fee=0.1)
        # PnlRecord 与 DB FIFO 一致 → accounting_match=True
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=4.8)

        # OKX fills 卖单价格偏离（120 vs DB 的 105）
        fills = [
            {"ordId": "order_1", "side": "buy", "fillPx": "100", "fillSz": "1",
             "fee": "0.1", "ts": "1"},
            {"ordId": "order_2", "side": "sell", "fillPx": "120", "fillSz": "1",
             "fee": "0.1", "ts": "2"},
        ]
        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(return_value=fills)
        mock_client.trade.get_fills_history = AsyncMock(return_value=[])

        import function_checker
        with patch("function_checker.OKXClient", return_value=mock_client):
            result = await function_checker.check_actual_pnl(clean_db)

        assert result["passed"] is False
        per = result["per_strategy"][0]
        # accounting 一致（DB FIFO == PnlRecord）
        assert per["accounting_diff"] < 0.5
        # OKX drift 超阈值
        assert per["okx_vs_db_fifo_diff"] > 5.0
        assert per["okx_drift_match"] is False
        assert per["matched"] is False
        # diff 反映最严重差异（OKX drift，而非 accounting_diff）
        assert per["diff"] > 5.0
        # total_diff 反映 OKX vs DB 真实差距
        assert result["total_diff"] > 5.0

    async def test_low_coverage_detected(self, clean_db, isolated_check_files):
        """OKX fills 覆盖率低于阈值时检测到数据缺失。

        DB 有 4 个已成交订单，OKX 只返回 2 个 → coverage=0.5 < 0.95 → 不通过。
        """
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT")
        # DB 4 个已成交订单（2 buy + 2 sell）
        for i, px in enumerate([100, 102]):
            _make_order(clean_db, f"buy_{i}", strategy_instance_id=1, side="buy",
                        symbol="ETH-USDT", status="filled",
                        fill_px=float(px), fill_sz=1.0, fee=0.1)
        for i, px in enumerate([105, 108]):
            _make_order(clean_db, f"sell_{i}", strategy_instance_id=1, side="sell",
                        symbol="ETH-USDT", status="filled",
                        fill_px=float(px), fill_sz=1.0, fee=0.1)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=9.6)

        # OKX 只返回 2 个 fills（buy_0 + sell_0），另外 2 个 DB 订单在 OKX 找不到
        fills = [
            {"ordId": "buy_0", "side": "buy", "fillPx": "100", "fillSz": "1",
             "fee": "0.1", "ts": "1"},
            {"ordId": "sell_0", "side": "sell", "fillPx": "105", "fillSz": "1",
             "fee": "0.1", "ts": "2"},
        ]
        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(return_value=fills)
        mock_client.trade.get_fills_history = AsyncMock(return_value=[])

        import function_checker
        with patch("function_checker.OKXClient", return_value=mock_client):
            result = await function_checker.check_actual_pnl(clean_db)

        assert result["passed"] is False
        per = result["per_strategy"][0]
        assert per["fills_coverage"] < 0.95
        assert per["coverage_match"] is False
        assert per["matched"] is False
        assert per["db_filled_count"] == 4
        assert per["okx_fills_count"] == 2

    async def test_okx_fetch_failure_skips_external_checks(self, clean_db, isolated_check_files):
        """OKX 拉取失败时跳过外部核验（drift + coverage），不导致 matched=False。

        API 失败已记录 function_check_okx_api_error 事件，不重复告警。
        """
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1, symbol="ETH-USDT")
        _make_order(clean_db, "order_1", strategy_instance_id=1, side="buy",
                    symbol="ETH-USDT", status="filled",
                    fill_px=100.0, fill_sz=1.0, fee=0.1)
        _make_pnl_record(clean_db, strategy_instance_id=1, realized_pnl=0.0)

        mock_client = MagicMock()
        mock_client.trade.get_fills = AsyncMock(side_effect=Exception("API timeout"))
        mock_client.trade.get_fills_history = AsyncMock(return_value=[])

        import function_checker
        with patch("function_checker.OKXClient", return_value=mock_client):
            result = await function_checker.check_actual_pnl(clean_db)

        per = result["per_strategy"][0]
        # OKX 拉取失败 → 跳过外部核验
        assert per["okx_fetch_succeeded"] is False
        assert per["okx_drift_match"] is True  # 跳过 → 默认通过
        assert per["coverage_match"] is True    # 跳过 → 默认通过
        # accounting 仍检查（DB FIFO vs PnlRecord，都是 DB 数据）
        assert per["matched"] is True
        # 记录了 API 错误事件
        events = clean_db.query(StrategyEvent).filter(
            StrategyEvent.event_type == "function_check_okx_api_error"
        ).all()
        assert len(events) == 1


# =============================================================================
# FIFO 计算单元测试
# =============================================================================
class TestFifoCalculation:
    def test_empty_fills(self):
        """空 fills 列表 → realized=0。"""
        from function_checker import _compute_fifo_realized_pnl
        realized, count = _compute_fifo_realized_pnl([], "SPOT", 1.0)
        assert realized == 0.0
        assert count == 0

    def test_only_buys(self):
        """只有买单 → realized=0（未平仓）。"""
        from function_checker import _compute_fifo_realized_pnl
        fills = [
            {"side": "buy", "fillPx": "100", "fillSz": "1", "fee": "0.1", "ts": "1"},
            {"side": "buy", "fillPx": "110", "fillSz": "2", "fee": "0.2", "ts": "2"},
        ]
        realized, count = _compute_fifo_realized_pnl(fills, "SPOT", 1.0)
        assert realized == 0.0
        assert count == 0

    def test_simple_match(self):
        """简单 1:1 配对。"""
        from function_checker import _compute_fifo_realized_pnl
        fills = [
            {"side": "buy", "fillPx": "100", "fillSz": "1", "fee": "0.1", "ts": "1"},
            {"side": "sell", "fillPx": "110", "fillSz": "1", "fee": "0.1", "ts": "2"},
        ]
        realized, count = _compute_fifo_realized_pnl(fills, "SPOT", 1.0)
        # (110-100)*1 - 1*(0.1+0.1) = 10 - 0.2 = 9.8
        assert realized == pytest.approx(9.8, abs=0.001)
        assert count == 1

    def test_out_of_order_ts(self):
        """fills 未按 ts 排序 → 内部按 ts 排序后配对。"""
        from function_checker import _compute_fifo_realized_pnl
        fills = [
            {"side": "sell", "fillPx": "110", "fillSz": "1", "fee": "0.1", "ts": "2"},
            {"side": "buy", "fillPx": "100", "fillSz": "1", "fee": "0.1", "ts": "1"},
        ]
        realized, count = _compute_fifo_realized_pnl(fills, "SPOT", 1.0)
        assert realized == pytest.approx(9.8, abs=0.001)
        assert count == 1

    def test_sell_exceeds_buy(self):
        """卖单数量超过买单 → 只匹配买单部分。"""
        from function_checker import _compute_fifo_realized_pnl
        fills = [
            {"side": "buy", "fillPx": "100", "fillSz": "1", "fee": "0.1", "ts": "1"},
            {"side": "sell", "fillPx": "110", "fillSz": "3", "fee": "0.3", "ts": "2"},
        ]
        realized, count = _compute_fifo_realized_pnl(fills, "SPOT", 1.0)
        # 只匹配 1 单位：(110-100)*1 - 1*(0.1 + 0.3/3) = 10 - 0.2 = 9.8
        assert realized == pytest.approx(9.8, abs=0.001)
        assert count == 1


# =============================================================================
# 主流程 run_function_check
# =============================================================================
class TestRunFunctionCheck:
    async def test_run_function_check_writes_report(self, clean_db, isolated_check_files):
        """run_function_check 生成报告文件 + latest 文件。"""
        import function_checker

        with patch.object(function_checker, "SessionLocal", return_value=clean_db):
            report = await function_checker.run_function_check()

        assert "check_type" in report
        assert report["check_type"] == "scheduled_function_check"
        assert "checks" in report
        assert "theoretical_vs_actual_orders" in report["checks"]
        assert "strategy_errors" in report["checks"]
        assert "actual_pnl" in report["checks"]
        assert "overall_passed" in report
        assert "duration_seconds" in report

        # 报告文件已写入
        files = list(isolated_check_files.glob("function_check_report_*.json"))
        assert len(files) == 1
        # latest 文件已写入
        assert (isolated_check_files / "function_check_latest.json").exists()

    async def test_run_function_check_empty_db_passes(self, clean_db, isolated_check_files):
        """空数据库时全部检查通过。"""
        import function_checker

        with patch.object(function_checker, "SessionLocal", return_value=clean_db):
            report = await function_checker.run_function_check()

        assert report["overall_passed"] is True
        # 三项检查都通过
        for check_name, check_result in report["checks"].items():
            assert check_result["passed"] is True, f"{check_name} 未通过"

    async def test_run_function_check_with_failures(self, clean_db, isolated_check_files):
        """有 error 事件时 strategy_errors 检查失败，overall_passed=False。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)
        _make_error_event(clean_db, strategy_instance_id=1,
                          message="order_place_failed: 参数错误")

        import function_checker
        with patch.object(function_checker, "SessionLocal", return_value=clean_db):
            report = await function_checker.run_function_check()

        assert report["overall_passed"] is False
        assert report["checks"]["strategy_errors"]["passed"] is False

    def test_main_entry_point(self, isolated_check_files):
        """main() 同步入口可正常执行（验证无异常）。

        本测试为同步函数（非 async），确保 main() 内部的 asyncio.run()
        不受 pytest-asyncio 事件循环影响。
        """
        import function_checker

        # 独立内存 DB（避免与模块级 fixture 冲突）
        _TEST_ENGINE_TMP = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=_TEST_ENGINE_TMP)
        _tmp_session = sessionmaker(autocommit=False, autoflush=False, bind=_TEST_ENGINE_TMP)()

        try:
            with patch.object(function_checker, "SessionLocal", return_value=_tmp_session):
                # main 内部调用 asyncio.run，同步上下文中无运行事件循环，可正常执行
                function_checker.main()
        finally:
            _tmp_session.close()
            Base.metadata.drop_all(bind=_TEST_ENGINE_TMP)


# =============================================================================
# 事件记录
# =============================================================================
class TestRecordCheckEvent:
    def test_record_event_with_strategy_id(self, clean_db, isolated_check_files):
        """有 strategy_instance_id 时写入 StrategyEvent 表。"""
        _make_account(clean_db)
        _make_template(clean_db)
        _make_instance(clean_db, instance_id=1)

        import function_checker
        function_checker._record_check_event(
            clean_db,
            strategy_instance_id=1,
            event_type="function_check_test_event",
            message="测试事件",
            details={"key": "value"},
        )

        events = clean_db.query(StrategyEvent).filter(
            StrategyEvent.event_type == "function_check_test_event"
        ).all()
        assert len(events) == 1
        assert events[0].strategy_instance_id == 1
        assert events[0].message == "测试事件"

    def test_record_event_none_strategy_id_skips_db(self, clean_db, isolated_check_files):
        """strategy_instance_id=None 时不写表，只写日志。"""
        import function_checker
        function_checker._record_check_event(
            clean_db,
            strategy_instance_id=None,
            event_type="function_check_global_event",
            message="全局告警",
            details={"key": "value"},
        )

        # 表中无该事件
        events = clean_db.query(StrategyEvent).filter(
            StrategyEvent.event_type == "function_check_global_event"
        ).all()
        assert len(events) == 0

    def test_record_event_handles_db_error(self, clean_db, isolated_check_files):
        """DB 写入失败时不抛异常（只记录日志）。"""
        import function_checker

        # 用一个无效的 session 触发异常
        bad_db = MagicMock()
        bad_db.add.side_effect = Exception("DB error")
        bad_db.rollback = MagicMock()

        # 不应抛异常
        function_checker._record_check_event(
            bad_db,
            strategy_instance_id=1,
            event_type="function_check_test",
            message="测试",
        )
        bad_db.rollback.assert_called_once()
