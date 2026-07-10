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


# ============================================================
# label / display_template / select 元数据校验（QS-Model 中文化改造）
# ============================================================


EXPECTED_LABELS = {
    "indicators": {
        "price_last": "最新价",
        "price_change_pct": "涨跌幅",
        "rsi": "RSI",
        "position_qty": "持仓数量",
        "position_pnl": "持仓盈亏",
        "account_equity": "账户净值",
        "realized_pnl": "已实现盈亏",
        "unrealized_pnl": "未实现盈亏",
    },
    "conditions": {
        "gt": "大于",
        "lt": "小于",
        "abs_gt": "绝对值大于",
        "abs_lt": "绝对值小于",
        "and": "同时满足",
        "or": "任一满足",
        "not": "取反",
    },
    "actions": {
        "place_order": "下单",
        "cancel_all": "撤销全部",
        "rebalance_position": "调仓",
        "hold_position": "持有不动",
        "pause_orders": "暂停挂单",
        "resume_orders": "恢复挂单",
        "log_event": "记录事件",
    },
    "events": {
        "on_tick": "行情更新",
        "on_order_filled": "订单成交",
        "on_margin_warning": "保证金预警",
        "on_interval": "定时触发",
        "on_strategy_error": "策略异常",
    },
}


def _fetch_blocks():
    """辅助：调用 GET /api/dsl/blocks 并返回 json。"""
    resp = client.get("/api/dsl/blocks")
    assert resp.status_code == 200
    return resp.json()


def test_all_p0_blocks_have_label():
    """所有 P0 积木 list() 输出含 label 字段且与预期中文一致。"""
    data = _fetch_blocks()
    for category, expected in EXPECTED_LABELS.items():
        blocks = {b["kind"]: b for b in data[category]}
        for kind, exp_label in expected.items():
            assert kind in blocks, f"{category} 缺少 P0 积木: {kind}"
            assert "label" in blocks[kind], f"{category}.{kind} 缺少 label 字段"
            assert blocks[kind]["label"] == exp_label, (
                f"{category}.{kind} label 期望 '{exp_label}'，实际 '{blocks[kind]['label']}'"
            )


def test_conditions_have_display_template():
    """所有 P0 条件积木含 display_template 字段（非 None）。"""
    data = _fetch_blocks()
    conditions = {b["kind"]: b for b in data["conditions"]}
    for kind in ("gt", "lt", "abs_gt", "abs_lt", "and", "or", "not"):
        assert kind in conditions, f"缺少条件积木: {kind}"
        dt = conditions[kind].get("display_template")
        assert isinstance(dt, str) and len(dt) > 0, (
            f"condition {kind} display_template 应为非空字符串，实际: {dt!r}"
        )


def test_indicator_blocks_have_no_display_template():
    """非条件类积木 display_template 应为 None（未定义）。"""
    data = _fetch_blocks()
    for ind in data["indicators"]:
        assert ind.get("display_template") is None, (
            f"indicator {ind['kind']} 不应有 display_template"
        )


def _iter_params(block):
    """统一遍历积木 param_schema 中的 (name, schema) 对，兼容扁平与 JSON Schema 嵌套格式。"""
    schema = block.get("param_schema") or {}
    if not isinstance(schema, dict):
        return
    if schema.get("type") == "object" and "properties" in schema:
        for name, sub in (schema.get("properties") or {}).items():
            yield name, sub
    else:
        for name, sub in schema.items():
            yield name, sub


def test_select_params_have_options_and_labels():
    """所有 type=select 的参数必须同时含 options 与 option_labels，且长度一致。"""
    data = _fetch_blocks()
    select_found = 0
    for category in ("indicators", "conditions", "actions", "events"):
        for block in data[category]:
            for name, param in _iter_params(block):
                if not isinstance(param, dict):
                    continue
                if param.get("type") != "select":
                    continue
                select_found += 1
                assert "options" in param, (
                    f"{category}.{block['kind']}.{name} select 缺少 options"
                )
                assert "option_labels" in param, (
                    f"{category}.{block['kind']}.{name} select 缺少 option_labels"
                )
                opts = param["options"]
                labels = param["option_labels"]
                assert isinstance(opts, list) and len(opts) > 0, (
                    f"{category}.{block['kind']}.{name} options 应为非空列表"
                )
                assert len(opts) == len(labels), (
                    f"{category}.{block['kind']}.{name} options/option_labels 长度不一致"
                )
    # 至少应识别到 6 个 select（price_change_pct.window, place_order.side/type,
    # rebalance_position.mode, log_event.level, on_order_filled.side）
    assert select_found >= 6, f"未识别到足够的 select 参数，仅 {select_found} 个"


