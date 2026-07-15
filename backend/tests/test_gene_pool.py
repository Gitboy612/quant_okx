"""Task 10: 基因池读写与反馈闭环测试。

测试用例：
1. test_gene_pool_read_write: 写入 gene_pool.json 后能正确读取
2. test_quality_strategy_added_to_pool: 优质策略（夏普>1.0, 回撤<20%）加入 genes
3. test_poor_strategy_blacklisted: 劣质策略（夏普<0）加入 blacklist
4. test_generator_prefers_gene_pool: gene_pool 有该 symbol 基因时，生成器基于基因微调
5. test_blacklisted_not_regenerated: 黑名单中的参数组合不再生成
6. test_generator_output_valid_qsm: 生成器输出通过 QSModelConfig.model_validate

导入风格参考 test_qsm_generator.py：sys.path 注入 backend 根目录。
"""
import sys
import os

# 注入 backend 根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from dsl.schema import QSModelConfig
from research.qsm_generator import (
    load_gene_pool,
    save_gene_pool,
    get_gene_from_pool,
    add_gene_to_pool,
    add_to_blacklist,
    is_blacklisted,
    compute_logic_hash,
    compute_param_fingerprint,
    generate_classic_variant,
    generate_dsl_innovation,
    validate_qsm,
)
import research.qsm_generator as qsm_generator


# ============================================================
# 测试夹具：每个测试用独立的 gene_pool.json（避免污染）
# ============================================================


@pytest.fixture
def isolated_gene_pool(tmp_path):
    """重定向 GENE_POOL_FILE 到临时目录，确保测试隔离。"""
    original = qsm_generator.GENE_POOL_FILE
    pool_file = tmp_path / "gene_pool.json"
    qsm_generator.GENE_POOL_FILE = pool_file
    yield pool_file
    qsm_generator.GENE_POOL_FILE = original


# ============================================================
# 1. test_gene_pool_read_write
# ============================================================


def test_gene_pool_read_write(isolated_gene_pool):
    """写入 gene_pool.json 后能正确读取。"""
    pool = {
        "version": "1.0",
        "updated_at": "2026-07-12T00:00:00+00:00",
        "genes": [
            {
                "gene_id": "G20260712-001",
                "symbol": "BTC-USDT",
                "metrics": {"sharpe": 1.5},
            }
        ],
        "blacklist": [],
    }
    save_gene_pool(pool)

    loaded = load_gene_pool()
    assert loaded["version"] == "1.0"
    assert len(loaded["genes"]) == 1
    assert loaded["genes"][0]["gene_id"] == "G20260712-001"
    assert loaded["genes"][0]["symbol"] == "BTC-USDT"
    assert loaded["genes"][0]["metrics"]["sharpe"] == 1.5


def test_load_gene_pool_missing_file(isolated_gene_pool):
    """gene_pool.json 不存在时返回空结构。"""
    loaded = load_gene_pool()
    assert loaded["version"] == "1.0"
    assert loaded["genes"] == []
    assert loaded["blacklist"] == []


# ============================================================
# 2. test_quality_strategy_added_to_pool
# ============================================================


def test_quality_strategy_added_to_pool(isolated_gene_pool):
    """优质策略（夏普>1.0, 回撤<20%）加入 genes。"""
    qsm = generate_classic_variant("BTC-USDT", 0)
    gene = {
        "symbol": "BTC-USDT",
        "strategy_type": "composable",
        "qs_model_config": qsm,
        "metrics": {
            "sharpe": 1.5,
            "max_drawdown": 0.12,
            "total_return": 0.25,
            "win_rate": 0.6,
        },
        "evaluated_at": "2026-07-22T00:00:00+00:00",
        "run_days": 10,
        "strategy_instance_id": 123,
    }
    add_gene_to_pool(gene)

    loaded = load_gene_pool()
    assert len(loaded["genes"]) == 1
    assert loaded["genes"][0]["symbol"] == "BTC-USDT"
    assert loaded["genes"][0]["metrics"]["sharpe"] == 1.5
    assert loaded["genes"][0]["metrics"]["max_drawdown"] == 0.12
    assert "gene_id" in loaded["genes"][0]
    assert loaded["genes"][0]["gene_id"].startswith("G")


def test_get_gene_from_pool_returns_matching_symbol(isolated_gene_pool):
    """get_gene_from_pool 返回匹配 symbol 的优质基因。"""
    qsm = generate_classic_variant("ETH-USDT", 0)
    gene = {
        "gene_id": "G20260712-001",
        "symbol": "ETH-USDT",
        "strategy_type": "composable",
        "qs_model_config": qsm,
        "metrics": {"sharpe": 1.5, "max_drawdown": 0.12, "total_return": 0.25, "win_rate": 0.6},
        "evaluated_at": "2026-07-22T00:00:00+00:00",
        "run_days": 10,
        "strategy_instance_id": 123,
    }
    add_gene_to_pool(gene)

    result = get_gene_from_pool("ETH-USDT")
    assert result is not None
    assert result["symbol"] == "ETH-USDT"
    assert result["metrics"]["sharpe"] == 1.5


