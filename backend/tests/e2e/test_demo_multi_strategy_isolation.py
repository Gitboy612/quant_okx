"""多策略同品种 PnL 隔离 E2E 验证（Task 6）。

验证多个策略实例跑同一 ETH-USDT-SWAP 合约时，各自盈亏正确隔离：
- 离线部分（默认运行）：用 Mock 订单数据写入内存 DB，验证 PnL 引擎按
  strategy_instance_id 独立核算、虚拟持仓独立、对账通过、停止连续性、冲突检测
- 真实 API 部分（@pytest.mark.demo，可跳过）：启动两策略实例各自下单验证隔离

设计要点：
1. 离线测试不依赖 demo 账户，使用独立的内存 SQLite DB（sqlite:///:memory:），
   避免受存量 DB schema 漂移影响（create_all 在内存库中直接建出完整最新表结构）
2. 通过 mock_okx（autouse）patch OKX API，所有 client 调用走 Mock
3. patch services.pnl_accounting_engine.SessionLocal 指向内存 DB 的 session 工厂，
   使 recompute / reconcile_positions 与测试数据共享同一内存库
4. 离线测试用 async（pytest-asyncio auto 模式），直接 await PnL 引擎异步方法
5. 每个测试通过 isolation_env fixture 构造独立环境（内存库随 fixture 销毁自动清理）
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.account import Account
from models.order import Order
from models.pnl import PnlRecord
from models.strategy import StrategyInstance, StrategyTemplate
from models.strategy_event import StrategyEvent
from services.pnl_accounting_engine import pnl_accounting_engine
from strategies.grid_strategy import GridStrategy

# 公共交易品种：两策略均跑该合约
SYMBOL = "ETH-USDT-SWAP"
MARKET = "swap"

# 网格策略参数（ETH 合约，价格区间 2500-3500）
GRID_PARAMS = {
    "upper_price": 3500,
    "lower_price": 2500,
    "grid_count": 10,
    "order_qty": 1.0,
    "symbol": SYMBOL,
    "investment_amount": 0,
    "lever": 1,
    "td_mode": "cross",
    "fee_rate": 0.001,
}

# 趋势策略参数（ETH 合约，双均线交叉）
TREND_PARAMS = {
    "fast_period": 5,
    "slow_period": 20,
    "order_qty": 1.0,
    "symbol": SYMBOL,
    "investment_amount": 0,
    "lever": 1,
    "td_mode": "cross",
    "fee_rate": 0.001,
}


# ============================================================
# 辅助函数
# ============================================================


def _insert_filled_order(db, instance_id, account_id, side, price, qty, fee=0.0):
    """向 DB 写入一笔已成交订单（Mock 数据），返回 Order 对象。"""
    order = Order(
        strategy_instance_id=instance_id,
        account_id=account_id,
        symbol=SYMBOL,
        order_id=f"mock_{uuid.uuid4().hex[:12]}",
        side=side,
        order_type="limit",
        price=price,
        quantity=qty,
        filled_quantity=qty,
        fill_px=price,
        fill_sz=qty,
        actual_qty=qty,
        fee=fee,
        state="filled",
        status="filled",
        pnl_accounted=False,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def _make_grid_strategy(instance_id, account_id, client, db_session_factory):
    """构造 GridStrategy 实例，用于测试 BaseStrategy 的虚拟持仓 / 冲突校验能力。"""
    return GridStrategy(
        instance_id=instance_id,
        params=dict(GRID_PARAMS),
        client=client,
        db_session_factory=db_session_factory,
        account_id=account_id,
        order_manager=MagicMock(),
        ws_client=None,
    )


def _set_instance_status(db_factory, instance_id, status):
    """更新 DB 中策略实例状态。"""
    db = db_factory()
    try:
        inst = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
        if inst:
            inst.status = status
            if status == "stopped":
                inst.stopped_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


# ============================================================
# 测试环境 fixture：内存 DB + 独立账户 + 双策略实例
# ============================================================


@pytest.fixture
def isolation_env(mock_okx):
    """构建多策略同品种隔离测试环境（内存 DB），fixture 销毁时自动清理。

    创建：内存 SQLite DB + 1 个测试账户 + 1 个网格模板/实例 + 1 个趋势模板/实例
    （均跑 ETH-USDT-SWAP）。两个实例初始 status='running'，便于 reconcile / conflict
    检测查询活跃策略。

    patch services.pnl_accounting_engine.SessionLocal 指向内存 DB session 工厂，
    使 PnL 引擎的 recompute / reconcile_positions 与测试数据共享同一内存库。

    Returns:
        dict: account_id / grid_instance_id / trend_instance_id /
              mock_client / db_factory（内存 DB session 工厂）
    """
    # 1. 创建内存 DB engine + session 工厂
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    # 导入所有模型确保 Base.metadata 注册全部表后建表（覆盖 FK 依赖）
    from models.user import User  # noqa: F401
    from models.log import OperationLog  # noqa: F401
    from models.api_call_log import ApiCallLog  # noqa: F401
    from models.setting import UserSetting  # noqa: F401
    from models.system_settings import SystemSetting  # noqa: F401
    from models.notification_rule import NotificationRule  # noqa: F401
    Base.metadata.create_all(bind=test_engine)

    # 2. 禁用真实通知 + patch PnL 引擎 SessionLocal 指向内存 DB
    with patch("services.notification_service.notification_service") as mock_ns, \
         patch("services.pnl_accounting_engine.SessionLocal", TestSession):
        mock_ns.notify = AsyncMock(return_value=0)

        db = TestSession()
        try:
            # 3. 测试账户（demo 模式，加密字段为 mock 值）
            account = Account(
                name=f"E2E_ISOLATION_{uuid.uuid4().hex[:8]}",
                api_key_encrypted="mock_key",
                secret_key_encrypted="mock_secret",
                passphrase_encrypted="mock_pass",
                trade_mode="demo",
                exchange="okx",
                is_active=True,
            )
            db.add(account)
            db.commit()
            db.refresh(account)
            account_id = account.id

            # 4. 网格 + 趋势模板
            grid_tpl = StrategyTemplate(
                name=f"E2E_ISOLATION_GRID_{uuid.uuid4().hex[:8]}",
                strategy_type="grid",
                description="多策略隔离测试-网格模板",
                default_params=GRID_PARAMS,
                param_schema={},
                is_builtin=False,
                is_custom=True,
            )
            trend_tpl = StrategyTemplate(
                name=f"E2E_ISOLATION_TREND_{uuid.uuid4().hex[:8]}",
                strategy_type="trend",
                description="多策略隔离测试-趋势模板",
                default_params=TREND_PARAMS,
                param_schema={},
                is_builtin=False,
                is_custom=True,
            )
            db.add_all([grid_tpl, trend_tpl])
            db.commit()
            db.refresh(grid_tpl)
            db.refresh(trend_tpl)

            # 5. 两个策略实例（同一 ETH-USDT-SWAP，初始 running）
            grid_inst = StrategyInstance(
                template_id=grid_tpl.id,
                account_id=account_id,
                name="E2E_ISOLATION_GRID_INST",
                symbol=SYMBOL,
                market_type=MARKET,
                params=GRID_PARAMS,
                status="running",
            )
            trend_inst = StrategyInstance(
                template_id=trend_tpl.id,
                account_id=account_id,
                name="E2E_ISOLATION_TREND_INST",
                symbol=SYMBOL,
                market_type=MARKET,
                params=TREND_PARAMS,
                status="running",
            )
            db.add_all([grid_inst, trend_inst])
            db.commit()
            db.refresh(grid_inst)
            db.refresh(trend_inst)

            env = {
                "account_id": account_id,
                "grid_template_id": grid_tpl.id,
                "trend_template_id": trend_tpl.id,
                "grid_instance_id": grid_inst.id,
                "trend_instance_id": trend_inst.id,
                "mock_client": mock_okx,
                "db_factory": TestSession,
            }
            yield env
        finally:
            db.close()
            # 内存 DB 随 engine.dispose() 自动销毁，无需手动清理表数据
            test_engine.dispose()


# ============================================================
# SubTask 6.2: 两策略各自 PnL 独立可核对
# ============================================================


class TestPnlIsolationOffline:
    """离线验证：两策略各自订单 → 各自 PnlRecord 独立、net_position 独立。"""

    async def test_pnl_isolation_offline(self, isolation_env):
        env = isolation_env
        grid_iid = env["grid_instance_id"]
        trend_iid = env["trend_instance_id"]
        account_id = env["account_id"]
        mock_client = env["mock_client"]
        db_factory = env["db_factory"]

        # 给 mock client 配置 get_position_risk（recompute 不依赖它，但避免 AttributeError）
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "0", "margin_ratio": 0.0})

        db = db_factory()
        try:
            # 策略 A（网格）订单：买 1.0 @ 3000，卖 0.5 @ 3100
            _insert_filled_order(db, grid_iid, account_id, "buy", 3000.0, 1.0)
            _insert_filled_order(db, grid_iid, account_id, "sell", 3100.0, 0.5)

            # 策略 B（趋势）订单：买 2.0 @ 2900，买 1.0 @ 2950
            _insert_filled_order(db, trend_iid, account_id, "buy", 2900.0, 2.0)
            _insert_filled_order(db, trend_iid, account_id, "buy", 2950.0, 1.0)
        finally:
            db.close()

        # 各自触发全量核算
        grid_snap = await pnl_accounting_engine.recompute(grid_iid, client=mock_client)
        trend_snap = await pnl_accounting_engine.recompute(trend_iid, client=mock_client)

        # 1. 网格 A：net_position = 1.0 - 0.5 = 0.5
        assert grid_snap.net_position == pytest.approx(0.5, abs=1e-9), \
            f"网格策略 net_position 应为 0.5，实际 {grid_snap.net_position}"
        # 网格 A 有卖单 → realized_pnl 非零（0.5 张 × (3100-3000) - 手续费）
        assert grid_snap.realized_pnl != 0, "网格策略有买+卖配对，realized_pnl 不应为 0"
        assert grid_snap.order_count == 2

        # 2. 趋势 B：net_position = 2.0 + 1.0 = 3.0（只有买单，无配对）
        assert trend_snap.net_position == pytest.approx(3.0, abs=1e-9), \
            f"趋势策略 net_position 应为 3.0，实际 {trend_snap.net_position}"
        # 趋势 B 无卖单 → 无配对 realized_pnl = 0
        assert trend_snap.realized_pnl == pytest.approx(0.0, abs=1e-9), \
            "趋势策略只有买单无配对，realized_pnl 应为 0"
        assert trend_snap.order_count == 2

        # 3. 独立性核对：DB 中 PnlRecord 的 strategy_instance_id 互不交叉
        db = db_factory()
        try:
            grid_records = db.query(PnlRecord).filter(
                PnlRecord.strategy_instance_id == grid_iid
            ).all()
            trend_records = db.query(PnlRecord).filter(
                PnlRecord.strategy_instance_id == trend_iid
            ).all()
        finally:
            db.close()

        assert len(grid_records) == 1, f"网格策略应有 1 条 PnlRecord，实际 {len(grid_records)}"
        assert len(trend_records) == 1, f"趋势策略应有 1 条 PnlRecord，实际 {len(trend_records)}"
        assert grid_records[0].strategy_instance_id == grid_iid
        assert trend_records[0].strategy_instance_id == trend_iid
        # net_position 互不相同且独立
        assert grid_records[0].net_position == pytest.approx(0.5, abs=1e-9)
        assert trend_records[0].net_position == pytest.approx(3.0, abs=1e-9)

    async def test_virtual_position_independent(self, isolation_env):
        """策略 A 的虚拟持仓不受策略 B 订单影响。

        - 先 recompute A，记录 A 的虚拟持仓
        - 再写入 B 的订单并 recompute B
        - 再次读取 A 的虚拟持仓，应保持不变
        """
        env = isolation_env
        grid_iid = env["grid_instance_id"]
        trend_iid = env["trend_instance_id"]
        account_id = env["account_id"]
        mock_client = env["mock_client"]
        db_factory = env["db_factory"]
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "0", "margin_ratio": 0.0})

        # 1. 策略 A 订单 + 核算
        db = db_factory()
        try:
            _insert_filled_order(db, grid_iid, account_id, "buy", 3000.0, 1.0)
            _insert_filled_order(db, grid_iid, account_id, "sell", 3100.0, 0.5)
        finally:
            db.close()
        await pnl_accounting_engine.recompute(grid_iid, client=mock_client)

        # 2. 构造策略 A 对象，读取虚拟持仓
        strategy_a = _make_grid_strategy(grid_iid, account_id, mock_client, db_factory)
        pos_a_before = strategy_a.get_virtual_position()
        assert pos_a_before["net_position"] == pytest.approx(0.5, abs=1e-9), \
            f"策略 A 虚拟持仓应为 0.5，实际 {pos_a_before['net_position']}"

        # 3. 写入策略 B 订单 + 核算 B（A 不应受影响）
        db = db_factory()
        try:
            _insert_filled_order(db, trend_iid, account_id, "buy", 2900.0, 5.0)
            _insert_filled_order(db, trend_iid, account_id, "buy", 2950.0, 3.0)
        finally:
            db.close()
        trend_snap = await pnl_accounting_engine.recompute(trend_iid, client=mock_client)
        assert trend_snap.net_position == pytest.approx(8.0, abs=1e-9)

        # 4. 再次读取策略 A 虚拟持仓：应保持 0.5 不变
        pos_a_after = strategy_a.get_virtual_position()
        assert pos_a_after["net_position"] == pytest.approx(0.5, abs=1e-9), \
            f"策略 B 下单后策略 A 虚拟持仓应仍为 0.5，实际 {pos_a_after['net_position']}"
        assert pos_a_after["realized_pnl"] == pytest.approx(
            pos_a_before["realized_pnl"], abs=1e-9
        ), "策略 A 的 realized_pnl 不应受策略 B 影响"


# ============================================================
# SubTask 6.3: 虚拟持仓之和 = 真实持仓（对账通过）
# ============================================================


class TestReconcilePositionsMatches:
    """虚拟持仓之和 = 真实持仓（Mock client.get_position_risk 返回 pos=sum）。"""

    async def test_reconcile_positions_matches(self, isolation_env):
        env = isolation_env
        grid_iid = env["grid_instance_id"]
        trend_iid = env["trend_instance_id"]
        account_id = env["account_id"]
        mock_client = env["mock_client"]
        db_factory = env["db_factory"]

        # 1. 两策略各自订单 + 核算（建立虚拟持仓）
        db = db_factory()
        try:
            # A：买 1.0，卖 0.5 → net=0.5
            _insert_filled_order(db, grid_iid, account_id, "buy", 3000.0, 1.0)
            _insert_filled_order(db, grid_iid, account_id, "sell", 3100.0, 0.5)
            # B：买 2.0，买 1.0 → net=3.0
            _insert_filled_order(db, trend_iid, account_id, "buy", 2900.0, 2.0)
            _insert_filled_order(db, trend_iid, account_id, "buy", 2950.0, 1.0)
        finally:
            db.close()

        await pnl_accounting_engine.recompute(grid_iid, client=mock_client)
        await pnl_accounting_engine.recompute(trend_iid, client=mock_client)

        # 虚拟持仓之和 = 0.5 + 3.0 = 3.5
        expected_virtual_total = 0.5 + 3.0

        # 2. Mock 真实持仓 = 虚拟持仓之和（对账应通过）
        mock_client.get_position_risk = AsyncMock(
            return_value={"pos": str(expected_virtual_total), "margin_ratio": 0.1}
        )

        result = await pnl_accounting_engine.reconcile_positions(
            account_id=account_id, symbol=SYMBOL, client=mock_client,
        )

        assert result["matched"] is True, (
            f"对账应通过：virtual_total={result['virtual_total']} "
            f"real_total={result['real_total']} diff={result['diff']}"
        )
        assert result["virtual_total"] == pytest.approx(expected_virtual_total, abs=1e-9)
        assert result["real_total"] == pytest.approx(expected_virtual_total, abs=1e-9)
        assert result["diff"] <= result["tolerance"]
        assert result["symbol"] == SYMBOL
        assert result["account_id"] == account_id

    async def test_reconcile_positions_mismatch_detected(self, isolation_env):
        """真实持仓与虚拟持仓之和不符时 matched=False（对账失败检测）。"""
        env = isolation_env
        grid_iid = env["grid_instance_id"]
        trend_iid = env["trend_instance_id"]
        account_id = env["account_id"]
        mock_client = env["mock_client"]
        db_factory = env["db_factory"]

        db = db_factory()
        try:
            _insert_filled_order(db, grid_iid, account_id, "buy", 3000.0, 1.0)
            _insert_filled_order(db, trend_iid, account_id, "buy", 2900.0, 2.0)
        finally:
            db.close()
        await pnl_accounting_engine.recompute(grid_iid, client=mock_client)
        await pnl_accounting_engine.recompute(trend_iid, client=mock_client)

        # 虚拟之和 = 3.0，真实持仓 = 5.0（不一致）
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "5.0"})

        result = await pnl_accounting_engine.reconcile_positions(
            account_id=account_id, symbol=SYMBOL, client=mock_client,
        )

        assert result["matched"] is False, "差异超容差时应 matched=False"
        assert result["virtual_total"] == pytest.approx(3.0, abs=1e-9)
        assert result["real_total"] == pytest.approx(5.0, abs=1e-9)
        assert result["diff"] > result["tolerance"]


# ============================================================
# SubTask 6.4: 一策略停止不影响另一策略 PnL 连续性
# ============================================================


class TestStrategyStopContinuity:
    """策略 A 停止后，策略 B 的 PnL 连续性不受影响。"""

    async def test_strategy_stop_does_not_affect_other(self, isolation_env):
        env = isolation_env
        grid_iid = env["grid_instance_id"]
        trend_iid = env["trend_instance_id"]
        account_id = env["account_id"]
        mock_client = env["mock_client"]
        db_factory = env["db_factory"]
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "0", "margin_ratio": 0.0})

        # 1. 两策略各自订单 + 核算
        db = db_factory()
        try:
            _insert_filled_order(db, grid_iid, account_id, "buy", 3000.0, 1.0)
            _insert_filled_order(db, trend_iid, account_id, "buy", 2900.0, 2.0)
        finally:
            db.close()
        await pnl_accounting_engine.recompute(grid_iid, client=mock_client)
        trend_snap_1 = await pnl_accounting_engine.recompute(trend_iid, client=mock_client)
        assert trend_snap_1.net_position == pytest.approx(2.0, abs=1e-9)

        # 2. 停止策略 A（更新 DB 状态）
        _set_instance_status(db_factory, grid_iid, "stopped")

        # 3. 策略 B 新增成交订单（PnL 连续性）
        db = db_factory()
        try:
            _insert_filled_order(db, trend_iid, account_id, "sell", 3200.0, 1.0)
        finally:
            db.close()
        trend_snap_2 = await pnl_accounting_engine.recompute(trend_iid, client=mock_client)

        # 4. 验证 B 的 PnL 连续性：net_position 从 2.0 → 1.0，realized_pnl 增加
        #    策略 B 累计订单：1 笔买（qty=2.0）+ 1 笔卖（qty=1.0）= 2 笔
        assert trend_snap_2.net_position == pytest.approx(1.0, abs=1e-9), \
            f"策略 B 卖出 1.0 后 net_position 应为 1.0，实际 {trend_snap_2.net_position}"
        assert trend_snap_2.realized_pnl > 0, "策略 B 卖出后应有正向 realized_pnl"
        assert trend_snap_2.order_count == 2, "策略 B 应累计 2 笔订单（1 买 + 1 卖）"

        # 5. DB 中 B 的 PnlRecord 仍可正常写入（连续性）
        db = db_factory()
        try:
            trend_records = db.query(PnlRecord).filter(
                PnlRecord.strategy_instance_id == trend_iid
            ).order_by(PnlRecord.recorded_at.asc()).all()
        finally:
            db.close()
        assert len(trend_records) >= 2, \
            f"策略 B 应有至少 2 条 PnlRecord（连续性），实际 {len(trend_records)}"
        # 最新记录反映卖出后状态
        latest = trend_records[-1]
        assert latest.net_position == pytest.approx(1.0, abs=1e-9)
        assert latest.realized_pnl > 0


# ============================================================
# SubTask 6.2-6.4: 仓位冲突检测
# ============================================================


class TestPositionConflictDetection:
    """策略 A 想平仓超过可用仓位时触发 position_conflict。"""

    async def test_position_conflict_detection(self, isolation_env):
        env = isolation_env
        grid_iid = env["grid_instance_id"]
        trend_iid = env["trend_instance_id"]
        account_id = env["account_id"]
        mock_client = env["mock_client"]
        db_factory = env["db_factory"]

        # 1. 两策略各自建立虚拟持仓
        #    A（网格）：net=1.0；B（趋势）：net=3.0
        db = db_factory()
        try:
            _insert_filled_order(db, grid_iid, account_id, "buy", 3000.0, 1.0)
            _insert_filled_order(db, trend_iid, account_id, "buy", 2900.0, 3.0)
        finally:
            db.close()
        await pnl_accounting_engine.recompute(grid_iid, client=mock_client)
        await pnl_accounting_engine.recompute(trend_iid, client=mock_client)

        # 2. Mock 真实持仓 = 4.0（= A 的 1.0 + B 的 3.0）
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "4.0", "margin_ratio": 0.1})

        # 3. 策略 A 想平仓 4.0：
        #    others_occupied = |B 的虚拟持仓| = 3.0
        #    available = |real_pos| - others_occupied = 4.0 - 3.0 = 1.0
        #    close_qty=4.0 > available=1.0 → 冲突
        strategy_a = _make_grid_strategy(grid_iid, account_id, mock_client, db_factory)
        result = await strategy_a.check_position_conflict(SYMBOL, close_qty=4.0)

        assert result is False, \
            "策略 A 平仓量超过可用仓位（真实 - 其他策略占用），应返回 False"

        # 4. 验证 position_conflict 事件写入 DB
        db = db_factory()
        try:
            events = db.query(StrategyEvent).filter(
                StrategyEvent.strategy_instance_id == grid_iid,
                StrategyEvent.event_type == "position_conflict",
            ).all()
        finally:
            db.close()
        assert len(events) >= 1, "应记录 position_conflict 事件"
        assert "close_qty" in (events[0].details or "")
        assert "available" in (events[0].details or "")

    async def test_position_conflict_no_conflict_when_available_enough(self, isolation_env):
        """平仓量 <= 可用仓位时无冲突（返回 True）。"""
        env = isolation_env
        grid_iid = env["grid_instance_id"]
        trend_iid = env["trend_instance_id"]
        account_id = env["account_id"]
        mock_client = env["mock_client"]
        db_factory = env["db_factory"]

        db = db_factory()
        try:
            _insert_filled_order(db, grid_iid, account_id, "buy", 3000.0, 1.0)
            _insert_filled_order(db, trend_iid, account_id, "buy", 2900.0, 3.0)
        finally:
            db.close()
        await pnl_accounting_engine.recompute(grid_iid, client=mock_client)
        await pnl_accounting_engine.recompute(trend_iid, client=mock_client)

        # 真实持仓 = 4.0，B 占用 3.0，A 可用 = 1.0，A 平仓 0.8 ≤ 1.0 → 无冲突
        mock_client.get_position_risk = AsyncMock(return_value={"pos": "4.0", "margin_ratio": 0.1})

        strategy_a = _make_grid_strategy(grid_iid, account_id, mock_client, db_factory)
        result = await strategy_a.check_position_conflict(SYMBOL, close_qty=0.8)
        assert result is True, "平仓量 <= 可用仓位时应返回 True"


# ============================================================
# SubTask 6.5: 真实 API 部分（@pytest.mark.demo，可跳过）
# ============================================================


from conftest_e2e import (  # noqa: E402
    DEMO_ACCOUNT_ID,
    SKIP_REASON,
    wait_for,
    get_instance_status,
    count_live_orders,
    get_latest_pnl,
)

demo_skip = pytest.mark.skipif(DEMO_ACCOUNT_ID is None, reason=SKIP_REASON)


@pytest.mark.demo
@demo_skip
def test_multi_strategy_isolation_demo(test_client, cleanup_strategy, demo_account_id):
    """真实模拟盘场景：启动网格 + 趋势两策略实例跑同一 ETH-USDT-SWAP，验证隔离。

    标记 @pytest.mark.demo，可通过 -m "not demo" 跳过；无 demo 账户时自动跳过。

    验证点：
    - 两策略实例均可启动并进入 running
    - 网格策略挂出 live 订单
    - 两策略的 PnlRecord 分属不同 strategy_instance_id（隔离）
    - 停止网格策略不影响趋势策略的 running 状态
    """
    GRID_DEMO_PARAMS = {
        "upper_price": 3500,
        "lower_price": 2500,
        "grid_count": 6,
        "order_qty": 1.0,
    }
    TREND_DEMO_PARAMS = {
        "fast_period": 5,
        "slow_period": 20,
        "order_qty": 1.0,
    }

    # 1. 创建网格模板 + 实例
    resp = test_client.post("/api/strategies/templates", json={
        "name": "E2E_ISOLATION_DEMO_GRID",
        "strategy_type": "grid",
        "description": "多策略隔离 demo 网格模板",
        "default_params": GRID_DEMO_PARAMS,
        "param_schema": {},
    })
    assert resp.status_code == 200, f"创建网格模板失败: {resp.text}"
    grid_tpl_id = resp.json()["id"]
    cleanup_strategy["templates"].append(grid_tpl_id)

    resp = test_client.post("/api/strategies/instances", json={
        "template_id": grid_tpl_id,
        "account_id": demo_account_id,
        "name": "E2E_ISOLATION_DEMO_GRID_INST",
        "symbol": SYMBOL,
        "market_type": MARKET,
        "params": GRID_DEMO_PARAMS,
    })
    assert resp.status_code == 200, f"创建网格实例失败: {resp.text}"
    grid_iid = resp.json()["id"]
    cleanup_strategy["instances"].append(grid_iid)

    # 2. 创建趋势模板 + 实例
    resp = test_client.post("/api/strategies/templates", json={
        "name": "E2E_ISOLATION_DEMO_TREND",
        "strategy_type": "trend",
        "description": "多策略隔离 demo 趋势模板",
        "default_params": TREND_DEMO_PARAMS,
        "param_schema": {},
    })
    assert resp.status_code == 200, f"创建趋势模板失败: {resp.text}"
    trend_tpl_id = resp.json()["id"]
    cleanup_strategy["templates"].append(trend_tpl_id)

    resp = test_client.post("/api/strategies/instances", json={
        "template_id": trend_tpl_id,
        "account_id": demo_account_id,
        "name": "E2E_ISOLATION_DEMO_TREND_INST",
        "symbol": SYMBOL,
        "market_type": MARKET,
        "params": TREND_DEMO_PARAMS,
    })
    assert resp.status_code == 200, f"创建趋势实例失败: {resp.text}"
    trend_iid = resp.json()["id"]
    cleanup_strategy["instances"].append(trend_iid)

    # 3. 启动两策略
    assert test_client.post(f"/api/strategies/instances/{grid_iid}/start").status_code == 200
    assert test_client.post(f"/api/strategies/instances/{trend_iid}/start").status_code == 200
    wait_for(lambda: get_instance_status(grid_iid) == "running", timeout=15, desc="网格策略 running")
    wait_for(lambda: get_instance_status(trend_iid) == "running", timeout=15, desc="趋势策略 running")

    # 4. 网格策略应挂出 live 订单
    wait_for(lambda: count_live_orders(grid_iid) > 0, timeout=30, desc="网格 live 订单出现")
    assert count_live_orders(grid_iid) > 0

    # 5. 触发各自 PnL 核算（即使无成交也会写入一条快照）
    test_client.post(f"/api/pnl/recompute/{grid_iid}")
    test_client.post(f"/api/pnl/recompute/{trend_iid}")

    # 6. 验证两策略的 PnlRecord 分属不同 strategy_instance_id（隔离）
    grid_pnl = get_latest_pnl(grid_iid)
    trend_pnl = get_latest_pnl(trend_iid)
    assert grid_pnl is not None, "网格策略无 PnlRecord"
    assert trend_pnl is not None, "趋势策略无 PnlRecord"
    assert grid_pnl.strategy_instance_id == grid_iid
    assert trend_pnl.strategy_instance_id == trend_iid
    assert grid_pnl.strategy_instance_id != trend_pnl.strategy_instance_id

    # 7. 停止网格策略，验证趋势策略仍 running（隔离）
    test_client.post(f"/api/strategies/instances/{grid_iid}/stop")
    wait_for(lambda: get_instance_status(grid_iid) == "stopped", timeout=10, desc="网格策略 stopped")
    assert get_instance_status(trend_iid) == "running", "停止网格策略后趋势策略应仍 running"

    # 8. 停止趋势策略以清理
    test_client.post(f"/api/strategies/instances/{trend_iid}/stop")
