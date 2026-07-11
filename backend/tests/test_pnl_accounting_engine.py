"""PnL 核算引擎单元测试。

覆盖：
- PnlAccountingEngine.recompute 全量核算
- PnlAccountingEngine.incremental_update 增量核算
- 合约 actual_qty 计算（_qty 方法优先取 actual_qty）
- InstrumentCache 缓存命中与异常兜底
- OrderManager.add_order 注入 ct_val 并计算 actual_qty

导入风格参考 conftest.py 与 test_pnl_algorithm_fix.py：顶部注入 backend 根目录到 sys.path。
"""
import sys
import os
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.pnl_accounting_engine import PnlAccountingEngine, PnlSnapshot
from services.instrument_cache import InstrumentCache
from services.order_manager import OrderManager, OrderInfo
from models.order import Order
from models.pnl import PnlRecord
from models.strategy import StrategyInstance


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


def _make_recompute_mock_db(orders, instance=None, latest_pnl=None):
    """构造 mock DB session，适配 recompute 的查询链路。

    recompute 涉及的 query 链路：
      - StrategyInstance: .filter().first()
      - Order: .filter().filter().all()  /  .filter().update()
      - PnlRecord: .filter().order_by().first()
    """
    mock_db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        if model is StrategyInstance:
            chain.filter.return_value.first.return_value = instance
        elif model is Order:
            # .filter().filter().all() — 查询 filled 订单
            chain.filter.return_value.filter.return_value.all.return_value = orders
            # .filter().update() — 批量标记 pnl_accounted=True
            chain.filter.return_value.update.return_value = 0
        elif model is PnlRecord:
            # .filter().order_by().first()
            chain.filter.return_value.order_by.return_value.first.return_value = latest_pnl
        return chain

    mock_db.query.side_effect = query_side_effect
    return mock_db


def _make_incremental_mock_db(new_orders, instance=None, latest_pnl=None):
    """构造 mock DB session，适配 incremental_update 的查询链路。

    incremental_update 涉及的 query 链路：
      - StrategyInstance: .filter().first()
      - Order: .filter().filter().filter().order_by().all()  /  .filter().update()
      - PnlRecord: .filter().order_by().first()
    """
    mock_db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        if model is StrategyInstance:
            chain.filter.return_value.first.return_value = instance
        elif model is Order:
            # .filter().filter().filter().order_by().all() — 查询未核算订单
            chain.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = new_orders
            # .filter().update() — 批量标记 pnl_accounted=True
            chain.filter.return_value.update.return_value = 0
        elif model is PnlRecord:
            chain.filter.return_value.order_by.return_value.first.return_value = latest_pnl
        return chain

    mock_db.query.side_effect = query_side_effect
    return mock_db


# ===========================================================================
# 1. 测试全量核算（recompute）
# ===========================================================================
class TestRecompute:
    @pytest.mark.asyncio
    async def test_recompute_basic(self):
        """构造 10 笔 filled 订单（5 buy + 5 sell），验证 total_pnl / realized_pnl / unrealized_pnl 计算正确"""
        # 5 buy: qty=1.0, px=100, fee=0.1
        buys = [_make_order(i, "buy", 100.0, 1.0, 0.1, actual_qty=1.0) for i in range(1, 6)]
        # 5 sell: qty=1.0, px=110, fee=0.1
        sells = [_make_order(i, "sell", 110.0, 1.0, 0.1, actual_qty=1.0) for i in range(6, 11)]
        orders = buys + sells

        instance = _make_instance(account_id=1, symbol="BTC-USDT")
        mock_db = _make_recompute_mock_db(orders, instance=instance, latest_pnl=None)

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            snapshot = await engine.recompute(strategy_instance_id=1, client=None)

        # buy_total = 5 × 1.0 × 100 = 500
        # sell_total = 5 × 1.0 × 110 = 550
        # total_fee = 10 × 0.1 = 1.0
        # total_pnl = 550 - 500 - 1 = 49
        assert snapshot.total_pnl == pytest.approx(49.0, rel=1e-9)
        # matched_qty = 5, avg_buy_px = 100, avg_sell_px = 110
        # avg_fee_per_unit = 1.0 / 10 = 0.1
        # realized_pnl = 5 × (110-100) - 5 × 0.1 = 50 - 0.5 = 49.5
        assert snapshot.realized_pnl == pytest.approx(49.5, rel=1e-9)
        # unrealized_pnl = total_pnl - realized_pnl = 49 - 49.5 = -0.5
        assert snapshot.unrealized_pnl == pytest.approx(-0.5, rel=1e-9)
        # net_position = 5 - 5 = 0
        assert snapshot.net_position == pytest.approx(0.0, abs=1e-12)
        # avg_buy_price = 500 / 5 = 100
        assert snapshot.avg_buy_price == pytest.approx(100.0, rel=1e-9)
        # total_fee = 1.0
        assert snapshot.total_fee == pytest.approx(1.0, rel=1e-9)
        # order_count = 10
        assert snapshot.order_count == 10
        # 返回类型为 PnlSnapshot
        assert isinstance(snapshot, PnlSnapshot)
        # 验证写入 PnlRecord 并提交
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()


