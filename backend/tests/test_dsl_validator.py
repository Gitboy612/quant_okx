"""DSL 静态校验器测试。

覆盖 spec.md「Requirement: DSL 静态校验」五层校验：

- 合法配置（应通过）：condition-trigger / event-trigger / event+extra_condition
  / 最小配置 / 多规则
- 非法配置（应失败并返回正确错误码）：结构 / 引用(UNKNOWN_KIND 递归) /
  语义(EMPTY_THEN / DUPLICATE_RULE_NAME / RECOVER_WITHOUT_WHEN /
  触发器字段缺失 / UNRECOVERABLE_STATE) / 资源(UNSUPPORTED_WINDOW / INVALID_QTY)

导入风格参考 test_dsl_schema.py：sys.path 注入 backend 根目录后用
``from dsl.xxx import``。导入 dsl.validator 即触发所有积木库注册。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from dsl.validator import DSLValidator, ValidationResult, ValidationError


# ============================================================
# 辅助构造
# ============================================================

def _validate(config: dict) -> ValidationResult:
    return DSLValidator().validate(config)


def _base_grid() -> dict:
    """用户示例的基础网格策略配置。"""
    return {
        "kind": "grid",
        "params": {
            "upper_price": 50000,
            "lower_price": 40000,
            "grid_count": 10,
            "order_qty": 0.01,
            "symbol": "BTC-USDT",
        },
    }


def _price_change_indicator(window: str = "1h", symbol: str = "BTC-USDT") -> dict:
    return {"kind": "price_change_pct", "args": {"window": window, "symbol": symbol}}


def _gt(indicator: dict, threshold: float) -> dict:
    return {"kind": "gt", "args": {"indicator": indicator, "threshold": threshold}}


def _abs_lt(indicator: dict, threshold: float) -> dict:
    return {"kind": "abs_lt", "args": {"indicator": indicator, "threshold": threshold}}


def _has_error(result: ValidationResult, layer: str, code: str) -> bool:
    return any(e.layer == layer and e.code == code for e in result.errors)


# ============================================================
# 合法配置
# ============================================================


def test_valid_condition_trigger():
    """用户示例「单边上涨暂停」配置：condition-trigger + recover_when，应通过。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "单边上涨暂停",
                "when": {
                    "mode": "condition",
                    "condition": _gt(_price_change_indicator("1h"), 0.05),
                },
                "then": [
                    {"kind": "pause_orders"},
                    {"kind": "hold_position"},
                    {"kind": "log_event", "args": {"level": "warn", "message": "单边上涨暂停"}},
                ],
                "recover_when": {
                    "mode": "condition",
                    "condition": _abs_lt(_price_change_indicator("1h"), 0.05),
                },
                "recover_then": [
                    {"kind": "rebalance_position", "args": {"mode": "to_theoretical"}},
                    {"kind": "resume_orders"},
                ],
                "cool_down_seconds": 60,
            }
        ],
    }
    result = _validate(config)
    assert result.valid, f"应通过校验，但得到错误: {[e.__dict__ for e in result.errors]}"
    assert result.errors == []


def test_valid_event_trigger():
    """on_margin_warning 事件触发 + then 动作，应通过。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "保证金预警",
                "when": {
                    "mode": "event",
                    "event": {
                        "kind": "on_margin_warning",
                        "args": {"symbol": "BTC-USDT-SWAP", "threshold": 0.5},
                    },
                },
                "then": [
                    {"kind": "log_event", "args": {"level": "critical", "message": "保证金率告警"}},
                    {"kind": "pause_orders"},
                ],
            }
        ],
    }
    result = _validate(config)
    assert result.valid, f"应通过校验，但得到错误: {[e.__dict__ for e in result.errors]}"


def test_valid_event_with_extra_condition():
    """event + extra_condition 组合，应通过。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "成交且涨幅异常",
                "when": {
                    "mode": "event",
                    "event": {"kind": "on_order_filled", "args": {"side": "buy"}},
                    "extra_condition": _gt(_price_change_indicator("1h"), 0.05),
                },
                "then": [{"kind": "hold_position"}],
            }
        ],
    }
    result = _validate(config)
    assert result.valid, f"应通过校验，但得到错误: {[e.__dict__ for e in result.errors]}"


def test_valid_minimal_config():
    """只有 base_strategy 无 rules，应通过。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
    }
    result = _validate(config)
    assert result.valid, f"应通过校验，但得到错误: {[e.__dict__ for e in result.errors]}"
    assert result.errors == []


def test_valid_multiple_rules():
    """多条规则（不同名），应通过。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "规则一",
                "when": {
                    "mode": "condition",
                    "condition": _gt(_price_change_indicator("1h"), 0.05),
                },
                "then": [{"kind": "pause_orders"}],
            },
            {
                "name": "规则二",
                "when": {
                    "mode": "event",
                    "event": {"kind": "on_interval", "args": {"seconds": 60}},
                },
                "then": [{"kind": "log_event", "args": {"message": "定时检查"}}],
            },
        ],
    }
    result = _validate(config)
    assert result.valid, f"应通过校验，但得到错误: {[e.__dict__ for e in result.errors]}"


