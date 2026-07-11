"""WebSocket 推送验证端到端测试。

测试链路：
1. 连接 /ws/dashboard
2. 启动一个策略实例
3. 通过 WebSocket 发送消息触发广播
4. 验证收到策略状态更新消息（最多 30s）
5. 关闭连接

约束：
- 不实际连接 OKX API（通过 mock_okx fixture 自动 patch）
- 无 demo 账户时跳过
- 每个测试最多 120s
- 测试后自动清理资源
"""
import json
import time

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

GRID_PARAMS = {
    "upper_price": 50000,
    "lower_price": 40000,
    "grid_count": 10,
    "order_qty": 0.01,
}
GRID_SYMBOL = "BTC-USDT"


def test_websocket_dashboard_receives_strategy_update(test_client, cleanup_strategy, demo_account_id):
    """连接 /ws/dashboard → 启动策略 → 发送消息 → 验证收到策略状态更新。"""
    # 1. 先创建并启动策略
    resp = test_client.post("/api/strategies/templates", json={
        "name": "E2E_WS_模板",
        "strategy_type": "grid",
        "description": "WebSocket 测试模板",
        "default_params": GRID_PARAMS,
        "param_schema": {},
    })
    assert resp.status_code == 200
    tid = resp.json()["id"]
    cleanup_strategy["templates"].append(tid)

    resp = test_client.post("/api/strategies/instances", json={
        "template_id": tid,
        "account_id": demo_account_id,
        "name": "E2E_WS_实例",
        "symbol": GRID_SYMBOL,
        "market_type": "spot",
        "params": GRID_PARAMS,
    })
    assert resp.status_code == 200
    iid = resp.json()["id"]
    cleanup_strategy["instances"].append(iid)

    # 启动策略
    resp = test_client.post(f"/api/strategies/instances/{iid}/start")
    assert resp.status_code == 200, f"启动失败: {resp.text}"

    # 等待策略进入 running 状态
    wait_for(lambda: get_instance_status(iid) == "running", timeout=15, desc="策略 running")

    # 2. 连接 WebSocket 并验证收到策略状态
    #    /ws/dashboard 的协议：client 发 text → server 广播 running_strategies
    try:
        with test_client.websocket_connect("/ws/dashboard") as ws:
            # 发送消息触发广播
            ws.send_text("ping")

            # 接收广播消息（最多 30s）
            received = False
            start = time.time()
            while time.time() - start < 30:
                try:
                    data = json.loads(ws.receive_text(timeout=5))
                    if data.get("type") == "dashboard":
                        # 验证 running_strategies 包含已启动的策略
                        running_ids = data.get("running_strategies", [])
                        assert iid in running_ids, (
                            f"WebSocket 广播的 running_strategies={running_ids} "
                            f"不包含已启动策略 {iid}"
                        )
                        received = True
                        break
                except Exception:
                    # 超时或解析失败，继续等待
                    ws.send_text("ping")
                    continue

            assert received, "30s 内未收到包含策略状态的 WebSocket 广播消息"
    finally:
        # 停止策略
        try:
            test_client.post(f"/api/strategies/instances/{iid}/stop")
        except Exception:
            pass