# ===========================================================================
# 2. 测试增量核算（incremental_update）
# ===========================================================================
class TestIncrementalUpdate:
    @pytest.mark.asyncio
    async def test_no_new_orders_returns_none(self):
        """无新增订单时返回 None"""
        instance = _make_instance()
        mock_db = _make_incremental_mock_db([], instance=instance, latest_pnl=None)

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            result = await engine.incremental_update(strategy_instance_id=1, client=None)

        assert result is None
        # 无新增订单时不应写入 PnlRecord
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_incremental_after_recompute(self):
        """首次 recompute 后新增 3 笔 filled，验证 incremental_update 累计值正确

        基准: realized=10, net_position=2, avg_buy=100, total_fee=0.5, order_count=5
        新增: 2 buy (qty=1, px=105) + 1 sell (qty=1, px=115)
        """
        # 基准 PnlRecord
        latest = MagicMock()
        latest.realized_pnl = 10.0
        latest.net_position = 2.0
        latest.avg_buy_price = 100.0
        latest.total_fee = 0.5
        latest.order_count = 5
        latest.equity = 5000.0

        # 新增 3 笔: 2 buy (qty=1, px=105) + 1 sell (qty=1, px=115)
        new_orders = [
            _make_order(101, "buy", 105.0, 1.0, 0.1, actual_qty=1.0),
            _make_order(102, "buy", 105.0, 1.0, 0.1, actual_qty=1.0),
            _make_order(103, "sell", 115.0, 1.0, 0.1, actual_qty=1.0),
        ]

        instance = _make_instance(account_id=1, symbol="BTC-USDT", params={"fee_rate": 0.001})
        mock_db = _make_incremental_mock_db(new_orders, instance=instance, latest_pnl=latest)

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            snapshot = await engine.incremental_update(strategy_instance_id=1, client=None)

        # net_position = 2 + 2(买) - 1(卖) = 3
        assert snapshot.net_position == pytest.approx(3.0, rel=1e-9)
        # avg_buy_price = (2×100 + 2×1×105) / 4 = 410/4 = 102.5
        assert snapshot.avg_buy_price == pytest.approx(102.5, rel=1e-9)
        # realized_pnl: 卖出 1 张时 net_position 从 4→3（未归零），不触发闭环，realized 保持 10
        assert snapshot.realized_pnl == pytest.approx(10.0, rel=1e-9)
        # total_fee = 0.5 + 3×0.1 = 0.8
        assert snapshot.total_fee == pytest.approx(0.8, rel=1e-9)
        # order_count = 5 + 3 = 8
        assert snapshot.order_count == 8
        # client=None → unrealized_pnl=0, total_pnl=realized+unrealized=10
        assert snapshot.unrealized_pnl == pytest.approx(0.0, abs=1e-12)
        assert snapshot.total_pnl == pytest.approx(10.0, rel=1e-9)
        # equity 保留上次值
        assert snapshot.equity == pytest.approx(5000.0, rel=1e-9)
        # 验证写入 PnlRecord 并提交
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()