# ============================================================
# 结构校验（structure）
# ============================================================


def test_invalid_version():
    """version="2.0" 不在 Literal["1.0"] 内，结构校验失败。"""
    config = {
        "version": "2.0",
        "base_strategy": _base_grid(),
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "structure", "SCHEMA_ERROR")
    # 结构失败应短路，后续层不执行
    assert all(e.layer == "structure" for e in result.errors)


def test_invalid_missing_base_strategy():
    """缺少必填 base_strategy，结构校验失败。"""
    config = {"version": "1.0", "rules": []}
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "structure", "SCHEMA_ERROR")


# ============================================================
# 引用校验（reference / UNKNOWN_KIND）
# ============================================================


def test_unknown_base_strategy_kind():
    """base_strategy.kind="nonexistent_strategy" 未注册 → UNKNOWN_KIND。

    注意：martingale/trend/dca 等已注册为 DSL 基础策略，故使用一个确定未注册的 kind。
    """
    config = {
        "version": "1.0",
        "base_strategy": {"kind": "nonexistent_strategy", "params": {}},
        "rules": [],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "reference", "UNKNOWN_KIND")
    err = next(e for e in result.errors if e.code == "UNKNOWN_KIND")
    assert "base_strategy.kind" in err.path


def test_unknown_indicator_kind():
    """indicator.kind="nonexistent" → UNKNOWN_KIND。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "condition",
                    "condition": _gt({"kind": "nonexistent", "args": {}}, 0.05),
                },
                "then": [{"kind": "pause_orders"}],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "reference", "UNKNOWN_KIND")
    err = next(e for e in result.errors if e.code == "UNKNOWN_KIND")
    assert "indicator" in err.path


def test_unknown_condition_kind():
    """condition.kind="foo" → UNKNOWN_KIND。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "condition",
                    "condition": {"kind": "foo", "args": {}},
                },
                "then": [{"kind": "pause_orders"}],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "reference", "UNKNOWN_KIND")
    err = next(e for e in result.errors if e.code == "UNKNOWN_KIND")
    assert "condition" in err.path


def test_unknown_action_kind():
    """action.kind="bar" → UNKNOWN_KIND。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "condition",
                    "condition": _gt(_price_change_indicator("1h"), 0.05),
                },
                "then": [{"kind": "bar", "args": {}}],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "reference", "UNKNOWN_KIND")
    err = next(e for e in result.errors if e.code == "UNKNOWN_KIND")
    assert "then" in err.path


def test_unknown_event_kind():
    """event.kind="on_nonexistent" → UNKNOWN_KIND。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "event",
                    "event": {"kind": "on_nonexistent", "args": {}},
                },
                "then": [{"kind": "pause_orders"}],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "reference", "UNKNOWN_KIND")
    err = next(e for e in result.errors if e.code == "UNKNOWN_KIND")
    assert "event" in err.path


def test_nested_unknown_kind_in_and():
    """and 条件嵌套一个未知子条件 → 引用校验递归发现 UNKNOWN_KIND。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "condition",
                    "condition": {
                        "kind": "and",
                        "args": {
                            "conditions": [
                                _gt(_price_change_indicator("1h"), 0.05),
                                {"kind": "foo", "args": {}},
                            ]
                        },
                    },
                },
                "then": [{"kind": "pause_orders"}],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "reference", "UNKNOWN_KIND")
    err = next(e for e in result.errors if e.code == "UNKNOWN_KIND")
    # 路径应体现嵌套位置
    assert "conditions" in err.path


# ============================================================
# 语义校验（semantic）
# ============================================================


def test_condition_trigger_missing_condition():
    """mode="condition" 但 condition=None → CONDITION_TRIGGER_MISSING_CONDITION。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {"mode": "condition", "condition": None},
                "then": [{"kind": "pause_orders"}],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "semantic", "CONDITION_TRIGGER_MISSING_CONDITION")


def test_event_trigger_missing_event():
    """mode="event" 但 event=None → EVENT_TRIGGER_MISSING_EVENT。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {"mode": "event", "event": None},
                "then": [{"kind": "pause_orders"}],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "semantic", "EVENT_TRIGGER_MISSING_EVENT")


def test_empty_then():
    """then=[] → EMPTY_THEN。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "condition",
                    "condition": _gt(_price_change_indicator("1h"), 0.05),
                },
                "then": [],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "semantic", "EMPTY_THEN")


