import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from pydantic import ValidationError

from dsl.schema import (
    QSModelConfig, StrategyMeta, ParamDefinition, RiskFilter,
    StrategyDSL, BaseStrategyRef, Rule, Trigger,
    ConditionRef, ActionRef,
    resolve_variables,
)
from dsl import (
    QSModelConfig as QSModelConfig2,
    StrategyMeta as StrategyMeta2,
    ParamDefinition as ParamDefinition2,
    RiskFilter as RiskFilter2,
    resolve_variables as resolve_variables2,
)


# ===================== 辅助构造 =====================


def _build_qm_model() -> QSModelConfig:
    """构造一个用于测试的 QS-Model 完整实例。"""
    return QSModelConfig(
        meta=StrategyMeta(
            name="BTC 网格策略",
            version="v1.2.0",
            author="quant_team",
            description="基于网格的低频策略",
            asset_class="CRYPTO",
            frequency="15min",
            base_symbol="BTC-USDT",
        ),
        params={
            "fast_period": ParamDefinition(
                label="快均线周期",
                value=10,
                type="int",
                range=[2, 100],
                unit="根",
            ),
            "slow_period": ParamDefinition(
                label="慢均线周期",
                value=30,
                type="int",
                range=[10, 200],
                unit="根",
            ),
            "threshold_pct": ParamDefinition(
                label="触发阈值",
                value=0.05,
                type="float",
                range=[0.0, 1.0],
                unit="%",
            ),
        },
        logic=StrategyDSL(
            base_strategy=BaseStrategyRef(
                kind="grid",
                params={
                    "upper": "$meta.base_symbol",
                    "fast": "$params.fast_period",
                    "slow": "$params.slow_period",
                    "literal_int": 100,
                    "literal_str": "static_value",
                },
            ),
            rules=[
                Rule(
                    name="金叉入场",
                    when=Trigger(
                        mode="condition",
                        condition=ConditionRef(
                            kind="cross_above",
                            args={
                                "fast": "$params.fast_period",
                                "slow": "$params.slow_period",
                            },
                        ),
                    ),
                    then=[
                        ActionRef(
                            kind="open_position",
                            args={"pct": "$params.threshold_pct"},
                        ),
                    ],
                ),
            ],
        ),
        risk_filter=RiskFilter(
            max_position_ratio=0.8,
            daily_max_loss=0.05,
            min_trade_size=0.001,
            blacklist_hours=["00:00", "01:00"],
        ),
    )


# ===================== 1. 序列化/反序列化 =====================


def test_qs_model_roundtrip_dict():
    """1. QSModelConfig dict 序列化/反序列化往返"""
    qm = _build_qm_model()
    dumped = qm.model_dump()
    assert dumped["qs_model_version"] == "2.0"
    assert dumped["meta"]["name"] == "BTC 网格策略"
    assert dumped["meta"]["base_symbol"] == "BTC-USDT"
    assert dumped["params"]["fast_period"]["value"] == 10
    assert dumped["logic"]["base_strategy"]["kind"] == "grid"
    assert dumped["risk_filter"]["max_position_ratio"] == 0.8

    qm2 = QSModelConfig.model_validate(dumped)
    assert qm2 == qm


def test_qs_model_roundtrip_json():
    """2. QSModelConfig JSON 序列化/反序列化往返"""
    qm = _build_qm_model()
    json_str = qm.model_dump_json()
    qm2 = QSModelConfig.model_validate_json(json_str)
    assert qm2 == qm
    assert qm2.params["fast_period"].value == 10
    assert qm2.risk_filter.blacklist_hours == ["00:00", "01:00"]


def test_qs_model_defaults():
    """3. 默认值：qs_model_version=2.0, params={}, risk_filter=None"""
    qm = QSModelConfig(
        meta=StrategyMeta(name="minimal"),
        logic=StrategyDSL(base_strategy=BaseStrategyRef(kind="grid")),
    )
    assert qm.qs_model_version == "2.0"
    assert qm.params == {}
    assert qm.risk_filter is None
    assert qm.meta.asset_class == "CRYPTO"
    assert qm.meta.version == "v1.0.0"


def test_param_definition_fields():
    """4. ParamDefinition 字段与默认值"""
    p = ParamDefinition(label="阈值", value=0.1, type="float")
    assert p.label == "阈值"
    assert p.value == 0.1
    assert p.type == "float"
    assert p.range is None
    assert p.options is None
    assert p.option_labels is None
    assert p.unit == ""
    assert p.description == ""


def test_risk_filter_all_none():
    """5. RiskFilter 所有字段默认 None"""
    rf = RiskFilter()
    assert rf.max_position_ratio is None
    assert rf.daily_max_loss is None
    assert rf.min_trade_size is None
    assert rf.blacklist_hours is None


def test_meta_required_name():
    """6. StrategyMeta name 必填"""
    with pytest.raises(ValidationError):
        StrategyMeta()


def test_qs_model_logic_required():
    """7. QSModelConfig meta + logic 必填"""
    with pytest.raises(ValidationError):
        QSModelConfig(meta=StrategyMeta(name="x"))


def test_qs_model_exported_from_dsl_init():
    """8. 验证 __init__.py 导出一致"""
    assert QSModelConfig is QSModelConfig2
    assert StrategyMeta is StrategyMeta2
    assert ParamDefinition is ParamDefinition2
    assert RiskFilter is RiskFilter2
    assert resolve_variables is resolve_variables2


# ===================== 2. 变量引用解析 =====================


def test_resolve_params_reference():
    """9. $params.xxx 被替换为 params 中对应 value"""
    qm = _build_qm_model()
    resolved = resolve_variables(qm)
    bs = resolved.base_strategy
    assert bs.params["fast"] == 10
    assert bs.params["slow"] == 30


