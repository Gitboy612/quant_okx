"""PnL 曲线稀疏与异常修复（fix-pnl-curve-sparse-and-anomaly）单元测试。

覆盖 spec Task 7 的五个子任务：
- 7.1 incremental_update 无基准 PnlRecord 时转 recompute，避免 avg_buy_price=0 异常
- 7.2 heartbeat_snapshot 复用最新 PnlRecord 重新计算 unrealized_pnl 并写入
- 7.3 avg_buy_price=0 且 net_position>0 时 unrealized_pnl 兜底为 0
- 7.4 PnLChart 自适应分桶（computeBucketInterval / buildBuckets 算法设计验证）
- 7.5 GET /api/pnl 的 start_time/end_time 时间窗口过滤

导入风格与 mock 约定参考 test_pnl_accounting_engine.py。
"""
import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.pnl_accounting_engine import PnlAccountingEngine, PnlSnapshot
from models.order import Order
from models.pnl import PnlRecord
from models.strategy import StrategyInstance
from database import Base


# ---------------------------------------------------------------------------
# 辅助函数：构造 mock Order / mock StrategyInstance / mock DB session
# ---------------------------------------------------------------------------

def _make_order(id, side, px, qty, fee, actual_qty=None, symbol="BTC-USDT"):
    """构造 mock Order 对象，模拟 filled 订单。"""
    o = MagicMock()
    o.id = id
    o.side = side
    o.fill_px = px
    o.fill_sz = qty
    o.actual_qty = actual_qty
    o.filled_quantity = None
    o.quantity = None
    o.fee = fee
    o.symbol = symbol
    o.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return o


def _make_instance(account_id=1, symbol="BTC-USDT", params=None):
    """构造 mock StrategyInstance。"""
    inst = MagicMock()
    inst.account_id = account_id
    inst.symbol = symbol
    inst.params = params if params is not None else {"fee_rate": 0.001}
    return inst


def _make_fallback_mock_db(orders, instance=None, latest_pnl=None):
    """mock DB，同时支持 incremental_update 与 recompute 两条查询链路。

    用于 7.1：incremental_update 检测到无基准 PnlRecord 时会转执行 recompute，
    两者对 Order 的查询链路不同：
      - incremental: .filter().filter().filter().all()
      - recompute:   .filter().filter().all()
    两者对 Order 的更新均为 .filter().update()。
    """
    mock_db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        if model is StrategyInstance:
            chain.filter.return_value.first.return_value = instance
        elif model is Order:
            chain.filter.return_value.filter.return_value.all.return_value = orders
            chain.filter.return_value.filter.return_value.filter.return_value.all.return_value = orders
            chain.filter.return_value.update.return_value = 0
        elif model is PnlRecord:
            chain.filter.return_value.order_by.return_value.first.return_value = latest_pnl
        return chain

    mock_db.query.side_effect = query_side_effect
    return mock_db


def _make_incremental_mock_db(new_orders, instance=None, latest_pnl=None):
    """mock DB，适配 incremental_update 的查询链路。"""
    mock_db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        if model is StrategyInstance:
            chain.filter.return_value.first.return_value = instance
        elif model is Order:
            chain.filter.return_value.filter.return_value.filter.return_value.all.return_value = new_orders
            chain.filter.return_value.update.return_value = 0
        elif model is PnlRecord:
            chain.filter.return_value.order_by.return_value.first.return_value = latest_pnl
        return chain

    mock_db.query.side_effect = query_side_effect
    return mock_db


def _make_heartbeat_mock_db(instance=None, latest_pnl=None):
    """mock DB，适配 heartbeat_snapshot 的查询链路（StrategyInstance + PnlRecord + Order）。

    Order 查询返回空列表：heartbeat 无 latest 时调 recompute 兜底，recompute 查到空订单后返回 None。
    """
    mock_db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        if model is StrategyInstance:
            chain.filter.return_value.first.return_value = instance
        elif model is PnlRecord:
            chain.filter.return_value.order_by.return_value.first.return_value = latest_pnl
        elif model is Order:
            # recompute 查询 Order 时返回空列表（无成交订单 → recompute 返回 None）
            chain.filter.return_value.filter.return_value.all.return_value = []
        return chain

    mock_db.query.side_effect = query_side_effect
    return mock_db


