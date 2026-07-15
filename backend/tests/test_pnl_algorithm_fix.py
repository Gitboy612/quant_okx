"""盈亏算法与策略监控修复 spec 的单元测试。

覆盖：
- OrderManager 净持仓计算（买入累加/卖出扣减/恢复）
- OrderManager 手续费查询
- OrderManager 线程安全（不再使用 threading，改用 asyncio.create_task）
- PnL Summary 取最新值（unrealized 不跨记录求和、按策略聚合、total_pnl 求和）
- BaseStrategy PnL 采样降频（_should_record_pnl）
- 停止时保留未实现盈亏（record_final_pnl）
- grid_idx=0 边界防护源码存在性检查

导入风格参考 conftest.py 与 test_dsl_executor.py：顶部注入 backend 根目录到 sys.path。
"""
import sys
import os
import asyncio
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.order_manager import OrderManager, OrderInfo
from routers.pnl import get_pnl_summary
from models.pnl import PnlRecord
from strategies.base_strategy import BaseStrategy


# ---------------------------------------------------------------------------
# 最小化 BaseStrategy 子类（BaseStrategy 是 ABC，需实现 abstractmethod）
# ---------------------------------------------------------------------------
class _MinimalStrategy(BaseStrategy):
    async def execute(self):
        pass

    async def validate_params(self) -> bool:
        return True


def _make_strategy(**overrides):
    """构造一个最小化策略实例，依赖全部 mock。"""
    kwargs = dict(
        instance_id=1,
        params={},
        client=MagicMock(),
        db_session_factory=MagicMock(),
        account_id=1,
    )
    kwargs.update(overrides)
    return _MinimalStrategy(**kwargs)


# ===========================================================================
# 1. OrderManager 净持仓计算
# ===========================================================================
class TestOrderManagerNetPosition:
    def _make_mgr(self):
        return OrderManager(MagicMock(), MagicMock(), 1, 1)

    def test_net_position_buy_accumulation(self):
        """连续两笔买单成交：net_position=0.03，avg_buy_price=40666.67"""
        mgr = self._make_mgr()

        asyncio.run(mgr.add_order("o1", "c1", "BTC-USDT", "buy", "40000", "0.01"))
        mgr.update_order("o1", state="filled", fillPx="40000", fillSz="0.01")

        asyncio.run(mgr.add_order("o2", "c2", "BTC-USDT", "buy", "41000", "0.02"))
        mgr.update_order("o2", state="filled", fillPx="41000", fillSz="0.02")

        net_pos, avg_price = mgr.get_position_summary()
        assert net_pos == pytest.approx(0.03, rel=1e-9)
        expected_avg = (0.01 * 40000 + 0.02 * 41000) / 0.03  # 40666.67
        assert avg_price == pytest.approx(expected_avg, rel=1e-3)

    def test_net_position_sell_reduces(self):
        """先买 0.01@40000，再卖 0.01@41000：net_position=0，均价保持 40000"""
        mgr = self._make_mgr()

        asyncio.run(mgr.add_order("o1", "c1", "BTC-USDT", "buy", "40000", "0.01"))
        mgr.update_order("o1", state="filled", fillPx="40000", fillSz="0.01")

        asyncio.run(mgr.add_order("o2", "c2", "BTC-USDT", "sell", "41000", "0.01"))
        mgr.update_order("o2", state="filled", fillPx="41000", fillSz="0.01")

        net_pos, avg_price = mgr.get_position_summary()
        assert net_pos == pytest.approx(0.0, abs=1e-12)
        # 卖单不改变加权平均买入价
        assert avg_price == pytest.approx(40000.0, rel=1e-9)

    def test_position_restore(self):
        """restore_position(0.5, 45000) 后 get_position_summary 返回 (0.5, 45000)"""
        mgr = self._make_mgr()
        mgr.restore_position(0.5, 45000)
        net_pos, avg_price = mgr.get_position_summary()
        assert net_pos == 0.5
        assert avg_price == 45000


# ===========================================================================
# 2. OrderManager 手续费查询
# ===========================================================================
class TestOrderManagerFee:
    def test_get_order_fee(self):
        """add_order 后通过 update_order 设置 fee=0.5，get_order_fee 返回 0.5"""
        mgr = OrderManager(MagicMock(), MagicMock(), 1, 1)
        asyncio.run(mgr.add_order("o1", "c1", "BTC-USDT", "buy", "40000", "0.01"))
        mgr.update_order("o1", fee="0.5")
        assert mgr.get_order_fee("o1") == pytest.approx(0.5)

    def test_get_order_fee_missing(self):
        """不存在的 ordId 返回 0.0"""
        mgr = OrderManager(MagicMock(), MagicMock(), 1, 1)
        assert mgr.get_order_fee("nonexistent") == 0.0


