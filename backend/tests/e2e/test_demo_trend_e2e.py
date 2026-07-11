"""趋势策略（trend）模拟盘端到端全链路测试。

测试链路：
1. 创建趋势策略模板
2. 创建策略实例（绑定 demo 账户）
3. 启动策略
4. 暂停 / 恢复策略
5. 停止策略

约束：
- 不实际连接 OKX API（通过 mock_okx fixture 自动 patch）
- 无 demo 账户时跳过
- 每个测试最多 120s
- 测试后自动清理资源
"""
import pytest

from conftest_e2e import (
    DEMO_ACCOUNT_ID,
    SKIP_REASON,
    wait_for,
    get_instance_status,
)

pytestmark = [
    pytest.mark.skipif(DEMO_ACCOUNT_ID is None, reason=SKIP_REASON),
    pytest.mark.timeout(120),
]

# 趋势策略参数（BTC-USDT-SWAP 合约，双均线交叉）
TREND_PARAMS = {
    "fast_ma_period": 5,
    "slow_ma_period": 20,
    "order_qty": 0.01,
}
TREND_SYMBOL = "BTC-USDT-SWAP"
TREND_MARKET = "swap"


# ============================================================
# 辅助函数
# ============================================================


def _create_trend_template(test_client, cleanup_strategy, name="E2E趋势模板"):
    """创建自定义趋势模板，返回 template_id。"""
    resp = test_client.post("/api/strategies/templates", json={
        "name": name,
        "strategy_type": "trend",
        "description": "E2E 测试趋势模板",
        "default_params": TREND_PARAMS,
        "param_schema": {},
    })
    assert resp.status_code == 200, f"创建模板失败: {resp.text}"
    data = resp.json()
    tid = data["id"]
    assert tid is not None, "模板 ID 为 None"
    cleanup_strategy["templates"].append(tid)
    return tid


def _create_trend_instance(test_client, cleanup_strategy, template_id, account_id, name="E2E趋势实例"):
    """创建趋势策略实例，返回 instance_id。"""
    resp = test_client.post("/api/strategies/instances", json={
        "template_id": template_id,
        "account_id": account_id,
        "name": name,
        "symbol": TREND_SYMBOL,
        "market_type": TREND_MARKET,
        "params": TREND_PARAMS,
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


def test_trend_create_template(test_client, cleanup_strategy):
    """测试创建趋势策略模板。"""
    tid = _create_trend_template(test_client, cleanup_strategy, name="E2E_趋势创建模板")

    resp = test_client.get("/api/strategies/templates")
    assert resp.status_code == 200
    templates = resp.json()
    assert any(t["id"] == tid and t["strategy_type"] == "trend" for t in templates)


def test_trend_create_instance(test_client, cleanup_strategy, demo_account_id):
    """测试创建趋势策略实例（绑定 demo 账户）。"""
    tid = _create_trend_template(test_client, cleanup_strategy)
    iid = _create_trend_instance(test_client, cleanup_strategy, tid, demo_account_id)

    resp = test_client.get("/api/strategies/instances")
    assert resp.status_code == 200
    instances = resp.json()
    inst = next(i for i in instances if i["id"] == iid)
    assert inst["account_id"] == demo_account_id
    assert inst["strategy_type"] == "trend"
    assert inst["symbol"] == TREND_SYMBOL


def test_trend_start_strategy(test_client, cleanup_strategy, demo_account_id):
    """测试启动趋势策略。"""
    tid = _create_trend_template(test_client, cleanup_strategy)
    iid = _create_trend_instance(test_client, cleanup_strategy, tid, demo_account_id)

    _start_strategy(test_client, iid)

    # 趋势策略 execute() 先调用 validate_params → get_balance → update_status("running")
    wait_for(
        lambda: get_instance_status(iid) == "running",
        timeout=15, desc="趋势策略状态变为 running"
    )
    assert get_instance_status(iid) == "running"

    _stop_strategy(test_client, iid)


def test_trend_pause_resume(test_client, cleanup_strategy, demo_account_id):
    """测试暂停/恢复趋势策略。"""
    tid = _create_trend_template(test_client, cleanup_strategy)
    iid = _create_trend_instance(test_client, cleanup_strategy, tid, demo_account_id)

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


def test_trend_stop_strategy(test_client, cleanup_strategy, demo_account_id):
    """测试停止趋势策略。"""
    tid = _create_trend_template(test_client, cleanup_strategy)
    iid = _create_trend_instance(test_client, cleanup_strategy, tid, demo_account_id)

    _start_strategy(test_client, iid)
    wait_for(lambda: get_instance_status(iid) == "running", timeout=15, desc="策略 running")

    _stop_strategy(test_client, iid)

    wait_for(lambda: get_instance_status(iid) == "stopped", timeout=10, desc="策略 stopped")
    assert get_instance_status(iid) == "stopped"