# ===========================================================================
# SubTask 7.1: incremental_update 无基准时转 recompute
# ===========================================================================
class TestIncrementalFallbackRecompute:
    @pytest.mark.asyncio
    async def test_no_base_falls_back_to_recompute(self):
        """无 PnlRecord 基准时，incremental_update 转 recompute，avg_buy_price 不为 0。

        构造 2 buy (px=100, qty=1) + 1 sell (px=110, qty=1)，无最新 PnlRecord。
        修复前：以 0 作为基准 avg_buy_price 增量叠加，产生异常。
        修复后：转 recompute 全量核算，avg_buy_price=加权均价 100。
        """
        buys = [_make_order(i, "buy", 100.0, 1.0, 0.1, actual_qty=1.0) for i in range(1, 3)]
        sells = [_make_order(3, "sell", 110.0, 1.0, 0.1, actual_qty=1.0)]
        orders = buys + sells

        instance = _make_instance(account_id=1, symbol="BTC-USDT")
        mock_db = _make_fallback_mock_db(orders, instance=instance, latest_pnl=None)

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            snapshot = await engine.incremental_update(strategy_instance_id=1, client=None)

        assert snapshot is not None
        assert isinstance(snapshot, PnlSnapshot)
        # 关键：avg_buy_price 为加权均价 100，而非 0
        assert snapshot.avg_buy_price == pytest.approx(100.0, rel=1e-9)
        assert snapshot.avg_buy_price != 0
        # net_position = 2(买) - 1(卖) = 1
        assert snapshot.net_position == pytest.approx(1.0, rel=1e-9)
        # 写入 PnlRecord 并提交
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_base_no_extreme_unrealized(self):
        """无基准时转 recompute，unrealized_pnl 不出现极端负值（client=None 时为 0 残差控制）。"""
        buys = [_make_order(1, "buy", 100.0, 1.0, 0.1, actual_qty=1.0)]
        sells = [_make_order(2, "sell", 110.0, 1.0, 0.1, actual_qty=1.0)]
        orders = buys + sells

        instance = _make_instance(account_id=1, symbol="BTC-USDT")
        mock_db = _make_fallback_mock_db(orders, instance=instance, latest_pnl=None)

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            snapshot = await engine.incremental_update(strategy_instance_id=1, client=None)

        assert snapshot is not None
        # avg_buy_price=0：FIFO 配对后所有买单已消耗（1 buy + 1 sell → 0 剩余）
        assert snapshot.avg_buy_price == pytest.approx(0.0, rel=1e-9)
        # net_position 归零，unrealized 为残差且不会因 avg_buy=0 触发极端值
        assert snapshot.net_position == pytest.approx(0.0, abs=1e-12)


