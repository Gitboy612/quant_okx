"""PnL 核算一致性端到端测试。

测试链路：
1. 启动网格策略
2. 等待 PnL 快照写入（最多 60s）
3. 查询 /api/pnl 验证记录存在
4. 验证 realized_pnl + unrealized_pnl ≈ total_pnl（容差 0.01）
5. 验证 equity 字段非零

约束：
- 不实际连接 OKX API（通过 mock_okx fixture 自动 patch）
- 无 demo 账户时跳过
- 每个测试最多 120s
- 测试后自动清理资源
"""
import pytest

from database import SessionLocal
from models.order import Order
from models.pnl import PnlRecord
from conftest_e2e import (
    DEMO_ACCOUNT_ID,
    SKIP_REASON,
    wait_for,
    get_instance_status,
    get_latest_pnl,
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


# ============================================================
# 辅助函数
# ============================================================


def _setup_grid_strategy(test_client, cleanup_strategy, account_id, name="E2E_PnL"):
    """创建并启动网格策略，返回 instance_id。"""
    resp = test_client.post("/api/strategies/templates", json={
        "name": name + "_模板",
        "strategy_type": "grid",
        "description": "PnL 测试模板",
        "default_params": GRID_PARAMS,
        "param_schema": {},
    })
    assert resp.status_code == 200
    tid = resp.json()["id"]
    cleanup_strategy["templates"].append(tid)

    resp = test_client.post("/api/strategies/instances", json={
        "template_id": tid,
        "account_id": account_id,
        "name": name + "_实例",
        "symbol": GRID_SYMBOL,
        "market_type": "spot",
        "params": GRID_PARAMS,
    })
    assert resp.status_code == 200
    iid = resp.json()["id"]
    cleanup_strategy["instances"].append(iid)

    resp = test_client.post(f"/api/strategies/instances/{iid}/start")
    assert resp.status_code == 200, f"启动失败: {resp.text}"

    wait_for(lambda: get_instance_status(iid) == "running", timeout=15, desc="策略 running")
    wait_for(lambda: count_live_orders(iid) > 0, timeout=30, desc="live 订单出现")
    return iid


def _simulate_order_fill(instance_id: int):
    """模拟订单成交：将第一笔 live 买单更新为 filled 状态。"""
    db = SessionLocal()
    try:
        order = db.query(Order).filter(
            Order.strategy_instance_id == instance_id,
            Order.status == "live",
            Order.side == "buy",
        ).first()
        if order:
            order.status = "filled"
            order.state = "filled"
            order.fill_px = order.price
            order.fill_sz = order.quantity
            order.fee = 0.0
            order.pnl_accounted = False
            db.commit()
        return order.id if order else None
    finally:
        db.close()


def _trigger_pnl_recompute(test_client, instance_id: int):
    """调用 /api/pnl/recompute 触发 PnL 全量核算。"""
    resp = test_client.post(f"/api/pnl/recompute/{instance_id}")
    assert resp.status_code == 200, f"PnL recompute 失败: {resp.text}"
    return resp.json()


# ============================================================
# 测试用例
# ============================================================


def test_pnl_record_exists_after_recompute(test_client, cleanup_strategy, demo_account_id):
    """启动网格策略 → 模拟成交 → 触发 recompute → 验证 PnlRecord 存在。"""
    iid = _setup_grid_strategy(test_client, cleanup_strategy, demo_account_id)

    # 模拟订单成交
    _simulate_order_fill(iid)

    # 触发 PnL 核算
    _trigger_pnl_recompute(test_client, iid)

    # 验证 PnlRecord 存在
    pnl = get_latest_pnl(iid)
    assert pnl is not None, "recompute 后无 PnlRecord"

    # 停止策略
    test_client.post(f"/api/strategies/instances/{iid}/stop")


def test_pnl_realized_plus_unrealized_equals_total(test_client, cleanup_strategy, demo_account_id):
    """验证 realized_pnl + unrealized_pnl ≈ total_pnl（容差 0.01）。"""
    iid = _setup_grid_strategy(test_client, cleanup_strategy, demo_account_id, name="E2E_PnL一致性")

    _simulate_order_fill(iid)
    _trigger_pnl_recompute(test_client, iid)

    pnl = get_latest_pnl(iid)
    assert pnl is not None, "无 PnlRecord"

    realized = pnl.realized_pnl or 0
    unrealized = pnl.unrealized_pnl or 0
    total = pnl.total_pnl or 0

    diff = abs((realized + unrealized) - total)
    assert diff <= 0.01, (
        f"PnL 不一致: realized={realized} + unrealized={unrealized} = {realized + unrealized}, "
        f"total={total}, 差异={diff} > 0.01"
    )

    test_client.post(f"/api/strategies/instances/{iid}/stop")


def test_pnl_equity_nonzero(test_client, cleanup_strategy, demo_account_id):
    """验证 equity 字段非零。"""
    iid = _setup_grid_strategy(test_client, cleanup_strategy, demo_account_id, name="E2E_PnL_Equity")

    _simulate_order_fill(iid)
    _trigger_pnl_recompute(test_client, iid)

    pnl = get_latest_pnl(iid)
    assert pnl is not None, "无 PnlRecord"

    # equity 来自 mock get_balance 的 totalEq=10000
    assert pnl.equity is not None, "equity 为 None"
    assert pnl.equity != 0, f"equity 为零（应来自余额 totalEq=10000）: {pnl.equity}"

    # 也通过 API 验证
    resp = test_client.get(f"/api/pnl?strategy_instance_id={iid}")
    assert resp.status_code == 200
    records = resp.json()
    assert len(records) > 0, "/api/pnl 返回空列表"
    assert records[0]["equity"] is not None
    assert records[0]["equity"] != 0, f"/api/pnl equity 为零: {records[0]['equity']}"

    test_client.post(f"/api/strategies/instances/{iid}/stop")