# ===========================================================================
# 3. 测试合约 actual_qty
# ===========================================================================
class TestContractActualQty:
    def test_swap_actual_qty(self):
        """SWAP 订单 sz=10 ct_val=0.1，actual_qty=1.0 时 _qty 返回 1.0（而非 fill_sz=10）

        actual_qty 由 OrderManager.add_order 计算：sz × ct_val = 10 × 0.1 = 1.0
        PnlAccountingEngine._qty 优先取 actual_qty，确保合约盈亏按面值核算。
        """
        o = MagicMock()
        o.actual_qty = 1.0    # 10 张 × ct_val 0.1 = 1.0
        o.fill_sz = "10"      # 张数（合约单位）
        o.filled_quantity = None
        o.quantity = None
        # _qty 优先取 actual_qty
        assert PnlAccountingEngine._qty(o) == pytest.approx(1.0, rel=1e-9)


# ===========================================================================
# 4. 测试 InstrumentCache
# ===========================================================================
class TestInstrumentCache:
    def test_cache_hit(self):
        """首次调用查 API，第二次命中缓存"""
        cache = InstrumentCache()
        cache.clear_cache()

        mock_client = MagicMock()
        mock_client.public.get_instruments = AsyncMock(return_value=[{"ctVal": "0.1"}])

        # 第一次调用 → API 被调用一次
        result1 = asyncio.run(cache.get_instrument("BTC-USDT-SWAP", mock_client))
        assert result1["ctVal"] == pytest.approx(0.1, rel=1e-9)
        assert mock_client.public.get_instruments.call_count == 1

        # 第二次调用 → 缓存命中，API 不被再次调用
        result2 = asyncio.run(cache.get_instrument("BTC-USDT-SWAP", mock_client))
        assert result2["ctVal"] == pytest.approx(0.1, rel=1e-9)
        assert mock_client.public.get_instruments.call_count == 1  # 仍然是 1

    def test_network_error_fallback(self):
        """网络异常返回兜底值 {ctVal: 1.0}，不抛异常"""
        cache = InstrumentCache()
        cache.clear_cache()

        mock_client = MagicMock()
        mock_client.public.get_instruments = AsyncMock(side_effect=Exception("network error"))

        result = asyncio.run(cache.get_instrument("BTC-USDT-SWAP", mock_client))
        assert result["ctVal"] == 1.0


# ===========================================================================
# 5. 测试 OrderManager actual_qty 注入
# ===========================================================================
class TestOrderManagerActualQty:
    @pytest.mark.asyncio
    async def test_add_order_fills_actual_qty(self):
        """add_order 注入 ct_val 并计算 actual_qty = sz × ct_val"""
        mock_cache = MagicMock()
        mock_cache.get_instrument = AsyncMock(return_value={
            "ctVal": 0.1,
            "ctType": "swap",
            "settleCcy": "USDT",
        })
        mgr = OrderManager(MagicMock(), MagicMock(), 1, 1, instrument_cache=mock_cache)

        order = await mgr.add_order("o1", "c1", "BTC-USDT-SWAP", "buy", "50000", "10")

        # actual_qty = 10 × 0.1 = 1.0
        assert order.actual_qty == pytest.approx(1.0, rel=1e-9)
        assert order.ct_val == pytest.approx(0.1, rel=1e-9)
        assert order.ct_type == "swap"
        assert order.settle_ccy == "USDT"