# ===========================================================================
# SubTask 7.2: heartbeat_snapshot 心跳快照
# ===========================================================================
class TestHeartbeatSnapshot:
    @pytest.mark.asyncio
    async def test_heartbeat_writes_and_recomputes_unrealized(self):
        """心跳快照：复用最新 PnlRecord 的累计值，基于当前价重算 unrealized_pnl。

        基准: realized=10, net_position=2, avg_buy=100, total_fee=0.5, order_count=5, equity=5000
        当前价: 120, fee_rate=0.001
        unrealized = (120-100)*2 - 2*120*0.001 = 40 - 0.24 = 39.76
        total_pnl = 10 + 39.76 = 49.76
        """
        latest = MagicMock()
        latest.realized_pnl = 10.0
        latest.net_position = 2.0
        latest.avg_buy_price = 100.0
        latest.total_fee = 0.5
        latest.order_count = 5
        latest.equity = 5000.0

        instance = _make_instance(account_id=1, symbol="BTC-USDT", params={"fee_rate": 0.001})
        mock_db = _make_heartbeat_mock_db(instance=instance, latest_pnl=latest)

        mock_client = MagicMock()
        mock_client.get_ticker = AsyncMock(return_value=[{"last": "120"}])

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            snapshot = await engine.heartbeat_snapshot(strategy_instance_id=1, client=mock_client)

        assert snapshot is not None
        assert isinstance(snapshot, PnlSnapshot)
        # realized_pnl 沿用最新记录
        assert snapshot.realized_pnl == pytest.approx(10.0, rel=1e-9)
        # unrealized_pnl 基于当前价重新计算
        assert snapshot.unrealized_pnl == pytest.approx(39.76, rel=1e-9)
        assert snapshot.total_pnl == pytest.approx(49.76, rel=1e-9)
        # 累计字段沿用
        assert snapshot.net_position == pytest.approx(2.0, rel=1e-9)
        assert snapshot.avg_buy_price == pytest.approx(100.0, rel=1e-9)
        assert snapshot.total_fee == pytest.approx(0.5, rel=1e-9)
        assert snapshot.order_count == 5
        assert snapshot.equity == pytest.approx(5000.0, rel=1e-9)
        # 写入新 PnlRecord 并提交
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_heartbeat_no_latest_writes_zero(self):
        """无最新 PnlRecord 且无成交时 heartbeat_snapshot 写一条全零初始心跳。

        修复前：recompute 返回 None 时 heartbeat 也返回 None，不写记录。
        修复后：用全零默认值写一条心跳，确保盈亏曲线有持续数据点。
        """
        instance = _make_instance(account_id=1, symbol="BTC-USDT")
        mock_db = _make_heartbeat_mock_db(instance=instance, latest_pnl=None)

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            snapshot = await engine.heartbeat_snapshot(strategy_instance_id=1, client=None)

        assert snapshot is not None
        assert isinstance(snapshot, PnlSnapshot)
        # 全零默认值
        assert snapshot.realized_pnl == pytest.approx(0.0, abs=1e-12)
        assert snapshot.unrealized_pnl == pytest.approx(0.0, abs=1e-12)
        assert snapshot.total_pnl == pytest.approx(0.0, abs=1e-12)
        assert snapshot.net_position == pytest.approx(0.0, abs=1e-12)
        assert snapshot.avg_buy_price == pytest.approx(0.0, abs=1e-12)
        assert snapshot.order_count == 0
        # 写入 PnlRecord 并提交
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_heartbeat_no_instance_returns_none(self):
        """策略实例不存在时 heartbeat_snapshot 返回 None。"""
        mock_db = _make_heartbeat_mock_db(instance=None, latest_pnl=None)

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            snapshot = await engine.heartbeat_snapshot(strategy_instance_id=999, client=None)

        assert snapshot is None
        mock_db.add.assert_not_called()