def test_specific_select_params():
    """关键 select 参数的 options 内容校验。"""
    data = _fetch_blocks()

    # price_change_pct.window
    pcp = next(b for b in data["indicators"] if b["kind"] == "price_change_pct")
    window = pcp["param_schema"]["window"]
    assert window["type"] == "select"
    assert window["options"] == ["1m", "5m", "15m", "1h", "4h", "1d"]
    assert window["option_labels"] == ["1分钟", "5分钟", "15分钟", "1小时", "4小时", "1天"]

    # place_order.side / type
    po = next(b for b in data["actions"] if b["kind"] == "place_order")
    props = po["param_schema"]["properties"]
    assert props["side"]["options"] == ["buy", "sell"]
    assert props["side"]["option_labels"] == ["买入", "卖出"]
    assert props["type"]["options"] == ["market", "limit"]
    assert props["type"]["option_labels"] == ["市价", "限价"]

    # rebalance_position.mode
    rp = next(b for b in data["actions"] if b["kind"] == "rebalance_position")
    mode = rp["param_schema"]["properties"]["mode"]
    assert mode["options"] == ["to_theoretical", "to_target", "from_zero"]
    assert mode["option_labels"] == ["到理论持仓", "到目标持仓", "从零开始"]

    # log_event.level
    le = next(b for b in data["actions"] if b["kind"] == "log_event")
    level = le["param_schema"]["properties"]["level"]
    assert level["options"] == ["info", "warn", "error", "critical"]
    assert level["option_labels"] == ["信息", "警告", "错误", "严重"]

    # on_order_filled.side
    oof = next(b for b in data["events"] if b["kind"] == "on_order_filled")
    side = oof["param_schema"]["side"]
    assert side["type"] == "select"
    assert side["options"] == ["buy", "sell"]
    assert side["option_labels"] == ["买入", "卖出"]


def test_symbol_params_have_label():
    """所有 symbol 类参数应有 label='交易对'。"""
    data = _fetch_blocks()
    checked = 0
    for category in ("indicators", "actions", "events"):
        for block in data[category]:
            for name, param in _iter_params(block):
                if name == "symbol" and isinstance(param, dict):
                    checked += 1
                    assert param.get("label") == "交易对", (
                        f"{category}.{block['kind']}.symbol label 期望 '交易对'，"
                        f"实际 '{param.get('label')}'"
                    )
    # 至少 8 个 symbol 参数（indicators 5 个 + actions 4 个 + events 3 个，部分去重）
    assert checked >= 8, f"仅校验到 {checked} 个 symbol 参数"


def test_extra_units_and_labels():
    """个别参数的 unit / label 校验（on_interval.seconds / on_margin_warning.threshold）。"""
    data = _fetch_blocks()
    oi = next(b for b in data["events"] if b["kind"] == "on_interval")
    seconds = oi["param_schema"]["seconds"]
    assert seconds.get("label") == "间隔秒数"
    assert seconds.get("unit") == "秒"

    omw = next(b for b in data["events"] if b["kind"] == "on_margin_warning")
    threshold = omw["param_schema"]["threshold"]
    assert threshold.get("label") == "保证金率阈值"
    assert threshold.get("unit") == "保证金率"


def test_registry_list_includes_label_and_display_template():
    """直接调用 Registry.list() 验证含 label 与 display_template 字段。"""
    from dsl.registry import (
        indicator_registry,
        condition_registry,
        action_registry,
        event_registry,
    )
    # 触发积木注册（与 router 导入副作用一致）
    import dsl.blocks.indicators  # noqa: F401
    import dsl.blocks.conditions  # noqa: F401
    import dsl.blocks.actions  # noqa: F401
    import dsl.blocks.events  # noqa: F401

    for registry in (indicator_registry, condition_registry, action_registry, event_registry):
        items = registry.list()
        assert len(items) > 0
        for item in items:
            assert "label" in item, f"{registry._block_type} list() 项缺少 label 字段"
            assert "display_template" in item, (
                f"{registry._block_type} list() 项缺少 display_template 字段"
            )


# ============================================================
# 基础策略 param_schema step 校验（问题 5：order_qty 输入小数）
# ============================================================


def test_grid_order_qty_has_step_in_blocks_api():
    """GET /api/dsl/blocks 返回的 grid 基础策略 order_qty 含 step=0.001。

    前端实例参数编辑区读取该 step 用于 <input step=...>，未声明时
    fallback 到 1 会阻断 0.01 等小数输入。此测试锁定后端显式声明。
    """
    data = _fetch_blocks()
    base_strategies = {b["kind"]: b for b in data["base_strategies"]}
    assert "grid" in base_strategies, "base_strategies 缺少 grid"
    grid_schema = base_strategies["grid"].get("param_schema") or {}
    assert "order_qty" in grid_schema, "grid param_schema 缺少 order_qty"
    order_qty = grid_schema["order_qty"]
    assert order_qty.get("step") == 0.001, (
        f"grid.order_qty step 期望 0.001，实际 {order_qty.get('step')!r}"
    )