def test_get_gene_from_pool_returns_none_when_no_match(isolated_gene_pool):
    """gene_pool 中无该 symbol 基因时返回 None。"""
    result = get_gene_from_pool("BTC-USDT")
    assert result is None


# ============================================================
# 3. test_poor_strategy_blacklisted
# ============================================================


def test_poor_strategy_blacklisted(isolated_gene_pool):
    """劣质策略（夏普<0）加入 blacklist。"""
    qsm = generate_classic_variant("BTC-USDT", 0)
    add_to_blacklist(qsm, "sharpe < 0")

    loaded = load_gene_pool()
    assert len(loaded["blacklist"]) == 1
    assert loaded["blacklist"][0]["reason"] == "sharpe < 0"
    assert "blacklisted_at" in loaded["blacklist"][0]
    # 黑名单条目含 logic_hash 和 param_fingerprint 供 is_blacklisted 检查
    assert "logic_hash" in loaded["blacklist"][0]
    assert "param_fingerprint" in loaded["blacklist"][0]


def test_is_blacklisted_returns_true_for_blacklisted(isolated_gene_pool):
    """is_blacklisted 对黑名单中的参数组合返回 True。"""
    qsm = generate_classic_variant("BTC-USDT", 0)
    add_to_blacklist(qsm, "sharpe < 0")

    assert is_blacklisted(qsm) is True


def test_is_blacklisted_returns_false_for_clean(isolated_gene_pool):
    """is_blacklisted 对未拉黑的参数组合返回 False。"""
    qsm = generate_classic_variant("BTC-USDT", 0)
    assert is_blacklisted(qsm) is False


def test_blacklist_by_param_fingerprint(isolated_gene_pool):
    """黑名单条目的 logic_hash 和 param_fingerprint 都匹配时判定为黑名单。"""
    import copy as _copy
    qsm1 = generate_classic_variant("BTC-USDT", 0)
    add_to_blacklist(qsm1, "sharpe < 0")

    # 同参数组合的独立副本 → logic_hash 和 param_fingerprint 都匹配
    qsm2 = _copy.deepcopy(qsm1)
    assert is_blacklisted(qsm2) is True


# ============================================================
# 4. test_generator_prefers_gene_pool
# ============================================================


def test_generator_prefers_gene_pool(isolated_gene_pool):
    """gene_pool 有该 symbol 基因时，生成器基于基因微调（而非从零生成）。"""
    # 存入一个优质基因（ETH-USDT，grid_count=20）
    base_qsm = generate_classic_variant("ETH-USDT", 1)  # seed=1 → grid_count=20
    original_grid_count = base_qsm["params"]["grid_count"]["value"]
    gene = {
        "gene_id": "G20260712-001",
        "symbol": "ETH-USDT",
        "strategy_type": "composable",
        "qs_model_config": base_qsm,
        "metrics": {"sharpe": 1.5, "max_drawdown": 0.12, "total_return": 0.25, "win_rate": 0.6},
        "evaluated_at": "2026-07-22T00:00:00+00:00",
        "run_days": 10,
        "strategy_instance_id": 123,
    }
    add_gene_to_pool(gene)

    # 生成器应基于基因微调（seed=0 → +10% 扰动）
    new_qsm = generate_classic_variant("ETH-USDT", 0)

    # 验证 meta.name 含 _gene_ 标记（来自基因池）
    assert "_gene_" in new_qsm["meta"]["name"]

    # 验证参数被 +10% 扰动（grid_count: 20 * 1.1 = 22）
    new_grid_count = new_qsm["params"]["grid_count"]["value"]
    expected = int(round(original_grid_count * 1.1))
    assert new_grid_count == expected

    # 验证是合法 QSModelConfig
    assert validate_qsm(new_qsm) is True


def test_generator_falls_back_when_no_gene(isolated_gene_pool):
    """gene_pool 无该 symbol 基因时，生成器走常规路径。"""
    qsm = generate_classic_variant("BTC-USDT", 0)
    # 无 _gene_ 标记
    assert "_gene_" not in qsm["meta"]["name"]
    assert qsm["meta"]["name"] == "classic_grid_0"