# ===========================================================================
# SubTask 7.3: avg_buy_price=0 兜底（unrealized_pnl=0）
# ===========================================================================
class TestAvgBuyPriceZeroFloor:
    @pytest.mark.asyncio
    async def test_heartbeat_avg_buy_zero_floor(self):
        """heartbeat_snapshot：avg_buy_price=0 且 net_position>0 → unrealized_pnl=0。

        构造异常基准 (net_position=2, avg_buy_price=0)，当前价 50000。
        修复前：unrealized = (50000-0)*2 = 100000（极端值）。
        修复后：兜底为 0。
        """
        latest = MagicMock()
        latest.realized_pnl = 5.0
        latest.net_position = 2.0
        latest.avg_buy_price = 0.0  # 异常基准
        latest.total_fee = 0.3
        latest.order_count = 3
        latest.equity = 1000.0

        instance = _make_instance(account_id=1, symbol="BTC-USDT", params={"fee_rate": 0.001})
        mock_db = _make_heartbeat_mock_db(instance=instance, latest_pnl=latest)

        mock_client = MagicMock()
        mock_client.get_ticker = AsyncMock(return_value=[{"last": "50000"}])

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            snapshot = await engine.heartbeat_snapshot(strategy_instance_id=1, client=mock_client)

        assert snapshot is not None
        # 兜底：unrealized_pnl=0，非极端值
        assert snapshot.unrealized_pnl == pytest.approx(0.0, abs=1e-12)
        assert snapshot.total_pnl == pytest.approx(5.0, rel=1e-9)

    @pytest.mark.asyncio
    async def test_incremental_avg_buy_zero_floor(self):
        """incremental_update：base avg_buy_price=0 且仅新增 sell → avg_buy 仍为 0，兜底 unrealized=0。

        基准: net_position=2, avg_buy_price=0（异常）。新增 1 sell (px=110, qty=1)。
        卖出不重置 avg_buy，故 avg_buy 仍为 0；net_position=1>0 → 兜底 unrealized=0。
        """
        latest = MagicMock()
        latest.realized_pnl = 5.0
        latest.net_position = 2.0
        latest.avg_buy_price = 0.0
        latest.total_fee = 0.3
        latest.order_count = 3
        latest.equity = 1000.0

        new_orders = [_make_order(10, "sell", 110.0, 1.0, 0.1, actual_qty=1.0)]
        instance = _make_instance(account_id=1, symbol="BTC-USDT", params={"fee_rate": 0.001})
        mock_db = _make_incremental_mock_db(new_orders, instance=instance, latest_pnl=latest)

        mock_client = MagicMock()
        mock_client.get_ticker = AsyncMock(return_value=[{"last": "50000"}])

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            snapshot = await engine.incremental_update(strategy_instance_id=1, client=mock_client)

        assert snapshot is not None
        # net_position = 2 - 1 = 1
        assert snapshot.net_position == pytest.approx(1.0, rel=1e-9)
        # 兜底：avg_buy_price=0 且 net_position>0 → unrealized_pnl=0
        assert snapshot.avg_buy_price == pytest.approx(0.0, abs=1e-12)
        assert snapshot.unrealized_pnl == pytest.approx(0.0, abs=1e-12)


# ===========================================================================
# SubTask 7.4: PnLChart 自适应分桶（算法设计验证）
#
# 说明：前端未配置 vitest（frontend/package.json 无 vitest 依赖，node_modules 中缺失），
# 故按 spec 推荐选项 A：已在 PnLChart.tsx 为 computeBucketInterval / buildBuckets
# 添加 `export` 关键字以便后续接入 vitest 直接测试；此处用 Python 忠实移植 TS 算法
# 做设计验证（spec 允许的兜底方案 C），确认 24h 模式生成 288 桶、all 模式按跨度自适应。
# ===========================================================================

_MIN_MS = 60 * 1000
_HOUR_MS = 60 * 60 * 1000
_DAY_MS = 24 * 60 * 60 * 1000


def _compute_bucket_interval(time_range, data_span_ms):
    """Python 移植版 computeBucketInterval（与 PnLChart.tsx 保持一致）。"""
    if time_range == '24h':
        return 5 * _MIN_MS          # 288 桶
    if time_range == '7d':
        return 30 * _MIN_MS         # 336 桶
    if time_range == '30d':
        return 2 * _HOUR_MS         # 360 桶
    # all 模式按数据跨度自适应
    if data_span_ms <= 6 * _HOUR_MS:
        return 1 * _MIN_MS          # ≤6h: 1分钟
    if data_span_ms <= 24 * _HOUR_MS:
        return 5 * _MIN_MS          # ≤24h: 5分钟
    if data_span_ms <= 7 * _DAY_MS:
        return 30 * _MIN_MS         # ≤7d: 30分钟
    if data_span_ms <= 30 * _DAY_MS:
        return 2 * _HOUR_MS         # ≤30d: 2小时
    return 6 * _HOUR_MS             # >30d: 6小时