# ===========================================================================
# 6. 测试定时采样任务调用 incremental_update
# ===========================================================================
class TestPnlSampling:
    @pytest.mark.asyncio
    async def test_sampling_calls_incremental_update(self):
        """mock 两个 running 策略，验证 _pnl_sampling_loop 调用 incremental_update"""
        from services.strategy_engine import StrategyEngine

        engine = StrategyEngine()

        # 保存原始状态
        saved_tasks = dict(StrategyEngine._tasks)
        saved_sampling_task = StrategyEngine._pnl_sampling_task

        try:
            # mock 两个 running 策略（task.done() == False）
            task1 = MagicMock()
            task1.done.return_value = False
            task2 = MagicMock()
            task2.done.return_value = False
            strategy1 = MagicMock()
            strategy1.client = MagicMock()
            strategy2 = MagicMock()
            strategy2.client = MagicMock()
            StrategyEngine._tasks.clear()
            StrategyEngine._tasks[1] = (task1, strategy1)
            StrategyEngine._tasks[2] = (task2, strategy2)

            # mock asyncio.sleep：第一次正常返回，第二次抛 CancelledError 退出循环
            sleep_count = {"n": 0}

            async def fake_sleep(seconds):
                sleep_count["n"] += 1
                if sleep_count["n"] >= 2:
                    raise asyncio.CancelledError()

            with patch(
                "services.strategy_engine.pnl_accounting_engine.incremental_update",
                new_callable=AsyncMock,
            ) as mock_incremental, patch(
                "services.strategy_engine.asyncio.sleep", new=fake_sleep
            ):
                await engine._pnl_sampling_loop()

            # 验证 incremental_update 被调用 2 次（每个策略一次）
            assert mock_incremental.call_count == 2
            mock_incremental.assert_any_call(1, strategy1.client)
            mock_incremental.assert_any_call(2, strategy2.client)
        finally:
            StrategyEngine._tasks.clear()
            StrategyEngine._tasks.update(saved_tasks)
            StrategyEngine._pnl_sampling_task = saved_sampling_task


# ===========================================================================
# 7. 测试策略停止时终值写入
# ===========================================================================
class TestStrategyStopFinalPnl:
    @pytest.mark.asyncio
    async def test_stop_calls_incremental_then_final(self):
        """验证 stop_strategy 先 incremental_update 再 strategy.stop()"""
        from services.strategy_engine import StrategyEngine

        engine = StrategyEngine()

        saved_tasks = dict(StrategyEngine._tasks)

        try:
            # mock 一个 running 策略
            task = MagicMock()
            task.done.return_value = False
            strategy = MagicMock()
            strategy.client = MagicMock()
            strategy.ws_client = MagicMock()
            strategy.ws_client.disconnect = AsyncMock()
            StrategyEngine._tasks.clear()
            StrategyEngine._tasks[1] = (task, strategy)

            # 记录调用顺序
            call_order = []

            async def incremental_side_effect(*args, **kwargs):
                call_order.append("incremental_update")

            def stop_side_effect():
                call_order.append("strategy.stop")

            strategy.stop.side_effect = stop_side_effect

            # mock DB（stop_strategy 末尾会更新 instance.status）
            mock_db = MagicMock()
            instance = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = instance

            with patch(
                "services.strategy_engine.pnl_accounting_engine.incremental_update",
                new_callable=AsyncMock,
                side_effect=incremental_side_effect,
            ) as mock_incremental, patch(
                "services.strategy_engine.SessionLocal", return_value=mock_db
            ):
                await engine.stop_strategy(1)

            # 验证 incremental_update 在 strategy.stop() 之前被调用
            assert call_order == ["incremental_update", "strategy.stop"]
            assert mock_incremental.call_count == 1
            mock_incremental.assert_called_once_with(1, strategy.client)
            # 验证策略已从 _tasks 移除
            assert 1 not in StrategyEngine._tasks
            # 验证 DB 状态更新
            assert instance.status == "stopped"
            assert instance.stopped_at is not None
            mock_db.commit.assert_called_once()
        finally:
            StrategyEngine._tasks.clear()
            StrategyEngine._tasks.update(saved_tasks)


