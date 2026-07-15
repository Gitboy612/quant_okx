"""QSModel 生成器模块。

按 spec.md「Requirement: 定时任务 QSModel 研究闭环」实现四类生成器，
让定时研究任务真正用 QSModel 生成创新策略，而非仅监控固定基础策略。

四类生成器：
- 经典变体（generate_classic_variant）：base_strategy 调参生成 QSModelConfig
- DSL 创新（generate_dsl_innovation）：base_strategy + rules 组合生成复合策略
- 回测筛选（generate_backtest_candidates）：生成多候选供 dry_run 筛选
- 参数 A/B（generate_ab_variants）：同 logic 不同 params 并行对比

所有生成器返回合法 QSModelConfig dict（四段式：meta/params/logic/risk_filter），
并调用 build_risk_filter 生成统一风控段。

变量引用约定：
- $params.xxx 引用 params 段定义的参数值
- $meta.xxx 引用 meta 段字段（如 $meta.base_symbol）
resolve_variables() 会递归替换这些引用为实际值。
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dsl.schema import QSModelConfig


# ============================================================
# 公共：风控段生成
# ============================================================


def build_risk_filter(
    daily_max_loss: float = 10.0,
    stop_loss: float = 0.05,
    take_profit: float = 0.1,
) -> dict:
    """生成 QSModelConfig 的 risk_filter 段。

    所有生成器输出的 QSModelConfig 都含 risk_filter 段，统一调本函数生成。

    Args:
        daily_max_loss: 每日最大亏损（USDT），默认 10.0
        stop_loss: 止损比例（小数，0.05=5%），默认 0.05
        take_profit: 止盈比例（小数，0.1=10%），默认 0.1

    Returns:
        dict，符合 RiskFilter schema 的 risk_filter 段
    """
    return {
        "daily_max_loss": daily_max_loss,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
    }


# ============================================================
# SubTask 8.2: 经典变体生成器
# ============================================================


# 经典变体参数组合表：variant_seed 决定 grid_count/order_qty/lever 组合。
# 每个 seed 对应一组差异化参数，覆盖从保守（少网格小单量低杠杆）
# 到激进（多网格大单量高杠杆）的不同风格。
_CLASSIC_VARIANTS = [
    {"grid_count": 10, "order_qty": 0.1, "lever": 1},     # 保守
    {"grid_count": 20, "order_qty": 0.5, "lever": 5},     # 中等
    {"grid_count": 50, "order_qty": 0.1, "lever": 10},    # 高杠杆
    {"grid_count": 15, "order_qty": 0.2, "lever": 2},     # 偏保守
    {"grid_count": 30, "order_qty": 0.3, "lever": 3},     # 偏中等
    {"grid_count": 25, "order_qty": 0.05, "lever": 1},    # 小单量
]


def generate_classic_variant(symbol: str, variant_seed: int) -> dict:
    """经典变体生成器：基于 base_strategy 调参生成 QSModelConfig。

    variant_seed 决定参数组合（grid_count/order_qty/lever），
    通过 $params.xxx 变量引用将可变参数注入 base_strategy.params。

    Args:
        symbol: 交易对，如 "BTC-USDT"
        variant_seed: 变体种子，决定参数组合（取模循环）

    Returns:
        QSModelConfig dict，含四段式结构：
        - meta: name=f"classic_grid_{seed}", version="1.0"
        - params: grid_count / order_qty / lever 三个可变参数
        - logic: base_strategy.kind="grid" + 引用 $params.xxx
        - risk_filter: 调 build_risk_filter 生成
    """
    # Task 10: 优先从基因池取优质基因，基于基因微调参数
    gene = get_gene_from_pool(symbol)
    if gene is not None:
        qsm = _perturb_from_gene(gene, variant_seed)
        if qsm is not None and not is_blacklisted(qsm):
            return qsm

    v = _CLASSIC_VARIANTS[variant_seed % len(_CLASSIC_VARIANTS)]

    result = {
        "qs_model_version": "2.0",
        "meta": {
            "name": f"classic_grid_{variant_seed}",
            "version": "1.0",
            "base_symbol": symbol,
            "asset_class": "CRYPTO",
        },
        "params": {
            "grid_count": {
                "label": "网格数量",
                "value": v["grid_count"],
                "type": "int",
                "range": [5, 100],
                "unit": "格",
                "description": "网格档位数量",
            },
            "order_qty": {
                "label": "单格数量",
                "value": v["order_qty"],
                "type": "float",
                "range": [0.001, 10.0],
                "unit": "币",
                "description": "单格交易量",
            },
            "lever": {
                "label": "杠杆倍数",
                "value": v["lever"],
                "type": "int",
                "range": [1, 20],
                "unit": "x",
                "description": "杠杆倍数（策略级参数，控制风险敞口）",
            },
        },
        "logic": {
            "version": "1.0",
            "base_strategy": {
                "kind": "grid",
                "params": {
                    "upper_price": 50000,
                    "lower_price": 40000,
                    "grid_count": "$params.grid_count",
                    "order_qty": "$params.order_qty",
                    "symbol": "$meta.base_symbol",
                },
            },
            "rules": [],
        },
        "risk_filter": build_risk_filter(),
    }

    # Task 10: 黑名单检查
    if is_blacklisted(result):
        return None
    return result


# ============================================================
# SubTask 8.3: DSL 创新生成器
# ============================================================


def _build_cross_above_rule(symbol_ref: str, period: int) -> dict:
    """构造 cross_above(price, ema) → pause_orders 规则。

    价格上穿均线时暂停挂单，规避单边上涨风险。

    Args:
        symbol_ref: 交易对引用（$meta.base_symbol 或字面量）
        period: EMA 周期
    """
    return {
        "name": "价格上涨穿均线暂停",
        "when": {
            "mode": "condition",
            "condition": {
                "kind": "cross_above",
                "args": {
                    "indicator_a": {
                        "kind": "price_last",
                        "args": {"symbol": symbol_ref},
                    },
                    "indicator_b": {
                        "kind": "ema",
                        "args": {
                            "symbol": symbol_ref,
                            "period": period,
                            "window": "1h",
                        },
                    },
                },
            },
        },
        "then": [{"kind": "pause_orders"}],
    }


def _build_cross_below_rsi_rule(symbol_ref: str, period: int) -> dict:
    """构造 cross_below(price, rsi) → rebalance_position 规则。

    RSI 超卖时再平衡持仓，低吸修正。

    Args:
        symbol_ref: 交易对引用
        period: RSI 周期
    """
    return {
        "name": "RSI 超卖再平衡",
        "when": {
            "mode": "condition",
            "condition": {
                "kind": "cross_below",
                "args": {
                    "indicator_a": {
                        "kind": "price_last",
                        "args": {"symbol": symbol_ref},
                    },
                    "indicator_b": {
                        "kind": "rsi",
                        "args": {"symbol": symbol_ref, "period": period},
                    },
                },
            },
        },
        "then": [
            {"kind": "rebalance_position", "args": {"mode": "to_theoretical"}},
        ],
    }


def _build_volatility_hold_rule(symbol_ref: str, period: int) -> dict:
    """构造 in_range(volatility, 0, 0.02) → hold_position 规则。

    低波动时持有不动，避免频繁调仓。

    Args:
        symbol_ref: 交易对引用
        period: 波动率周期
    """
    return {
        "name": "低波动持有",
        "when": {
            "mode": "condition",
            "condition": {
                "kind": "in_range",
                "args": {
                    "indicator": {
                        "kind": "volatility",
                        "args": {
                            "symbol": symbol_ref,
                            "period": period,
                            "window": "1h",
                        },
                    },
                    "lower": 0,
                    "upper": 0.02,
                },
            },
        },
        "then": [{"kind": "hold_position"}],
    }


def generate_dsl_innovation(symbol: str, innovation_seed: int) -> dict:
    """DSL 创新生成器：base_strategy + rules 组合生成复合策略。

    innovation_seed 决定规则组合：
    - seed=0: grid + cross_above(price, ema) → pause_orders（价格上涨穿均线暂停）
    - seed=1: grid + cross_below(price, rsi) → rebalance_position（RSI 超卖再平衡）
    - seed=2: trend + in_range(volatility, 0, 0.02) → hold_position（低波动持有）

    生成真正的 DSL 复合策略（base_strategy + rules 数组），
    rules 含 condition + action。

    Args:
        symbol: 交易对
        innovation_seed: 创新种子（0/1/2 对应上述三种组合，>2 取模）

    Returns:
        QSModelConfig dict，logic 段含 base_strategy + rules 数组
    """
    # Task 10: 优先从基因池取优质基因，基于基因微调参数
    gene = get_gene_from_pool(symbol)
    if gene is not None:
        qsm = _perturb_from_gene(gene, innovation_seed)
        if qsm is not None and not is_blacklisted(qsm):
            return qsm

    seed = innovation_seed % 3
    symbol_ref = "$meta.base_symbol"

    if seed == 0:
        # grid + cross_above(price, ema) → pause_orders
        meta_name = f"dsl_cross_above_ema_{innovation_seed}"
        base_strategy = {
            "kind": "grid",
            "params": {
                "upper_price": 50000,
                "lower_price": 40000,
                "grid_count": 10,
                "order_qty": 0.01,
                "symbol": symbol_ref,
            },
        }
        rules = [_build_cross_above_rule(symbol_ref, 20)]
        params = {
            "ema_period": {
                "label": "EMA周期",
                "value": 20,
                "type": "int",
                "range": [5, 100],
                "unit": "根",
            },
        }

    elif seed == 1:
        # grid + cross_below(price, rsi) → rebalance_position
        meta_name = f"dsl_cross_below_rsi_{innovation_seed}"
        base_strategy = {
            "kind": "grid",
            "params": {
                "upper_price": 50000,
                "lower_price": 40000,
                "grid_count": 10,
                "order_qty": 0.01,
                "symbol": symbol_ref,
            },
        }
        rules = [_build_cross_below_rsi_rule(symbol_ref, 30)]
        params = {
            "rsi_period": {
                "label": "RSI周期",
                "value": 30,
                "type": "int",
                "range": [6, 50],
                "unit": "根",
            },
        }

    else:
        # seed == 2: trend + in_range(volatility, 0, 0.02) → hold_position
        meta_name = f"dsl_volatility_hold_{innovation_seed}"
        base_strategy = {
            "kind": "trend",
            "params": {
                "fast_period": 5,
                "slow_period": 20,
                "symbol": symbol_ref,
            },
        }
        rules = [_build_volatility_hold_rule(symbol_ref, 20)]
        params = {
            "vol_period": {
                "label": "波动率周期",
                "value": 20,
                "type": "int",
                "range": [5, 100],
                "unit": "根",
            },
        }

    result = {
        "qs_model_version": "2.0",
        "meta": {
            "name": meta_name,
            "version": "1.0",
            "base_symbol": symbol,
            "asset_class": "CRYPTO",
        },
        "params": params,
        "logic": {
            "version": "1.0",
            "base_strategy": base_strategy,
            "rules": rules,
        },
        "risk_filter": build_risk_filter(),
    }

    # Task 10: 黑名单检查
    if is_blacklisted(result):
        return None
    return result


# ============================================================
# SubTask 8.4: 回测筛选生成器
# ============================================================


def generate_backtest_candidates(symbol: str) -> list[dict]:
    """回测筛选生成器：生成多个候选 QSModel。

    混合经典变体与 DSL 创新策略，返回 5-10 个候选，
    供调用方逐个调 dry_run 回测筛选（按夏普/回撤等指标）。

    Args:
        symbol: 交易对

    Returns:
        QSModelConfig dict 列表，每个候选配置不同参数组合
    """
    candidates: list[dict] = []

    # 3 个经典变体（保守/中等/激进）
    for seed in range(3):
        candidates.append(generate_classic_variant(symbol, seed))

    # 3 个 DSL 创新（三种规则组合）
    for seed in range(3):
        candidates.append(generate_dsl_innovation(symbol, seed))

    # 2 个额外经典变体（不同参数组合）
    for seed in range(3, 5):
        candidates.append(generate_classic_variant(symbol, seed))

    return candidates


# ============================================================
# SubTask 8.5: 参数 A/B 生成器
# ============================================================


def generate_ab_variants(
    base_qsm: dict,
    param_name: str,
    values: list,
) -> list[dict]:
    """参数 A/B 生成器：复制 base_qsm 生成不同参数变体。

    用 $params.xxx 变量引用生成不同参数变体（同 logic 不同 params）。
    每个 variant 复制 base_qsm，仅修改 params[param_name].value，
    logic 段保持不变（其中的 $params.xxx 引用会自动解析为新值）。

    Args:
        base_qsm: 基础 QSModelConfig dict
        param_name: 参数名，如 "fast_period"
        values: 参数值列表，如 [5, 10, 20]

    Returns:
        QSModelConfig dict 列表，每个变体 meta.name 加后缀 _ab_{value}
    """
    variants: list[dict] = []
    base_name = base_qsm.get("meta", {}).get("name", "base")

    for value in values:
        variant = copy.deepcopy(base_qsm)
        # 确保 params 段存在
        if "params" not in variant:
            variant["params"] = {}

        # 更新或新增参数定义
        if param_name in variant["params"]:
            variant["params"][param_name]["value"] = value
        else:
            variant["params"][param_name] = {
                "label": param_name,
                "value": value,
                "type": "int" if isinstance(value, int) and not isinstance(value, bool) else "float",
            }

        # meta.name 加后缀 _ab_{value}
        variant["meta"]["name"] = f"{base_name}_ab_{value}"
        variants.append(variant)

    return variants


# ============================================================
# 便捷：验证生成器输出的 QSModelConfig 合法性
# ============================================================


def validate_qsm(qsm: dict) -> bool:
    """用 QSModelConfig Pydantic schema 验证生成的 dict 是否合法。

    供生成器调用方做防御性校验。仅校验 Pydantic schema 结构，
    不做 DSL 静态校验（DSLValidator）。

    Args:
        qsm: QSModelConfig dict

    Returns:
        True 合法 / False 非法
    """
    try:
        QSModelConfig.model_validate(qsm)
        return True
    except Exception:
        return False


# ============================================================
# Task 10: 基因池读写与黑名单检查
# ============================================================


# 基因池文件路径（与 run_iteration.py 的 REPORT_DIR 一致）
_BACKEND_DIR = Path(__file__).resolve().parents[1]
GENE_POOL_FILE = _BACKEND_DIR / "tests" / "reports" / "strategy_research" / "gene_pool.json"

# 基因池读写锁（保证线程安全）
_gene_pool_lock = threading.Lock()

# 优质判定阈值
QUALITY_MIN_SHARPE = 1.0
QUALITY_MAX_DRAWDOWN = 0.20
QUALITY_MIN_TOTAL_RETURN = 0.05
# 劣质判定阈值
POOR_MAX_SHARPE = 0.0
POOR_MAX_DRAWDOWN = 0.30


def _utc_now() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    """datetime → ISO 字符串。"""
    return dt.isoformat() if dt else None


def _empty_pool() -> dict:
    """返回空的基因池结构。"""
    return {
        "version": "1.0",
        "updated_at": _iso(_utc_now()),
        "genes": [],
        "blacklist": [],
    }


def _load_gene_pool_unlocked() -> dict:
    """读取 gene_pool.json（不加锁，供内部调用）。"""
    if not GENE_POOL_FILE.exists():
        return _empty_pool()
    try:
        with open(GENE_POOL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_pool()


def _save_gene_pool_unlocked(pool: dict):
    """原子写入 gene_pool.json（不加锁，供内部调用）。

    先写临时文件再 os.replace，保证原子性。
    """
    GENE_POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    pool["updated_at"] = _iso(_utc_now())
    tmp_file = GENE_POOL_FILE.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, GENE_POOL_FILE)


def load_gene_pool() -> dict:
    """读取 gene_pool.json（线程安全）。

    不存在或解析失败时返回空结构（version/genes/blacklist）。
    """
    with _gene_pool_lock:
        return _load_gene_pool_unlocked()


def save_gene_pool(pool: dict):
    """原子写入 gene_pool.json（线程安全）。"""
    with _gene_pool_lock:
        _save_gene_pool_unlocked(pool)


def _next_gene_id(pool: dict) -> str:
    """生成下一个 gene_id，格式 G{YYYYMMDD}-{seq:03d}。"""
    today = _utc_now().strftime("%Y%m%d")
    prefix = f"G{today}-"
    seq = 1
    existing_ids = {g.get("gene_id", "") for g in pool.get("genes", [])}
    existing_ids |= {b.get("gene_id", "") for b in pool.get("blacklist", [])}
    while f"{prefix}{seq:03d}" in existing_ids:
        seq += 1
    return f"{prefix}{seq:03d}"


def get_gene_from_pool(symbol: str) -> dict | None:
    """从基因池取该 symbol 的优质基因（未在黑名单中）。

    遍历 genes 数组，返回第一个匹配 symbol 且未被拉黑的基因。
    无匹配时返回 None。
    """
    pool = load_gene_pool()
    blacklist_ids = {b.get("gene_id") for b in pool.get("blacklist", [])}
    for gene in pool.get("genes", []):
        if gene.get("symbol") == symbol and gene.get("gene_id") not in blacklist_ids:
            return gene
    return None


def add_gene_to_pool(gene: dict):
    """将优质基因加入 gene_pool.json 的 genes 数组（线程安全）。

    若 gene 缺少 gene_id，自动生成。
    """
    with _gene_pool_lock:
        pool = _load_gene_pool_unlocked()
        if "genes" not in pool:
            pool["genes"] = []
        if "gene_id" not in gene:
            gene["gene_id"] = _next_gene_id(pool)
        pool["genes"].append(gene)
        _save_gene_pool_unlocked(pool)


def add_to_blacklist(
    qs_model_config: dict,
    reason: str,
    gene_id: str | None = None,
    **extra,
):
    """将劣质策略参数组合加入黑名单（线程安全）。

    基于 logic_hash 和参数组合指纹标识，供 is_blacklisted 检查。

    Args:
        qs_model_config: 劣质策略的 QSModelConfig dict
        reason: 拉黑原因，如 "sharpe < 0"
        gene_id: 可选的基因 ID
        **extra: 额外字段，如 strategy_instance_id
    """
    with _gene_pool_lock:
        pool = _load_gene_pool_unlocked()
        if "blacklist" not in pool:
            pool["blacklist"] = []
        entry = {
            "gene_id": gene_id or _next_gene_id(pool),
            "reason": reason,
            "blacklisted_at": _iso(_utc_now()),
            "logic_hash": compute_logic_hash(qs_model_config),
            "param_fingerprint": compute_param_fingerprint(qs_model_config),
        }
        entry.update(extra)
        pool["blacklist"].append(entry)
        _save_gene_pool_unlocked(pool)


def compute_logic_hash(qs_model_config: dict) -> str | None:
    """计算 qs_model_config.logic 段的 SHA-256 哈希。

    与 run_iteration.py 中 _compute_logic_hash 逻辑一致。
    """
    logic = qs_model_config.get("logic", {}) or {}
    if not logic:
        return None
    canonical = json.dumps(logic, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_param_fingerprint(qs_model_config: dict) -> str:
    """计算 qs_model_config.params 段的参数组合指纹（SHA-256）。

    只取每个参数的 value 构建指纹，忽略 label/description 等显示字段。
    """
    params = qs_model_config.get("params", {}) or {}
    values = {}
    for k, v in params.items():
        if isinstance(v, dict) and "value" in v:
            values[k] = v["value"]
        else:
            values[k] = v
    canonical = json.dumps(values, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def is_blacklisted(qs_model_config: dict) -> bool:
    """检查 QSModel 是否在黑名单中（基于 logic_hash 和参数组合指纹同时匹配）。

    只有 logic_hash 和 param_fingerprint 都匹配同一条黑名单记录时才判定为黑名单，
    避免仅 logic 相同（如所有经典变体共享 grid 逻辑）就误杀不同参数组合。
    """
    pool = load_gene_pool()
    blacklist = pool.get("blacklist", [])
    logic_hash = compute_logic_hash(qs_model_config)
    param_fp = compute_param_fingerprint(qs_model_config)
    for entry in blacklist:
        if entry.get("logic_hash") == logic_hash and entry.get("param_fingerprint") == param_fp:
            return True
    return False


def _perturb_from_gene(gene: dict, seed: int) -> dict | None:
    """基于优质基因微调参数生成新变体（±10% 扰动）。

    从基因的 qs_model_config 深拷贝，对每个数值参数做 ±10% 扰动：
    - 偶数 seed → +10%
    - 奇数 seed → -10%
    int 类型参数四舍五入并限制在 range 范围内。

    Args:
        gene: 基因池中的优质基因（含 qs_model_config）
        seed: 种子，决定扰动方向

    Returns:
        微调后的 QSModelConfig dict，若基因无 qs_model_config 则返回 None
    """
    qsm = copy.deepcopy(gene.get("qs_model_config", {}))
    if not qsm:
        return None

    # 扰动方向：偶数 +10%，奇数 -10%
    factor = 1.1 if (seed % 2 == 0) else 0.9

    params = qsm.get("params", {})
    for param_def in params.values():
        if not isinstance(param_def, dict):
            continue
        value = param_def.get("value")
        # 布尔值不扰动（isinstance(True, int) 为 True，需先排除）
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            new_value = value * factor
            # int 类型保持整数
            if param_def.get("type") == "int":
                new_value = max(1, int(round(new_value)))
            # 限制在 range 范围内
            rng = param_def.get("range")
            if rng and len(rng) == 2:
                new_value = max(rng[0], min(rng[1], new_value))
            param_def["value"] = new_value

    # 更新 meta.name 标记来自基因池
    base_name = qsm.get("meta", {}).get("name", "gene_variant")
    qsm.setdefault("meta", {})["name"] = f"{base_name}_gene_{seed}"

    return qsm