def test_resolve_meta_reference():
    """10. $meta.base_symbol 被替换为 meta.base_symbol"""
    qm = _build_qm_model()
    resolved = resolve_variables(qm)
    bs = resolved.base_strategy
    assert bs.params["upper"] == "BTC-USDT"


def test_resolve_param_overrides():
    """11. param_overrides 覆盖 params 默认 value"""
    qm = _build_qm_model()
    overrides = {"fast_period": 50, "threshold_pct": 0.15}
    resolved = resolve_variables(qm, param_overrides=overrides)
    bs = resolved.base_strategy
    assert bs.params["fast"] == 50
    # 未覆盖的仍取 params.value
    assert bs.params["slow"] == 30
    # 嵌套 rules 中的引用同样生效
    rule = resolved.rules[0]
    assert rule.when.condition.args["fast"] == 50
    assert rule.when.condition.args["slow"] == 30
    assert rule.then[0].args["pct"] == 0.15


def test_resolve_keeps_literals():
    """12. 纯字面量（int/str）不被替换"""
    qm = _build_qm_model()
    resolved = resolve_variables(qm)
    bs = resolved.base_strategy
    assert bs.params["literal_int"] == 100
    assert bs.params["literal_str"] == "static_value"


def test_resolve_nested_rules():
    """13. 嵌套 rules[].when/then 中的变量引用被替换"""
    qm = _build_qm_model()
    resolved = resolve_variables(qm)
    rule = resolved.rules[0]
    assert rule.name == "金叉入场"
    assert rule.when.condition.kind == "cross_above"
    assert rule.when.condition.args["fast"] == 10
    assert rule.when.condition.args["slow"] == 30
    assert rule.then[0].kind == "open_position"
    assert rule.then[0].args["pct"] == 0.05


def test_resolve_does_not_mutate_input():
    """14. resolve_variables 不修改原 QSModelConfig.logic 对象"""
    qm = _build_qm_model()
    original_dump = qm.logic.model_dump()
    _ = resolve_variables(qm)
    after_dump = qm.logic.model_dump()
    assert original_dump == after_dump
    # 引用字符串应保持原样
    assert qm.logic.base_strategy.params["fast"] == "$params.fast_period"
    assert qm.logic.base_strategy.params["upper"] == "$meta.base_symbol"


def test_resolve_unknown_reference_kept():
    """15. 未知的 $params.xxx / $meta.xxx 引用保持原样"""
    qm = QSModelConfig(
        meta=StrategyMeta(name="x", base_symbol="BTC-USDT"),
        params={},
        logic=StrategyDSL(
            base_strategy=BaseStrategyRef(
                kind="grid",
                params={
                    "unknown_param": "$params.not_exists",
                    "unknown_meta": "$meta.not_exists",
                    "normal": 42,
                },
            ),
        ),
    )
    resolved = resolve_variables(qm)
    bs = resolved.base_strategy
    assert bs.params["unknown_param"] == "$params.not_exists"
    assert bs.params["unknown_meta"] == "$meta.not_exists"
    assert bs.params["normal"] == 42


def test_resolve_returns_new_strategy_dsl():
    """16. 返回值是新的 StrategyDSL 对象"""
    qm = _build_qm_model()
    resolved = resolve_variables(qm)
    assert isinstance(resolved, StrategyDSL)
    # 不是同一个 logic 对象
    assert resolved is not qm.logic
    assert resolved.base_strategy is not qm.logic.base_strategy


def test_resolve_meta_other_fields():
    """17. $meta 可引用 meta 任意字段"""
    qm = QSModelConfig(
        meta=StrategyMeta(name="my_strategy", version="v9.9.9", frequency="1h"),
        logic=StrategyDSL(
            base_strategy=BaseStrategyRef(
                kind="grid",
                params={
                    "name_ref": "$meta.name",
                    "ver_ref": "$meta.version",
                    "freq_ref": "$meta.frequency",
                },
            ),
        ),
    )
    resolved = resolve_variables(qm)
    bs = resolved.base_strategy
    assert bs.params["name_ref"] == "my_strategy"
    assert bs.params["ver_ref"] == "v9.9.9"
    assert bs.params["freq_ref"] == "1h"


def test_resolve_no_references_at_all():
    """18. 完全无变量引用时正常返回等价 DSL"""
    qm = QSModelConfig(
        meta=StrategyMeta(name="plain"),
        logic=StrategyDSL(
            base_strategy=BaseStrategyRef(
                kind="grid",
                params={"upper": 100, "lower": 50},
            ),
        ),
    )
    resolved = resolve_variables(qm)
    assert resolved.base_strategy.params == {"upper": 100, "lower": 50}


def test_resolve_deeply_nested_list_in_args():
    """19. args 中包含 list 与 dict 嵌套结构的变量引用"""
    qm = QSModelConfig(
        meta=StrategyMeta(name="x", base_symbol="BTC-USDT"),
        params={"p1": ParamDefinition(label="p", value=7, type="int")},
        logic=StrategyDSL(
            base_strategy=BaseStrategyRef(kind="grid"),
            rules=[
                Rule(
                    name="complex",
                    when=Trigger(
                        mode="condition",
                        condition=ConditionRef(
                            kind="multi",
                            args={
                                "list_ref": ["$params.p1", "$meta.base_symbol", 99],
                                "dict_ref": {"inner": "$params.p1"},
                            },
                        ),
                    ),
                    then=[],
                ),
            ],
        ),
    )
    resolved = resolve_variables(qm)
    cond_args = resolved.rules[0].when.condition.args
    assert cond_args["list_ref"] == [7, "BTC-USDT", 99]
    assert cond_args["dict_ref"] == {"inner": 7}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