def test_dsl_innovation_prefers_gene_pool(isolated_gene_pool):
    """generate_dsl_innovation 也优先用基因池基因微调。"""
    base_qsm = generate_dsl_innovation("ETH-USDT", 0)
    original_ema_period = base_qsm["params"]["ema_period"]["value"]
    gene = {
        "gene_id": "G20260712-001",
        "symbol": "ETH-USDT",
        "strategy_type": "composable",
        "qs_model_config": base_qsm,
        "metrics": {"sharpe": 1.5, "max_drawdown": 0.12, "total_return": 0.25, "win_rate": 0.6},
        "evaluated_at": "2026-07-22T00:00:00+00:00",
        "run_days": 10,
        "strategy_instance_id": 123,
    }
    add_gene_to_pool(gene)

    new_qsm = generate_dsl_innovation("ETH-USDT", 0)
    assert "_gene_" in new_qsm["meta"]["name"]
    # seed=0 → +10% 扰动（ema_period: 20 * 1.1 = 22）
    new_ema = new_qsm["params"]["ema_period"]["value"]
    expected = int(round(original_ema_period * 1.1))
    assert new_ema == expected
    assert validate_qsm(new_qsm) is True


# ============================================================
# 5. test_blacklisted_not_regenerated
# ============================================================


def test_blacklisted_not_regenerated(isolated_gene_pool):
    """黑名单中的参数组合不再生成（生成器返回 None）。"""
    # 生成一个 QSModel 并加入黑名单
    qsm = generate_classic_variant("BTC-USDT", 0)
    assert qsm is not None
    add_to_blacklist(qsm, "sharpe < 0")

    # 再次生成同 symbol 同 seed → 参数组合相同 → 在黑名单中 → 返回 None
    result = generate_classic_variant("BTC-USDT", 0)
    assert result is None


def test_blacklisted_dsl_not_regenerated(isolated_gene_pool):
    """黑名单中的 DSL 创新策略不再生成。"""
    qsm = generate_dsl_innovation("BTC-USDT", 0)
    assert qsm is not None
    add_to_blacklist(qsm, "max_drawback > 0.30")

    result = generate_dsl_innovation("BTC-USDT", 0)
    assert result is None


def test_different_seed_not_blacklisted(isolated_gene_pool):
    """不同参数组合（不同 seed）不在黑名单中，可正常生成。"""
    # 将 seed=0 的变体加入黑名单
    qsm0 = generate_classic_variant("BTC-USDT", 0)
    add_to_blacklist(qsm0, "sharpe < 0")

    # seed=1 参数不同（grid_count=20 vs 10），不在黑名单中 → 正常生成
    result = generate_classic_variant("BTC-USDT", 1)
    assert result is not None
    assert result["params"]["grid_count"]["value"] == 20


# ============================================================
# 6. test_generator_output_valid_qsm
# ============================================================


def test_generator_output_valid_qsm(isolated_gene_pool):
    """生成器输出通过 QSModelConfig.model_validate。"""
    # 经典变体所有 seed
    for seed in range(6):
        qsm = generate_classic_variant("BTC-USDT", seed)
        assert qsm is not None, f"classic seed={seed} 返回 None"
        QSModelConfig.model_validate(qsm)

    # DSL 创新所有 seed
    for seed in range(3):
        qsm = generate_dsl_innovation("BTC-USDT", seed)
        assert qsm is not None, f"dsl seed={seed} 返回 None"
        QSModelConfig.model_validate(qsm)


def test_perturbed_gene_validates_qsm(isolated_gene_pool):
    """基于基因微调的变体也通过 QSModelConfig 验证。"""
    base_qsm = generate_classic_variant("ETH-USDT", 1)
    gene = {
        "gene_id": "G20260712-001",
        "symbol": "ETH-USDT",
        "strategy_type": "composable",
        "qs_model_config": base_qsm,
        "metrics": {"sharpe": 1.5, "max_drawdown": 0.12, "total_return": 0.25, "win_rate": 0.6},
        "evaluated_at": "2026-07-22T00:00:00+00:00",
        "run_days": 10,
        "strategy_instance_id": 123,
    }
    add_gene_to_pool(gene)

    for seed in range(6):
        qsm = generate_classic_variant("ETH-USDT", seed)
        assert qsm is not None
        QSModelConfig.model_validate(qsm)


# ============================================================
# 辅助：compute_logic_hash / compute_param_fingerprint
# ============================================================


def test_compute_logic_hash():
    """compute_logic_hash 返回 logic 段 SHA-256。"""
    qsm = generate_classic_variant("BTC-USDT", 0)
    h = compute_logic_hash(qsm)
    assert h is not None
    assert len(h) == 64  # SHA-256 hex 长度


def test_compute_param_fingerprint():
    """compute_param_fingerprint 返回参数组合指纹。"""
    qsm1 = generate_classic_variant("BTC-USDT", 0)
    qsm2 = generate_classic_variant("BTC-USDT", 0)
    qsm3 = generate_classic_variant("BTC-USDT", 1)

    fp1 = compute_param_fingerprint(qsm1)
    fp2 = compute_param_fingerprint(qsm2)
    fp3 = compute_param_fingerprint(qsm3)

    # 相同参数 → 相同指纹
    assert fp1 == fp2
    # 不同参数 → 不同指纹
    assert fp1 != fp3


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