# ===========================================================================
# 8. 测试 recompute API 端点
# ===========================================================================
class TestPnlAPI:
    @pytest.mark.asyncio
    async def test_recompute_endpoint(self):
        """测试 POST /api/pnl/recompute/{strategy_id} 返回 PnlSnapshot 字段"""
        from routers.pnl import recompute_pnl
        from services.pnl_accounting_engine import pnl_accounting_engine

        snapshot = PnlSnapshot(
            strategy_instance_id=1,
            realized_pnl=100.0,
            unrealized_pnl=50.0,
            total_pnl=150.0,
            equity=5000.0,
            net_position=2.0,
            avg_buy_price=100.0,
            total_fee=1.0,
            order_count=10,
            recorded_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        mock_client = MagicMock()

        with patch.object(
            pnl_accounting_engine, "_get_client", new_callable=AsyncMock, return_value=mock_client
        ) as mock_get_client, patch.object(
            pnl_accounting_engine, "recompute", new_callable=AsyncMock, return_value=snapshot
        ) as mock_recompute:
            result = await recompute_pnl(
                strategy_id=1,
                request=MagicMock(),
                db=MagicMock(),
                user=MagicMock(),
            )

        # 验证 _get_client 和 recompute 被调用
        mock_get_client.assert_awaited_once_with(1)
        mock_recompute.assert_awaited_once_with(1, mock_client)

        # 验证返回的 dict 包含正确的 PnL 字段
        assert result["strategy_instance_id"] == 1
        assert result["realized_pnl"] == pytest.approx(100.0, rel=1e-9)
        assert result["unrealized_pnl"] == pytest.approx(50.0, rel=1e-9)
        assert result["total_pnl"] == pytest.approx(150.0, rel=1e-9)
        assert result["equity"] == pytest.approx(5000.0, rel=1e-9)
        assert result["net_position"] == pytest.approx(2.0, rel=1e-9)
        assert result["avg_buy_price"] == pytest.approx(100.0, rel=1e-9)
        assert result["total_fee"] == pytest.approx(1.0, rel=1e-9)
        assert result["order_count"] == 10
        assert result["recorded_at"] is not None


# ===========================================================================
# 9. 验证 ComposableStrategy 运行时盈亏曲线
# ===========================================================================
class TestComposableStrategyPnl:
    @pytest.mark.asyncio
    async def test_composable_strategy_pnl_via_engine(self):
        """验证 ComposableStrategy 运行时 PnL 由引擎采样覆盖

        ComposableStrategy 不自行核算 PnL，依赖 pnl_accounting_engine.recompute 统一核算。
        构造 4 笔 filled 订单（2 buy + 2 sell），验证引擎正确计算 PnL 并写入 PnlRecord。
        """
        # 2 buy: qty=1.0, px=100, fee=0.1
        buys = [_make_order(i, "buy", 100.0, 1.0, 0.1, actual_qty=1.0) for i in range(1, 3)]
        # 2 sell: qty=1.0, px=120, fee=0.1
        sells = [_make_order(i, "sell", 120.0, 1.0, 0.1, actual_qty=1.0) for i in range(3, 5)]
        orders = buys + sells

        instance = _make_instance(account_id=1, symbol="BTC-USDT")
        mock_db = _make_recompute_mock_db(orders, instance=instance, latest_pnl=None)

        engine = PnlAccountingEngine()
        with patch("services.pnl_accounting_engine.SessionLocal", return_value=mock_db):
            snapshot = await engine.recompute(strategy_instance_id=1, client=None)

        # buy_total = 2 × 1.0 × 100 = 200
        # sell_total = 2 × 1.0 × 120 = 240
        # total_fee = 4 × 0.1 = 0.4
        # total_pnl = 240 - 200 - 0.4 = 39.6
        assert snapshot.total_pnl == pytest.approx(39.6, rel=1e-9)
        # matched_qty = 2, avg_buy_px = 100, avg_sell_px = 120
        # avg_fee_per_unit = 0.4 / 4 = 0.1
        # realized_pnl = 2 × (120-100) - 2 × 0.1 = 40 - 0.2 = 39.8
        assert snapshot.realized_pnl == pytest.approx(39.8, rel=1e-9)
        # unrealized_pnl = total_pnl - realized_pnl = 39.6 - 39.8 = -0.2
        assert snapshot.unrealized_pnl == pytest.approx(-0.2, rel=1e-9)
        # net_position = 2 - 2 = 0
        assert snapshot.net_position == pytest.approx(0.0, abs=1e-12)
        # avg_buy_price = 200 / 2 = 100
        assert snapshot.avg_buy_price == pytest.approx(100.0, rel=1e-9)
        # total_fee = 0.4
        assert snapshot.total_fee == pytest.approx(0.4, rel=1e-9)
        # order_count = 4
        assert snapshot.order_count == 4
        assert isinstance(snapshot, PnlSnapshot)
        # 验证写入 PnlRecord 并提交
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
