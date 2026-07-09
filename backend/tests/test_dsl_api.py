"""DSL REST API 路由测试。

覆盖 Task 13 实现的两个端点：
- GET  /api/dsl/blocks    列出所有可用积木
- POST /api/dsl/validate  静态校验 DSL 配置

测试方式：FastAPI TestClient。DSL 端点无数据库/鉴权依赖，
为避免 main.py 导入副作用（数据库、strategy_engine 等），这里构建
仅注册 dsl 路由的独立测试 app，与现有 DSL 测试避免 main.py 的风格一致。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.dsl import router as dsl_router


app = FastAPI()
app.include_router(dsl_router)
client = TestClient(app)


# ============================================================
# 合法 DSL 配置（用户示例：单边上涨暂停-恢复）
# ============================================================

VALID_CONFIG = {
    "version": "1.0",
    "base_strategy": {
        "kind": "grid",
        "params": {
            "upper_price": 50000,
            "lower_price": 40000,
            "grid_count": 10,
            "order_qty": 0.01,
            "symbol": "BTC-USDT",
        },
    },
    "rules": [
        {
            "name": "单边上涨暂停",
            "when": {
                "mode": "condition",
                "condition": {
                    "kind": "gt",
                    "args": {
                        "indicator": {
                            "kind": "price_change_pct",
                            "args": {"window": "1h", "symbol": "BTC-USDT"},
                        },
                        "threshold": 0.05,
                    },
                },
            },
            "then": [{"kind": "pause_orders"}, {"kind": "hold_position"}],
            "recover_when": {
                "mode": "condition",
                "condition": {
                    "kind": "abs_lt",
                    "args": {
                        "indicator": {
                            "kind": "price_change_pct",
                            "args": {"window": "1h", "symbol": "BTC-USDT"},
                        },
                        "threshold": 0.05,
                    },
                },
            },
            "recover_then": [
                {"kind": "rebalance_position", "args": {"mode": "to_theoretical"}},
                {"kind": "resume_orders"},
            ],
        }
    ],
}


# ============================================================
# GET /api/dsl/blocks
# ============================================================


def test_list_blocks_returns_all_categories():
    """GET /api/dsl/blocks 返回 5 个类别，每个均为列表。"""
    resp = client.get("/api/dsl/blocks")
    assert resp.status_code == 200
    data = resp.json()
    expected_keys = {
        "indicators",
        "conditions",
        "actions",
        "events",
        "base_strategies",
    }
    assert set(data.keys()) == expected_keys
    for key in expected_keys:
        assert isinstance(data[key], list), f"{key} 应为列表"
        assert len(data[key]) > 0, f"{key} 不应为空"


def test_list_blocks_contains_p0_indicators():
    """返回的 indicators 含 price_change_pct / rsi / position_qty 等 P0 指标。"""
    resp = client.get("/api/dsl/blocks")
    assert resp.status_code == 200
    indicators = resp.json()["indicators"]
    kinds = {b["kind"] for b in indicators}
    for p0 in ("price_change_pct", "rsi", "position_qty"):
        assert p0 in kinds, f"缺少 P0 指标: {p0}"
    # 元数据字段完整
    sample = next(b for b in indicators if b["kind"] == "rsi")
    for field in ("kind", "category", "description", "param_schema", "output_type", "priority"):
        assert field in sample, f"指标元数据缺少字段: {field}"


def test_list_blocks_contains_p0_actions():
    """返回的 actions 含 pause_orders / resume_orders / rebalance_position 等 P0 动作。"""
    resp = client.get("/api/dsl/blocks")
    assert resp.status_code == 200
    actions = resp.json()["actions"]
    kinds = {b["kind"] for b in actions}
    for p0 in ("pause_orders", "resume_orders", "rebalance_position"):
        assert p0 in kinds, f"缺少 P0 动作: {p0}"


# ============================================================
# POST /api/dsl/validate
# ============================================================


def test_validate_valid_config():
    """POST /api/dsl/validate 传入合法 DSL 配置，返回 valid=true, errors=[]。"""
    resp = client.post("/api/dsl/validate", json=VALID_CONFIG)
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["errors"] == []


def test_validate_invalid_config_unknown_kind():
    """传入含未知 action kind 的配置，返回 valid=false，errors 含 UNKNOWN_KIND。"""
    config = {
        "version": "1.0",
        "base_strategy": {
            "kind": "grid",
            "params": {
                "upper_price": 50000,
                "lower_price": 40000,
                "grid_count": 10,
                "order_qty": 0.01,
                "symbol": "BTC-USDT",
            },
        },
        "rules": [
            {
                "name": "未知动作",
                "when": {
                    "mode": "condition",
                    "condition": {
                        "kind": "gt",
                        "args": {
                            "indicator": {
                                "kind": "price_change_pct",
                                "args": {"window": "1h", "symbol": "BTC-USDT"},
                            },
                            "threshold": 0.05,
                        },
                    },
                },
                "then": [{"kind": "nonexistent_action_kind"}],
            }
        ],
    }
    resp = client.post("/api/dsl/validate", json=config)
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    codes = [e["code"] for e in data["errors"]]
    assert "UNKNOWN_KIND" in codes
    # 每条错误应包含 layer/code/message/path 四字段
    for err in data["errors"]:
        assert set(err.keys()) == {"layer", "code", "message", "path"}


def test_validate_invalid_config_structure():
    """传入结构错误（version="2.0"），返回 valid=false（structure 层校验失败）。"""
    config = {
        "version": "2.0",
        "base_strategy": {
            "kind": "grid",
            "params": {
                "upper_price": 50000,
                "lower_price": 40000,
                "grid_count": 10,
                "order_qty": 0.01,
                "symbol": "BTC-USDT",
            },
        },
        "rules": [],
    }
    resp = client.post("/api/dsl/validate", json=config)
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert len(data["errors"]) > 0
    assert any(e["layer"] == "structure" for e in data["errors"])
