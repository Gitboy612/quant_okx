"""网格策略（grid）模拟盘端到端全链路测试。

测试链路：
1. 创建网格策略模板（自定义）
2. 创建策略实例（绑定 demo 账户）
3. 启动策略
4. 验证订单挂出（orders 表有 live 订单）
5. 暂停 / 恢复策略
6. 停止策略（验证订单被撤销）
7. 删除实例

约束：
- 不实际连接 OKX API（通过 mock_okx fixture 自动 patch）
- 无 demo 账户时跳过（pytestmark.skipif）
- 每个测试最多 120s
- 测试后自动清理资源（cleanup_strategy fixture）
"""
import pytest

from conftest_e2e import (
    DEMO_ACCOUNT_ID,
    SKIP_REASON,
    get_builtin_template_id,
    wait_for,
    count_live_orders,
    get_instance_status,
)

pytestmark = [
    pytest.mark.skipif(DEMO_ACCOUNT_ID is None, reason=SKIP_REASON),
    pytest.mark.timeout(120),
]

# 网格策略参数（BTC-USDT 现货，价格区间 40000-50000）
GRID_PARAMS = {
    "upper_price": 50000,
    "lower_price": 40000,
    "grid_count": 10,
    "order_qty": 0.01,
}
GRID_SYMBOL = "BTC-USDT"
GRID_MARKET = "spot"


# ============================================================
# 辅助：创建自定义模板
# ============================================================


def _create_grid_template(test_client, cleanup_strategy, name="E2E网格模板"):
    """创建自定义网格模板，返回 template_id。"""
    resp = test_client.post("/api/strategies/templates", json={
        "name": name,
        "strategy_type": "grid",
        "description": "E2E 测试网格模板",
        "default_params": GRID_PARAMS,
        "param_schema": {},
    })
    assert resp.status_code == 200, f"创建模板失败: {resp.text}"
    data = resp.json()
    tid = data["id"]
    assert tid is not None, "模板 ID 为 None（可能重复逻辑被拦截）"
    cleanup_strategy["templates"].append(tid)
    return tid


def _create_grid_instance(test_client, cleanup_strategy, template_id, account_id, name="E2E网格实例"):
    """创建网格策略实例，返回 instance_id。"""
    resp = test_client.post("/api/strategies/instances", json={
        "template_id": template_id,
        "account_id": account_id,
        "name": name,
        "symbol": GRID_SYMBOL,
        "market_type": GRID_MARKET,
        "params": GRID_PARAMS,
    })
    assert resp.status_code == 200, f"创建实例失败: {resp.text}"
    iid = resp.json()["id"]
    cleanup_strategy["instances"].append(iid)
    return iid


def _start_strategy(test_client, instance_id):
    """启动策略实例。"""
    resp = test_client.post(f"/api/strategies/instances/{instance_id}/start")
    assert resp.status_code == 200, f"启动策略失败: {resp.text}"


def _stop_strategy(test_client, instance_id):
    """停止策略实例。"""
    resp = test_client.post(f"/api/strategies/instances/{instance_id}/stop")
    assert resp.status_code == 200, f"停止策略失败: {resp.text}"


# ============================================================
# 测试用例
# ============================================================


def test_grid_create_template(test_client, cleanup_strategy):
    """测试创建网格策略模板。"""
    tid = _create_grid_template(test_client, cleanup_strategy, name="E2E_创建模板测试")

    # 验证模板存在
    resp = test_client.get("/api/strategies/templates")
    assert resp.status_code == 200
    templates = resp.json()
    assert any(t["id"] == tid for t in templates), "创建的模板不在列表中"


def test_grid_create_instance(test_client, cleanup_strategy, demo_account_id):
    """测试创建策略实例（绑定 demo 账户）。"""
    tid = _create_grid_template(test_client, cleanup_strategy)
    iid = _create_grid_instance(test_client, cleanup_strategy, tid, demo_account_id)

    # 验证实例存在
    resp = test_client.get("/api/strategies/instances")
    assert resp.status_code == 200
    instances = resp.json()
    assert any(i["id"] == iid for i in instances), "创建的实例不在列表中"

    # 验证实例绑定到 demo 账户
    inst = next(i for i in instances if i["id"] == iid)
    assert inst["account_id"] == demo_account_id
    assert inst["strategy_type"] == "grid"
    assert inst["symbol"] == GRID_SYMBOL


def test_grid_start_and_verify_orders(test_client, cleanup_strategy, demo_account_id):
    """测试启动策略并验证订单挂出。"""
    tid = _create_grid_template(test_client, cleanup_strategy)
    iid = _create_grid_instance(test_client, cleanup_strategy, tid, demo_account_id)

    _start_strategy(test_client, iid)

    # 验证状态变为 running
    wait_for(
        lambda: get_instance_status(iid) == "running",
        timeout=15, desc="策略状态变为 running"
    )

    # 等待订单挂出（mock 下单立即返回，但后台任务需要时间处理）
    wait_for(
        lambda: count_live_orders(iid) > 0,
        timeout=30, desc="live 订单出现"
    )
    assert count_live_orders(iid) > 0, "启动后 orders 表无 live 订单"

    # 停止策略以清理
    _stop_strategy(test_client, iid)


