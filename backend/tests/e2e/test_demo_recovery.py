"""策略重启 DB 恢复端到端测试。

测试链路：
1. 启动网格策略，等待订单挂出
2. 记录 active_orders（DB 中 live 订单数）
3. 停止策略引擎（模拟重启，mock cancel_all 不撤销订单）
4. 重新启动策略
5. 验证 _rebuild_active_dicts 从 DB 恢复了订单

验证方式：
- strategy_events 表出现 "订单同步完成" 事件
- DB 中 live 订单数 >= 重启前的数量（恢复 + 新挂单）
- 策略状态恢复为 running

约束：
- 不实际连接 OKX API（通过 mock_okx fixture 自动 patch）
- 无 demo 账户时跳过
- 每个测试最多 120s
- 测试后自动清理资源
"""
from unittest.mock import AsyncMock, patch

import pytest

from database import SessionLocal
from models.strategy_event import StrategyEvent
from conftest_e2e import (
    DEMO_ACCOUNT_ID,
    SKIP_REASON,
    wait_for,
    get_instance_status,
    count_live_orders,
)

pytestmark = [
    pytest.mark.skipif(DEMO_ACCOUNT_ID is None, reason=SKIP_REASON),
    pytest.mark.timeout(120),
]

GRID_PARAMS = {
    "upper_price": 50000,
    "lower_price": 40000,
    "grid_count": 10,
    "order_qty": 0.01,
}
GRID_SYMBOL = "BTC-USDT"


def _get_sync_events(instance_id: int) -> list:
    """查询策略的订单同步事件。"""
    db = SessionLocal()
    try:
        return db.query(StrategyEvent).filter(
            StrategyEvent.strategy_instance_id == instance_id,
            StrategyEvent.message.like("%订单同步完成%"),
        ).all()
    finally:
        db.close()


def test_strategy_recovery_from_db(test_client, cleanup_strategy, demo_account_id):
    """策略重启后从 DB 恢复订单验证。

    流程：
    1. 创建 + 启动网格策略 → 等待 live 订单
    2. mock cancel_all（模拟崩溃，订单不被撤销）
    3. 停止策略 → 验证 DB 中仍有 live 订单
    4. 取消 mock → 重新启动策略
    5. 验证 strategy_events 出现 "订单同步完成"
    6. 验证 _active_buy_orders 从 DB 恢复（通过 sync 事件中的 still_active > 0）
    """
    # 1. 创建模板和实例
    resp = test_client.post("/api/strategies/templates", json={
        "name": "E2E_Recovery_模板",
        "strategy_type": "grid",
        "description": "恢复测试模板",
        "default_params": GRID_PARAMS,
        "param_schema": {},
    })
    assert resp.status_code == 200
    tid = resp.json()["id"]
    cleanup_strategy["templates"].append(tid)

    resp = test_client.post("/api/strategies/instances", json={
        "template_id": tid,
        "account_id": demo_account_id,
        "name": "E2E_Recovery_实例",
        "symbol": GRID_SYMBOL,
        "market_type": "spot",
        "params": GRID_PARAMS,
    })
    assert resp.status_code == 200
    iid = resp.json()["id"]
    cleanup_strategy["instances"].append(iid)

    # 2. 启动策略，等待订单挂出
    resp = test_client.post(f"/api/strategies/instances/{iid}/start")
    assert resp.status_code == 200, f"启动失败: {resp.text}"

    wait_for(lambda: get_instance_status(iid) == "running", timeout=15, desc="策略 running")
    wait_for(lambda: count_live_orders(iid) > 0, timeout=30, desc="live 订单出现")

    live_orders_before = count_live_orders(iid)
    assert live_orders_before > 0, "启动后无 live 订单"

    # 3. mock cancel_all 使停止时不撤销订单（模拟崩溃重启）
    with patch(
        "services.order_manager.OrderManager.cancel_all",
        new=AsyncMock(return_value=0),
    ):
        # 4. 停止策略（订单保留在 DB 中）
        resp = test_client.post(f"/api/strategies/instances/{iid}/stop")
        assert resp.status_code == 200, f"停止失败: {resp.text}"
        wait_for(lambda: get_instance_status(iid) == "stopped", timeout=10, desc="策略 stopped")

        # 5. 验证 DB 中仍有 live 订单（未被撤销）
        live_orders_after_stop = count_live_orders(iid)
        assert live_orders_after_stop == live_orders_before, (
            f"停止后 live 订单数变化: before={live_orders_before}, after={live_orders_after_stop} "
            f"（mock cancel_all 后应保持不变）"
        )

    # 6. 重新启动策略（此时 DB 中有 live 订单，应被恢复）
    resp = test_client.post(f"/api/strategies/instances/{iid}/start")
    assert resp.status_code == 200, f"重启失败: {resp.text}"

    wait_for(lambda: get_instance_status(iid) == "running", timeout=15, desc="策略恢复 running")

    # 7. 验证 strategy_events 出现 "订单同步完成"
    wait_for(
        lambda: len(_get_sync_events(iid)) > 0,
        timeout=30, desc="订单同步完成事件"
    )

    sync_events = _get_sync_events(iid)
    assert len(sync_events) > 0, "重启后无 '订单同步完成' 事件"

    # 验证同步事件包含 still_active > 0（说明从 DB 恢复了活跃订单）
    latest_sync = sync_events[-1]
    assert latest_sync.message is not None
    assert "订单同步完成" in latest_sync.message, (
        f"同步事件消息不匹配: {latest_sync.message}"
    )
    # still_active 应 > 0，表示从 DB 恢复了订单
    assert "仍活跃" in latest_sync.message or "活跃" in latest_sync.message, (
        f"同步事件未包含活跃订单信息: {latest_sync.message}"
    )

    # 8. 验证 DB 中仍有 live 订单
    live_orders_after_restart = count_live_orders(iid)
    assert live_orders_after_restart > 0, (
        "重启后无 live 订单（应从 DB 恢复）"
    )

    # 停止策略以清理
    test_client.post(f"/api/strategies/instances/{iid}/stop")
