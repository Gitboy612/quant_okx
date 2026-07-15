"""QSModel 生成器模块单元测试（Task 8）。

验证四类生成器输出的 QSModelConfig 合法性与 spec 要求：
- build_risk_filter 输出含 daily_max_loss/stop_loss/take_profit
- generate_classic_variant 输出合法 QSModelConfig（含四段、params 引用正确）
- generate_dsl_innovation 含 rules 数组
- generate_backtest_candidates 返回 5-10 个候选
- generate_ab_variants 生成多变体、param_name 正确替换
- 生成的 QSModel 可被 QSModelConfig schema 验证

导入风格参考 test_dsl_schema.py：sys.path 注入 backend 根目录。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from dsl.schema import QSModelConfig, StrategyDSL, resolve_variables
from research.qsm_generator import (
    build_risk_filter,
    generate_classic_variant,
    generate_dsl_innovation,
    generate_backtest_candidates,
    generate_ab_variants,
    validate_qsm,
)


# ============================================================
# 1. build_risk_filter
# ============================================================


def test_build_risk_filter_default():
    """build_risk_filter 默认输出含 daily_max_loss=10.0 / stop_loss=0.05 / take_profit=0.1。"""
    rf = build_risk_filter()
    assert rf["daily_max_loss"] == 10.0
    assert rf["stop_loss"] == 0.05
    assert rf["take_profit"] == 0.1


def test_build_risk_filter_custom():
    """build_risk_filter 接受自定义参数。"""
    rf = build_risk_filter(daily_max_loss=20.0, stop_loss=0.08, take_profit=0.15)
    assert rf["daily_max_loss"] == 20.0
    assert rf["stop_loss"] == 0.08
    assert rf["take_profit"] == 0.15


def test_build_risk_filter_has_three_keys():
    """risk_filter dict 含 daily_max_loss / stop_loss / take_profit 三个键。"""
    rf = build_risk_filter()
    assert "daily_max_loss" in rf
    assert "stop_loss" in rf
    assert "take_profit" in rf


# ============================================================
# 2. generate_classic_variant
# ============================================================


def test_classic_variant_has_four_sections():
    """generate_classic_variant 输出含 meta/params/logic/risk_filter 四段。"""
    qsm = generate_classic_variant("BTC-USDT", 0)
    assert "meta" in qsm
    assert "params" in qsm
    assert "logic" in qsm
    assert "risk_filter" in qsm
    assert qsm["qs_model_version"] == "2.0"


def test_classic_variant_meta_name():
    """meta.name = f"classic_grid_{seed}", version="1.0"。"""
    qsm = generate_classic_variant("BTC-USDT", 0)
    assert qsm["meta"]["name"] == "classic_grid_0"
    assert qsm["meta"]["version"] == "1.0"
    assert qsm["meta"]["base_symbol"] == "BTC-USDT"


def test_classic_variant_seed_0_params():
    """seed=0 → grid_count=10, order_qty=0.1, lever=1。"""
    qsm = generate_classic_variant("BTC-USDT", 0)
    assert qsm["params"]["grid_count"]["value"] == 10
    assert qsm["params"]["order_qty"]["value"] == 0.1
    assert qsm["params"]["lever"]["value"] == 1


def test_classic_variant_seed_1_params():
    """seed=1 → grid_count=20, order_qty=0.5, lever=5（不同参数组合）。"""
    qsm = generate_classic_variant("BTC-USDT", 1)
    assert qsm["params"]["grid_count"]["value"] == 20
    assert qsm["params"]["order_qty"]["value"] == 0.5
    assert qsm["params"]["lever"]["value"] == 5


def test_classic_variant_params_reference():
    """logic.base_strategy.params 引用 $params.grid_count / $params.order_qty。"""
    qsm = generate_classic_variant("BTC-USDT", 0)
    bs_params = qsm["logic"]["base_strategy"]["params"]
    assert bs_params["grid_count"] == "$params.grid_count"
    assert bs_params["order_qty"] == "$params.order_qty"
    assert bs_params["symbol"] == "$meta.base_symbol"


def test_classic_variant_base_strategy_kind():
    """logic.base_strategy.kind == "grid"。"""
    qsm = generate_classic_variant("BTC-USDT", 0)
    assert qsm["logic"]["base_strategy"]["kind"] == "grid"


def test_classic_variant_risk_filter():
    """classic_variant 输出含 risk_filter 段（调 build_risk_filter）。"""
    qsm = generate_classic_variant("BTC-USDT", 0)
    rf = qsm["risk_filter"]
    assert rf is not None
    assert rf["daily_max_loss"] == 10.0
    assert rf["stop_loss"] == 0.05
    assert rf["take_profit"] == 0.1


def test_classic_variant_seed_cycles():
    """variant_seed 超过表长时取模循环（seed=6 等价于 seed=0）。"""
    qsm_0 = generate_classic_variant("BTC-USDT", 0)
    qsm_6 = generate_classic_variant("BTC-USDT", 6)
    assert qsm_6["params"]["grid_count"]["value"] == qsm_0["params"]["grid_count"]["value"]


def test_classic_variant_resolves_variables():
    """生成的 QSModel 经 resolve_variables 解析后 $params.xxx 被正确替换。"""
    qsm = generate_classic_variant("BTC-USDT", 0)
    config = QSModelConfig.model_validate(qsm)
    resolved = resolve_variables(config)
    bs = resolved.base_strategy
    assert bs.params["grid_count"] == 10
    assert bs.params["order_qty"] == 0.1
    assert bs.params["symbol"] == "BTC-USDT"


# ============================================================
# 3. generate_dsl_innovation
# ============================================================


def test_dsl_innovation_has_rules():
    """generate_dsl_innovation 输出含 rules 数组。"""
    qsm = generate_dsl_innovation("BTC-USDT", 0)
    assert "rules" in qsm["logic"]
    assert len(qsm["logic"]["rules"]) >= 1


def test_dsl_innovation_seed_0_cross_above():
    """seed=0: grid + cross_above(price, ema) → pause_orders。"""
    qsm = generate_dsl_innovation("BTC-USDT", 0)
    assert qsm["logic"]["base_strategy"]["kind"] == "grid"
    rule = qsm["logic"]["rules"][0]
    assert rule["when"]["condition"]["kind"] == "cross_above"
    assert rule["then"][0]["kind"] == "pause_orders"


def test_dsl_innovation_seed_1_cross_below():
    """seed=1: grid + cross_below(price, rsi) → rebalance_position。"""
    qsm = generate_dsl_innovation("BTC-USDT", 1)
    rule = qsm["logic"]["rules"][0]
    assert rule["when"]["condition"]["kind"] == "cross_below"
    assert rule["then"][0]["kind"] == "rebalance_position"


def test_dsl_innovation_seed_2_in_range():
    """seed=2: trend + in_range(volatility, 0, 0.02) → hold_position。"""
    qsm = generate_dsl_innovation("BTC-USDT", 2)
    assert qsm["logic"]["base_strategy"]["kind"] == "trend"
    rule = qsm["logic"]["rules"][0]
    assert rule["when"]["condition"]["kind"] == "in_range"
    assert rule["then"][0]["kind"] == "hold_position"


def test_dsl_innovation_rule_has_name_and_when_then():
    """每条 rule 含 name / when / then 字段。"""
    for seed in range(3):
        qsm = generate_dsl_innovation("BTC-USDT", seed)
        rule = qsm["logic"]["rules"][0]
        assert "name" in rule
        assert "when" in rule
        assert "then" in rule
        assert len(rule["then"]) >= 1


def test_dsl_innovation_risk_filter():
    """dsl_innovation 输出含 risk_filter 段。"""
    qsm = generate_dsl_innovation("BTC-USDT", 0)
    assert qsm["risk_filter"] is not None
    assert "daily_max_loss" in qsm["risk_filter"]
    assert "stop_loss" in qsm["risk_filter"]
    assert "take_profit" in qsm["risk_filter"]


def test_dsl_innovation_seed_cycles():
    """innovation_seed=3 等价于 seed=0（取模循环）。"""
    qsm_0 = generate_dsl_innovation("BTC-USDT", 0)
    qsm_3 = generate_dsl_innovation("BTC-USDT", 3)
    assert qsm_0["logic"]["rules"][0]["when"]["condition"]["kind"] == \
        qsm_3["logic"]["rules"][0]["when"]["condition"]["kind"]


def test_dsl_innovation_uses_meta_base_symbol():
    """DSL 创新策略的 indicator args 引用 $meta.base_symbol。"""
    qsm = generate_dsl_innovation("BTC-USDT", 0)
    cond_args = qsm["logic"]["rules"][0]["when"]["condition"]["args"]
    indicator_a = cond_args["indicator_a"]
    assert indicator_a["args"]["symbol"] == "$meta.base_symbol"


# ============================================================
# 4. generate_backtest_candidates
# ============================================================


def test_backtest_candidates_count():
    """generate_backtest_candidates 返回 5-10 个候选。"""
    candidates = generate_backtest_candidates("BTC-USDT")
    assert 5 <= len(candidates) <= 10


def test_backtest_candidates_all_valid_qsm():
    """每个候选都是合法 QSModelConfig（可被 QSModelConfig schema 验证）。"""
    candidates = generate_backtest_candidates("BTC-USDT")
    for i, c in enumerate(candidates):
        assert validate_qsm(c), f"候选 {i} 不是合法 QSModelConfig"


def test_backtest_candidates_have_risk_filter():
    """每个候选都含 risk_filter 段。"""
    candidates = generate_backtest_candidates("BTC-USDT")
    for c in candidates:
        assert c["risk_filter"] is not None
        assert "daily_max_loss" in c["risk_filter"]


def test_backtest_candidates_mixed_types():
    """候选列表混合经典变体与 DSL 创新（不同 meta.name 前缀）。"""
    candidates = generate_backtest_candidates("BTC-USDT")
    names = [c["meta"]["name"] for c in candidates]
    # 应有 classic_grid_ 开头的经典变体
    assert any(n.startswith("classic_grid_") for n in names)
    # 应有 dsl_ 开头的 DSL 创新
    assert any(n.startswith("dsl_") for n in names)


def test_backtest_candidates_different_params():
    """候选之间参数组合不同（至少前两个 grid_count 不同或 base_strategy kind 不同）。"""
    candidates = generate_backtest_candidates("BTC-USDT")
    # 取前两个经典变体，验证参数不同
    c0 = candidates[0]
    c1 = candidates[1]
    gc0 = c0["params"]["grid_count"]["value"]
    gc1 = c1["params"]["grid_count"]["value"]
    assert gc0 != gc1, "前两个经典变体的 grid_count 应不同"


# ============================================================
# 5. generate_ab_variants
# ============================================================


def test_ab_variants_count():
    """generate_ab_variants 返回与 values 等长的变体列表。"""
    base = generate_classic_variant("BTC-USDT", 0)
    variants = generate_ab_variants(base, "grid_count", [5, 10, 20, 50])
    assert len(variants) == 4


def test_ab_variants_param_replaced():
    """每个变体的 params[param_name].value 被正确替换。"""
    base = generate_classic_variant("BTC-USDT", 0)
    variants = generate_ab_variants(base, "grid_count", [5, 10, 20])
    for i, v in enumerate([5, 10, 20]):
        assert variants[i]["params"]["grid_count"]["value"] == v


def test_ab_variants_name_suffix():
    """每个变体 meta.name 加后缀 _ab_{value}。"""
    base = generate_classic_variant("BTC-USDT", 0)
    variants = generate_ab_variants(base, "grid_count", [5, 10, 20])
    assert variants[0]["meta"]["name"] == "classic_grid_0_ab_5"
    assert variants[1]["meta"]["name"] == "classic_grid_0_ab_10"
    assert variants[2]["meta"]["name"] == "classic_grid_0_ab_20"


def test_ab_variants_logic_unchanged():
    """所有变体的 logic 段保持不变（同 logic 不同 params）。"""
    base = generate_classic_variant("BTC-USDT", 0)
    variants = generate_ab_variants(base, "grid_count", [5, 10, 20])
    base_logic = base["logic"]
    for v in variants:
        assert v["logic"] == base_logic


def test_ab_variants_resolve_correctly():
    """A/B 变体经 resolve_variables 解析后，$params.grid_count 被替换为对应值。"""
    base = generate_classic_variant("BTC-USDT", 0)
    variants = generate_ab_variants(base, "grid_count", [5, 50])
    # 验证变体 0 解析后 grid_count=5
    config0 = QSModelConfig.model_validate(variants[0])
    resolved0 = resolve_variables(config0)
    assert resolved0.base_strategy.params["grid_count"] == 5
    # 验证变体 1 解析后 grid_count=50
    config1 = QSModelConfig.model_validate(variants[1])
    resolved1 = resolve_variables(config1)
    assert resolved1.base_strategy.params["grid_count"] == 50


def test_ab_variants_new_param():
    """param_name 不在 base params 中时新增参数定义。"""
    base = generate_classic_variant("BTC-USDT", 0)
    # fast_period 不在 classic_variant 的 params 中
    variants = generate_ab_variants(base, "fast_period", [5, 10, 20])
    for i, v in enumerate([5, 10, 20]):
        assert variants[i]["params"]["fast_period"]["value"] == v
        assert variants[i]["params"]["fast_period"]["type"] == "int"


def test_ab_variants_float_type():
    """float 值时参数 type 设置为 float。"""
    base = generate_classic_variant("BTC-USDT", 0)
    variants = generate_ab_variants(base, "threshold", [0.05, 0.1])
    assert variants[0]["params"]["threshold"]["type"] == "float"
    assert variants[1]["params"]["threshold"]["type"] == "float"


# ============================================================
# 6. QSModelConfig schema 验证
# ============================================================


def test_classic_variant_validates_qsm():
    """generate_classic_variant 输出可被 QSModelConfig 验证。"""
    for seed in range(6):
        qsm = generate_classic_variant("BTC-USDT", seed)
        config = QSModelConfig.model_validate(qsm)
        assert config.meta.name == f"classic_grid_{seed}"
        assert config.logic.base_strategy.kind == "grid"
        assert config.risk_filter is not None


def test_dsl_innovation_validates_qsm():
    """generate_dsl_innovation 输出可被 QSModelConfig 验证。"""
    for seed in range(3):
        qsm = generate_dsl_innovation("BTC-USDT", seed)
        config = QSModelConfig.model_validate(qsm)
        assert len(config.logic.rules) >= 1
        assert config.risk_filter is not None


def test_backtest_candidates_all_validate_qsm():
    """所有回测候选可被 QSModelConfig 验证。"""
    candidates = generate_backtest_candidates("BTC-USDT")
    for c in candidates:
        QSModelConfig.model_validate(c)


def test_ab_variants_all_validate_qsm():
    """所有 A/B 变体可被 QSModelConfig 验证。"""
    base = generate_classic_variant("BTC-USDT", 0)
    variants = generate_ab_variants(base, "grid_count", [5, 10, 20])
    for v in variants:
        QSModelConfig.model_validate(v)


def test_all_generators_have_risk_filter():
    """所有生成器输出的 QSModelConfig 都含 risk_filter 段（SubTask 8.6）。"""
    # classic_variant
    qsm = generate_classic_variant("BTC-USDT", 0)
    assert qsm["risk_filter"] is not None
    assert qsm["risk_filter"]["daily_max_loss"] == 10.0
    assert qsm["risk_filter"]["stop_loss"] == 0.05
    assert qsm["risk_filter"]["take_profit"] == 0.1

    # dsl_innovation
    qsm = generate_dsl_innovation("BTC-USDT", 0)
    assert qsm["risk_filter"] is not None

    # backtest_candidates
    for c in generate_backtest_candidates("BTC-USDT"):
        assert c["risk_filter"] is not None

    # ab_variants
    base = generate_classic_variant("BTC-USDT", 0)
    for v in generate_ab_variants(base, "grid_count", [5, 10]):
        assert v["risk_filter"] is not None


def test_validate_qsm_helper():
    """validate_qsm 辅助函数正确返回 True/False。"""
    qsm = generate_classic_variant("BTC-USDT", 0)
    assert validate_qsm(qsm) is True

    # 非法 QSModel（缺 meta）应返回 False
    assert validate_qsm({"params": {}}) is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