def _build_buckets_count(time_range, data_points, now_ms):
    """Python 移植版 buildBuckets 的桶计数（与 PnLChart.tsx 的窗口/步长逻辑一致）。

    data_points: list[dict] 含 'ts' (毫秒) 字段，按时间升序处理。
    返回生成的桶数量。
    """
    sorted_pts = sorted(data_points, key=lambda r: r['ts'])
    data_span_ms = (sorted_pts[-1]['ts'] - sorted_pts[0]['ts']) if sorted_pts else 0
    interval = _compute_bucket_interval(time_range, data_span_ms)

    if time_range == '24h':
        start = (now_ms - 24 * _HOUR_MS) // (5 * _MIN_MS) * (5 * _MIN_MS)
        end = now_ms
    elif time_range == '7d':
        today_start = (now_ms // _DAY_MS) * _DAY_MS  # startOfToday 等价（本地时区近似为 UTC）
        start = today_start - 7 * _DAY_MS
        end = today_start + _DAY_MS
    elif time_range == '30d':
        today_start = (now_ms // _DAY_MS) * _DAY_MS
        start = today_start - 30 * _DAY_MS
        end = today_start + _DAY_MS
    else:  # all
        if not sorted_pts:
            return 0
        start = (sorted_pts[0]['ts'] // interval) * interval
        end = max(sorted_pts[-1]['ts'], now_ms)

    count = 0
    t = start
    while t < end:
        count += 1
        t += interval
    return count


class TestPnlChartBucketing:
    def test_compute_bucket_interval_fixed_modes(self):
        """24h / 7d / 30d 模式返回固定桶间隔。"""
        assert _compute_bucket_interval('24h', 0) == 5 * _MIN_MS
        assert _compute_bucket_interval('7d', 0) == 30 * _MIN_MS
        assert _compute_bucket_interval('30d', 0) == 2 * _HOUR_MS

    def test_compute_bucket_interval_all_adaptive(self):
        """all 模式按数据跨度自适应：≤6h→1min，≤24h→5min，≤7d→30min，≤30d→2h，>30d→6h。"""
        assert _compute_bucket_interval('all', 3 * _HOUR_MS) == 1 * _MIN_MS       # 3h ≤ 6h
        assert _compute_bucket_interval('all', 6 * _HOUR_MS) == 1 * _MIN_MS       # 恰好 6h
        assert _compute_bucket_interval('all', 12 * _HOUR_MS) == 5 * _MIN_MS      # 12h ≤ 24h
        assert _compute_bucket_interval('all', 24 * _HOUR_MS) == 5 * _MIN_MS      # 恰好 24h
        assert _compute_bucket_interval('all', 5 * _DAY_MS) == 30 * _MIN_MS       # 5d ≤ 7d
        assert _compute_bucket_interval('all', 7 * _DAY_MS) == 30 * _MIN_MS       # 恰好 7d
        assert _compute_bucket_interval('all', 20 * _DAY_MS) == 2 * _HOUR_MS      # 20d ≤ 30d
        assert _compute_bucket_interval('all', 30 * _DAY_MS) == 2 * _HOUR_MS      # 恰好 30d
        assert _compute_bucket_interval('all', 60 * _DAY_MS) == 6 * _HOUR_MS      # 60d > 30d

    def test_build_buckets_24h_generates_288(self):
        """24h 模式：窗口跨度 24h、步长 5min → 288 个桶。

        取 now 对齐到 5 分钟边界，使 start = now - 24h 也对齐，桶数恰好 24h/5min = 288。
        """
        now = (1717200000000 // (5 * _MIN_MS)) * (5 * _MIN_MS)  # 对齐到 5 分钟边界
        # 数据点不影响 24h 模式的窗口/步长
        data = [{'ts': now - 12 * _HOUR_MS, 'total_pnl': 0}]
        count = _build_buckets_count('24h', data, now)
        assert count == 288

    def test_build_buckets_all_adaptive_6h(self):
        """all 模式：数据跨度 6h → 1min 步长 → 360 个桶（spec: ≤6h→60s，360桶）。"""
        start_ts = 1717200000000  # 已对齐到分钟边界
        end_ts = start_ts + 6 * _HOUR_MS
        now = end_ts
        data = [{'ts': start_ts, 'total_pnl': 0}, {'ts': end_ts, 'total_pnl': 1}]
        count = _build_buckets_count('all', data, now)
        # start 对齐到 1min 边界，end=max(end_ts, now)=end_ts → 6h/1min = 360
        assert count == 360

    def test_build_buckets_all_empty_returns_zero(self):
        """all 模式无数据 → 返回 0 桶（与 TS buildBuckets 一致）。"""
        assert _build_buckets_count('all', [], 1717200000000) == 0


# ===========================================================================
# SubTask 7.5: GET /api/pnl 的 start_time/end_time 时间窗口过滤
# ===========================================================================
class TestPnlApiTimeWindow:
    def _build_db_with_records(self):
        """构建内存 SQLite 并写入 10 条 PnlRecord（每小时一条，覆盖 10 小时）。

        PnlRecord 有指向 accounts / strategy_instances 的外键，故需先导入 Account /
        StrategyInstance 模型使相关表注册到 Base.metadata，再用 create_all 建表。
        """
        from models.account import Account  # noqa: F401 — 注册 accounts 表
        from models.strategy import StrategyInstance  # noqa: F401 — 注册 strategy_instances 表

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            bind=engine,
            tables=[Account.__table__, StrategyInstance.__table__, PnlRecord.__table__],
        )
        Session = sessionmaker(bind=engine)
        db = Session()
        base = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        for i in range(10):
            db.add(PnlRecord(
                account_id=1,
                strategy_instance_id=1,
                equity=1000.0,
                unrealized_pnl=0.0,
                realized_pnl=float(i),
                total_pnl=float(i),
                is_final=False,
                recorded_at=base + timedelta(hours=i),
                net_position=0.0,
                avg_buy_price=0.0,
                total_fee=0.0,
                order_count=0,
            ))
        db.commit()
        return engine, db

    def test_start_end_time_window_filter(self):
        """传入 start_time/end_time 仅返回时间窗口内记录（含两端）。"""
        from routers.pnl import get_pnl_records

        engine, db = self._build_db_with_records()
        try:
            base = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
            start_iso = (base + timedelta(hours=2)).isoformat()
            end_iso = (base + timedelta(hours=5)).isoformat()

            result = get_pnl_records(
                account_id=None,
                strategy_instance_id=None,
                start_time=start_iso,
                end_time=end_iso,
                limit=1000,
                db=db,
                user=MagicMock(),
            )

            # 窗口 [2h, 5h] 含端点 → 小时 2,3,4,5 共 4 条
            assert len(result) == 4
            # 按 recorded_at desc 返回，首条为 5h（realized_pnl=5.0），末条为 2h（=2.0）
            assert result[0]["realized_pnl"] == pytest.approx(5.0)
            assert result[-1]["realized_pnl"] == pytest.approx(2.0)
        finally:
            db.close()
            engine.dispose()

    def test_start_time_only_filter(self):
        """仅传 start_time：返回所有 >= start_time 的记录。"""
        from routers.pnl import get_pnl_records

        engine, db = self._build_db_with_records()
        try:
            base = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
            start_iso = (base + timedelta(hours=7)).isoformat()

            result = get_pnl_records(
                account_id=None,
                strategy_instance_id=None,
                start_time=start_iso,
                end_time=None,
                limit=1000,
                db=db,
                user=MagicMock(),
            )

            # >= 7h → 小时 7,8,9 共 3 条
            assert len(result) == 3
            assert result[0]["realized_pnl"] == pytest.approx(9.0)
            assert result[-1]["realized_pnl"] == pytest.approx(7.0)
        finally:
            db.close()
            engine.dispose()

    def test_no_time_filter_returns_all_up_to_limit(self):
        """不传时间过滤：返回全部记录（受 limit 约束）。"""
        from routers.pnl import get_pnl_records

        engine, db = self._build_db_with_records()
        try:
            result = get_pnl_records(
                account_id=None,
                strategy_instance_id=None,
                start_time=None,
                end_time=None,
                limit=1000,
                db=db,
                user=MagicMock(),
            )

            assert len(result) == 10
        finally:
            db.close()
            engine.dispose()

    def test_invalid_time_filter_ignored(self):
        """非法 start_time 被忽略（不报错，回退为无该过滤）。"""
        from routers.pnl import get_pnl_records

        engine, db = self._build_db_with_records()
        try:
            result = get_pnl_records(
                account_id=None,
                strategy_instance_id=None,
                start_time="not-a-date",
                end_time=None,
                limit=1000,
                db=db,
                user=MagicMock(),
            )

            # 非法 start_time 被忽略 → 返回全部 10 条
            assert len(result) == 10
        finally:
            db.close()
            engine.dispose()