# ===========================================================================
# 3. OrderManager 线程安全
# ===========================================================================
class TestOrderManagerThreading:
    def test_async_persist_no_threading(self):
        """验证 _async_persist 不再使用 threading，而是用 asyncio.create_task。

        - 源码中不含 `import threading`
        - 在有 running loop 上下文中调用 _async_persist，asyncio.create_task 被调用
          且不会回退到同步 _persist_to_db
        """
        import services.order_manager as om_module
        source = open(om_module.__file__, encoding="utf-8").read()
        assert "import threading" not in source, "order_manager.py 不应再使用 threading"

        mgr = OrderManager(MagicMock(), MagicMock(), 1, 1)
        # 模拟有 running loop 的场景
        with patch.object(asyncio, "get_running_loop", return_value=MagicMock()), \
             patch.object(asyncio, "create_task") as mock_create_task, \
             patch.object(mgr, "_persist_to_db") as mock_persist:
            mgr._async_persist(OrderInfo(ordId="x"))
            # 应通过 asyncio.create_task 调度
            assert mock_create_task.called, "应调用 asyncio.create_task"
            # create_task 成功后不应回退到同步持久化
            assert not mock_persist.called, "create_task 成功时不应同步调用 _persist_to_db"

    def test_async_persist_fallback_sync(self):
        """无 running loop 时回退到同步持久化。"""
        mgr = OrderManager(MagicMock(), MagicMock(), 1, 1)
        with patch.object(asyncio, "get_running_loop", side_effect=RuntimeError), \
             patch.object(mgr, "_persist_to_db") as mock_persist:
            mgr._async_persist(OrderInfo(ordId="x"))
            assert mock_persist.called, "无 event loop 时应同步调用 _persist_to_db"

    def test_async_persist_holds_task_reference(self):
        """验证 _async_persist 将 task 引用加入 _pending_persist_tasks 防止 GC。"""
        mgr = OrderManager(MagicMock(), MagicMock(), 1, 1)
        fake_task = MagicMock()
        fake_task.add_done_callback = MagicMock()
        with patch.object(asyncio, "get_running_loop", return_value=MagicMock()), \
             patch.object(asyncio, "create_task", return_value=fake_task):
            mgr._async_persist(OrderInfo(ordId="x"))
            assert fake_task in mgr._pending_persist_tasks, "task 引用应被持有防止 GC"
            fake_task.add_done_callback.assert_called_once()


# ===========================================================================
# 4. PnL Summary 取最新值
# ===========================================================================
class TestPnlSummary:
    def _make_records_same_strategy(self):
        """3 条同策略记录，realized=10/20/30，unrealized=5/15/25，最新在前。"""
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        return [
            PnlRecord(
                id=3, account_id=1, strategy_instance_id=1, equity=1000,
                unrealized_pnl=25, realized_pnl=30, total_pnl=55,
                is_final=False, recorded_at=base + timedelta(seconds=20),
            ),
            PnlRecord(
                id=2, account_id=1, strategy_instance_id=1, equity=990,
                unrealized_pnl=15, realized_pnl=20, total_pnl=35,
                is_final=False, recorded_at=base + timedelta(seconds=10),
            ),
            PnlRecord(
                id=1, account_id=1, strategy_instance_id=1, equity=980,
                unrealized_pnl=5, realized_pnl=10, total_pnl=15,
                is_final=False, recorded_at=base,
            ),
        ]

    def _make_mock_db(self, records):
        """构造 mock db，使 query().order_by().limit().all() 返回 records。"""
        mock_db = MagicMock()
        # account_id=None 时不会调用 filter，链路：query().order_by().limit().all()
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = records
        return mock_db

    def test_summary_unrealized_not_summed(self):
        """unrealized 取最新值 25，不是 5+15+25=45"""
        records = self._make_records_same_strategy()
        mock_db = self._make_mock_db(records)
        result = get_pnl_summary(account_id=None, strategy_instance_id=None, db=mock_db, user=MagicMock())
        assert result["total_unrealized_pnl"] == 25
        assert result["total_unrealized_pnl"] != 45

    def test_summary_by_strategy(self):
        """两条记录分属不同 strategy_instance_id，by_strategy 长度为 2"""
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        records = [
            PnlRecord(
                id=2, account_id=1, strategy_instance_id=10, equity=1000,
                unrealized_pnl=25, realized_pnl=30, total_pnl=55,
                is_final=False, recorded_at=base + timedelta(seconds=10),
            ),
            PnlRecord(
                id=1, account_id=1, strategy_instance_id=20, equity=900,
                unrealized_pnl=10, realized_pnl=15, total_pnl=25,
                is_final=False, recorded_at=base,
            ),
        ]
        mock_db = self._make_mock_db(records)
        result = get_pnl_summary(account_id=None, strategy_instance_id=None, db=mock_db, user=MagicMock())
        assert len(result["by_strategy"]) == 2

    def test_summary_total_pnl(self):
        """total_pnl == total_realized + total_unrealized == 30 + 25 == 55"""
        records = self._make_records_same_strategy()
        mock_db = self._make_mock_db(records)
        result = get_pnl_summary(account_id=None, strategy_instance_id=None, db=mock_db, user=MagicMock())
        assert result["total_realized_pnl"] == 30
        assert result["total_unrealized_pnl"] == 25
        assert result["total_pnl"] == 30 + 25
        assert result["total_pnl"] == 55