def test_duplicate_rule_name():
    """两条 rule 同名 → DUPLICATE_RULE_NAME。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "重复名",
                "when": {
                    "mode": "condition",
                    "condition": _gt(_price_change_indicator("1h"), 0.05),
                },
                "then": [{"kind": "pause_orders"}],
            },
            {
                "name": "重复名",
                "when": {
                    "mode": "condition",
                    "condition": _gt(_price_change_indicator("1h"), 0.05),
                },
                "then": [{"kind": "resume_orders"}],
            },
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "semantic", "DUPLICATE_RULE_NAME")


def test_recover_then_without_recover_when():
    """recover_then 非空但 recover_when=None → RECOVER_WITHOUT_WHEN。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "condition",
                    "condition": _gt(_price_change_indicator("1h"), 0.05),
                },
                "then": [{"kind": "pause_orders"}],
                "recover_then": [{"kind": "resume_orders"}],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "semantic", "RECOVER_WITHOUT_WHEN")


def test_unrecoverable_state():
    """有 recover_when 但 recover_then 为空 → UNRECOVERABLE_STATE（无法回到 RUNNING）。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "condition",
                    "condition": _gt(_price_change_indicator("1h"), 0.05),
                },
                "then": [{"kind": "pause_orders"}],
                "recover_when": {
                    "mode": "condition",
                    "condition": _abs_lt(_price_change_indicator("1h"), 0.05),
                },
                "recover_then": [],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "semantic", "UNRECOVERABLE_STATE")


# ============================================================
# 资源校验（resource）
# ============================================================


def test_unsupported_window():
    """window="2h" 不在支持列表 → UNSUPPORTED_WINDOW。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "condition",
                    "condition": _gt(_price_change_indicator("2h"), 0.05),
                },
                "then": [{"kind": "pause_orders"}],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "resource", "UNSUPPORTED_WINDOW")
    err = next(e for e in result.errors if e.code == "UNSUPPORTED_WINDOW")
    assert "window" in err.path


def test_invalid_qty_zero():
    """place_order qty=0 → INVALID_QTY。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "event",
                    "event": {"kind": "on_tick", "args": {"symbol": "BTC-USDT"}},
                },
                "then": [
                    {
                        "kind": "place_order",
                        "args": {
                            "symbol": "BTC-USDT",
                            "side": "buy",
                            "type": "market",
                            "qty": 0,
                        },
                    }
                ],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "resource", "INVALID_QTY")


def test_invalid_qty_negative():
    """place_order qty=-1（负数）→ INVALID_QTY。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "event",
                    "event": {"kind": "on_tick", "args": {"symbol": "BTC-USDT"}},
                },
                "then": [
                    {
                        "kind": "place_order",
                        "args": {
                            "symbol": "BTC-USDT",
                            "side": "sell",
                            "type": "limit",
                            "qty": -0.5,
                            "price": 50000,
                        },
                    }
                ],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "resource", "INVALID_QTY")


# ============================================================
# 类型校验（type / TYPE_MISMATCH）
# ============================================================


def test_type_mismatch_logic_missing_child():
    """and 条件缺少 args.conditions → TYPE_MISMATCH（逻辑组合期望子条件引用）。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "condition",
                    "condition": {"kind": "and", "args": {}},
                },
                "then": [{"kind": "pause_orders"}],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "type", "TYPE_MISMATCH")


def test_type_mismatch_compare_missing_indicator():
    """gt 条件缺少 args.indicator → TYPE_MISMATCH（比较类期望数值型指标）。"""
    config = {
        "version": "1.0",
        "base_strategy": _base_grid(),
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "condition",
                    "condition": {"kind": "gt", "args": {"threshold": 0.05}},
                },
                "then": [{"kind": "pause_orders"}],
            }
        ],
    }
    result = _validate(config)
    assert not result.valid
    assert _has_error(result, "type", "TYPE_MISMATCH")


# ============================================================
# 附加：接受 StrategyDSL 实例 / 错误结构
# ============================================================


def test_validate_accepts_dsl_instance():
    """validate 接受 StrategyDSL 实例（结构已合法）。"""
    from dsl.schema import StrategyDSL

    dsl = StrategyDSL.model_validate({
        "version": "1.0",
        "base_strategy": _base_grid(),
    })
    result = DSLValidator().validate(dsl)
    assert result.valid
    assert result.errors == []


def test_validation_error_dataclass_fields():
    """ValidationError 含 layer/code/message/path 四字段。"""
    err = ValidationError("semantic", "EMPTY_THEN", "说明", "rules[0].then")
    assert err.layer == "semantic"
    assert err.code == "EMPTY_THEN"
    assert err.message == "说明"
    assert err.path == "rules[0].then"


def test_validation_result_add_error_marks_invalid():
    """add_error 应把 valid 置为 False。"""
    r = ValidationResult()
    assert r.valid is True
    r.add_error("structure", "SCHEMA_ERROR", "x", "version")
    assert r.valid is False
    assert len(r.errors) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