def test_grid_pause_resume(test_client, cleanup_strategy, demo_account_id):
    """测试暂停/恢复策略。"""
    tid = _create_grid_template(test_client, cleanup_strategy)
    iid = _create_grid_instance(test_client, cleanup_strategy, tid, demo_account_id)

    _start_strategy(test_client, iid)
    wait_for(lambda: get_instance_status(iid) == "running", timeout=15, desc="策略 running")

    # 暂停
    resp = test_client.post(f"/api/strategies/instances/{iid}/pause")
    assert resp.status_code == 200, f"暂停失败: {resp.text}"
    wait_for(lambda: get_instance_status(iid) == "paused", timeout=10, desc="策略 paused")

    # 恢复
    resp = test_client.post(f"/api/strategies/instances/{iid}/resume")
    assert resp.status_code == 200, f"恢复失败: {resp.text}"
    wait_for(lambda: get_instance_status(iid) == "running", timeout=10, desc="策略恢复 running")

    _stop_strategy(test_client, iid)


def test_grid_stop_verifies_orders_canceled(test_client, cleanup_strategy, demo_account_id):
    """测试停止策略后订单被撤销。"""
    tid = _create_grid_template(test_client, cleanup_strategy)
    iid = _create_grid_instance(test_client, cleanup_strategy, tid, demo_account_id)

    _start_strategy(test_client, iid)
    wait_for(lambda: get_instance_status(iid) == "running", timeout=15, desc="策略 running")
    wait_for(lambda: count_live_orders(iid) > 0, timeout=30, desc="live 订单出现")

    live_before = count_live_orders(iid)
    assert live_before > 0, "停止前应有 live 订单"

    _stop_strategy(test_client, iid)

    # 验证状态变为 stopped
    wait_for(lambda: get_instance_status(iid) == "stopped", timeout=10, desc="策略 stopped")

    # 验证 live 订单被撤销（status 不再是 live）
    live_after = count_live_orders(iid)
    assert live_after == 0, f"停止后仍有 {live_after} 笔 live 订单（应全部撤销）"


def test_grid_delete_instance(test_client, cleanup_strategy, demo_account_id):
    """测试删除策略实例。"""
    tid = _create_grid_template(test_client, cleanup_strategy)
    iid = _create_grid_instance(test_client, cleanup_strategy, tid, demo_account_id)

    # 删除实例
    resp = test_client.delete(f"/api/strategies/instances/{iid}")
    assert resp.status_code == 200, f"删除失败: {resp.text}"

    # 验证实例不再存在（从 cleanup 列表移除，避免重复删除）
    if iid in cleanup_strategy["instances"]:
        cleanup_strategy["instances"].remove(iid)

    resp = test_client.get("/api/strategies/instances")
    instances = resp.json()
    assert not any(i["id"] == iid for i in instances), "删除后实例仍在列表中"


def test_grid_full_lifecycle(test_client, cleanup_strategy, demo_account_id):
    """网格策略全生命周期：创建 → 启动 → 验证订单 → 暂停 → 恢复 → 停止 → 删除。"""
    # 1. 创建模板和实例
    tid = _create_grid_template(test_client, cleanup_strategy, name="E2E_全生命周期")
    iid = _create_grid_instance(test_client, cleanup_strategy, tid, demo_account_id, name="E2E_全生命周期实例")

    # 2. 启动
    _start_strategy(test_client, iid)
    wait_for(lambda: get_instance_status(iid) == "running", timeout=15, desc="策略 running")

    # 3. 验证订单
    wait_for(lambda: count_live_orders(iid) > 0, timeout=30, desc="live 订单出现")
    assert count_live_orders(iid) > 0

    # 4. 暂停
    test_client.post(f"/api/strategies/instances/{iid}/pause")
    wait_for(lambda: get_instance_status(iid) == "paused", timeout=10, desc="策略 paused")

    # 5. 恢复
    test_client.post(f"/api/strategies/instances/{iid}/resume")
    wait_for(lambda: get_instance_status(iid) == "running", timeout=10, desc="策略恢复 running")

    # 6. 停止
    _stop_strategy(test_client, iid)
    wait_for(lambda: get_instance_status(iid) == "stopped", timeout=10, desc="策略 stopped")
    assert count_live_orders(iid) == 0, "停止后应无 live 订单"

    # 7. 删除
    resp = test_client.delete(f"/api/strategies/instances/{iid}")
    assert resp.status_code == 200
    if iid in cleanup_strategy["instances"]:
        cleanup_strategy["instances"].remove(iid)