# ===========================================================================
# 5. PnL 采样降频
# ===========================================================================
class TestShouldRecordPnl:
    def test_should_record_first_time(self):
        """首次调用（_last_pnl_record_ts=0）返回 True"""
        strategy = _make_strategy()
        strategy._last_pnl_record_ts = 0.0
        assert strategy._should_record_pnl(total_pnl=100.0) is True

    def test_should_record_within_interval(self):
        """10 秒前记录过，total_pnl 与上次接近（变化<1%），返回 False"""
        strategy = _make_strategy()
        strategy._last_pnl_record_ts = time.time() - 10
        strategy._last_pnl_total = 100.0
        # total_pnl 与上次相同，变化 0% < 1%
        assert strategy._should_record_pnl(total_pnl=100.0) is False

    def test_should_record_change_exceeds_threshold(self):
        """10 秒前记录过，但 total_pnl 从 100 变为 200（变化 100% > 1%），返回 True"""
        strategy = _make_strategy()
        strategy._last_pnl_record_ts = time.time() - 10
        strategy._last_pnl_total = 100.0
        assert strategy._should_record_pnl(total_pnl=200.0) is True

    def test_should_record_after_interval(self):
        """61 秒前记录过（超过 60s 间隔），返回 True"""
        strategy = _make_strategy()
        strategy._last_pnl_record_ts = time.time() - 61
        strategy._last_pnl_total = 100.0
        assert strategy._should_record_pnl(total_pnl=100.0) is True


# ===========================================================================
# 6. 停止时保留未实现盈亏
# ===========================================================================
class TestRecordFinalPnl:
    def test_record_final_pnl_preserves_unrealized(self):
        """record_final_pnl 写入的 PnlRecord: is_final=True 且 unrealized_pnl=15（非 0）"""
        mock_db = MagicMock()
        # latest 记录：unrealized=15, realized=30, equity=1000
        mock_latest = MagicMock()
        mock_latest.realized_pnl = 30
        mock_latest.equity = 1000
        mock_latest.unrealized_pnl = 15
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_latest

        db_session_factory = MagicMock(return_value=mock_db)
        strategy = _make_strategy(db_session_factory=db_session_factory)

        strategy.record_final_pnl()

        # 捕获所有 db.add 调用的参数，找到 is_final=True 的 PnlRecord
        added_records = [call.args[0] for call in mock_db.add.call_args_list]
        final_records = [r for r in added_records if getattr(r, "is_final", False) is True]
        assert len(final_records) == 1, "应仅有一条 is_final=True 的 PnL 记录"
        final_record = final_records[0]
        assert final_record.is_final is True
        # unrealized_pnl 保留最新值 15，不再被清零
        assert final_record.unrealized_pnl == 15
        assert final_record.unrealized_pnl != 0


# ===========================================================================
# 7. grid_idx=0 边界防护
# ===========================================================================
def test_grid_idx_zero_boundary_exists():
    """验证 grid_strategy.py 包含 grid_idx=0 边界防护代码"""
    import strategies.grid_strategy as gs
    source = open(gs.__file__, encoding="utf-8").read()
    assert "grid_idx == 0" in source
    assert "order_warn" in source
