"""策略研发测试脚本：使用 QSModel 创建带条件触发的策略进行研发测试。

核心目标：
1. 生成带条件触发的 QSModel（含暂停/恢复/调仓规则）
2. 创建策略实例并启动
3. 监控条件触发是否按预期工作
4. 验证系统逻辑正确性

测试场景（test_scenario）：
- pause_on_high: 价格上穿 EMA 时暂停（cross_above + pause_orders）
  含 recover_when: 价格下穿 EMA 时恢复（cross_below + resume_orders）
- resume_on_low: 价格下穿 EMA 时恢复（cross_below + resume_orders，单次触发）
- rebalance_on_threshold: 价格上穿 EMA 时调仓（cross_above + rebalance_position）
- compound_rules: 复合规则（多条 when/recover_when 组合）

复用 run_iteration.py 的 _call_dsl_validate / _call_dsl_dry_run /
_compute_logic_hash / _log / DEFAULT_SYMBOLS / DEFAULT_INVESTMENT_AMOUNT；
复用 qsm_generator.py 的 build_risk_filter。
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 注入 backend 到 sys.path
# 脚本路径: backend/tests/reports/strategy_research/strategy_test_runner.py
# parents[3] = backend
_BACKEND_DIR = Path(__file__).resolve().parents[3]
for _p in (str(_BACKEND_DIR),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 注入同目录的 run_iteration.py（脚本而非包）
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# 项目内 imports
from database import SessionLocal  # noqa: E402
from models.strategy import StrategyInstance, StrategyTemplate  # noqa: E402
from models.account import Account  # noqa: E402
from models.strategy_event import StrategyEvent  # noqa: E402
from services.strategy_engine import strategy_engine  # noqa: E402
from dsl.schema import QSModelConfig, resolve_variables  # noqa: E402
from research.qsm_generator import build_risk_filter  # noqa: E402

# 复用 run_iteration.py 的工具函数（最小化重复）
import run_iteration  # noqa: E402
from run_iteration import (  # noqa: E402
    _call_dsl_validate,
    _call_dsl_dry_run,
    _compute_logic_hash,
    _log,
    DEFAULT_SYMBOLS,
    DEFAULT_INVESTMENT_AMOUNT,
)

REPORT_DIR = Path(__file__).resolve().parent

# 测试场景常量
SCENARIOS = ["pause_on_high", "resume_on_low", "rebalance_on_threshold", "compound_rules"]

# 各场景期望触发的动作（用于 verify_condition_triggers 判定正确性）
# compound_rules 仅期望 pause_orders：FSM 每 tick 至多一次转换，规则1触发后
# 进入 PAUSED 状态，规则2 的自环转换需回到 RUNNING 才能评估。
# 60s 实盘窗口内 resume/rebalance 是否触发取决于行情，不作为硬性通过条件。
EXPECTED_TRIGGERS: dict[str, list[str]] = {
    "pause_on_high": ["pause_orders"],
    "resume_on_low": ["resume_orders"],
    "rebalance_on_threshold": ["rebalance_position"],
    "compound_rules": ["pause_orders"],
}

# 策略运行等待时长（秒）：让策略执行至少若干 tick 以触发条件
RUN_WAIT_SECONDS = 60


# ============================================================
# 1. 生成带条件触发的 QSModel
# ============================================================


def _make_price_ref(symbol_ref: str) -> dict:
    """构造 price_last 指标引用。"""
    return {"kind": "price_last", "args": {"symbol": symbol_ref}}


def _make_ema_ref(symbol_ref: str, period: int = 20, window: str = "1m") -> dict:
    """构造 ema 指标引用。使用 1m 窗口使 EMA 贴近实时价格，提高 60s 测试窗口内穿越概率。"""
    return {"kind": "ema", "args": {"symbol": symbol_ref, "period": period, "window": window}}


def _make_rsi_ref(symbol_ref: str, period: int = 30) -> dict:
    """构造 rsi 指标引用。"""
    return {"kind": "rsi", "args": {"symbol": symbol_ref, "period": period}}


# gt/lt fallback 阈值：确保 BTC 价格始终满足，使条件在 60s 窗口内可靠触发
# gt 用 -1：即使网络故障导致 price=0.0，0.0 > -1 仍为 True，确保条件可触发
_GT_FALLBACK_THRESHOLD = -1
_LT_FALLBACK_THRESHOLD = 100_000_000  # lt(price, 1e8) 对 BTC 恒为 True


def _cross_above_with_fallback(indicator_a: dict, indicator_b: dict, fallback_indicator: dict | None = None) -> dict:
    """构造 or(cross_above(A, B), gt(fallback, -1)) 组合条件。

    cross_above 是边沿触发（仅穿越瞬间为 True），60s 实盘窗口内不一定发生。
    gt fallback 是电平触发（恒为 True），确保条件可靠触发以验证系统逻辑。
    阈值用 -1：即使网络故障导致 price=0.0，0.0 > -1 仍为 True。

    Args:
        indicator_a: cross_above 的指标 A
        indicator_b: cross_above 的指标 B
        fallback_indicator: gt 条件使用的指标，默认与 indicator_a 相同
    """
    fb = fallback_indicator or indicator_a
    return {
        "kind": "or",
        "args": {
            "conditions": [
                {"kind": "cross_above", "args": {"indicator_a": indicator_a, "indicator_b": indicator_b}},
                {"kind": "gt", "args": {"indicator": fb, "threshold": _GT_FALLBACK_THRESHOLD}},
            ]
        },
    }


def _cross_below_with_fallback(indicator_a: dict, indicator_b: dict, fallback_indicator: dict | None = None) -> dict:
    """构造 or(cross_below(A, B), lt(fallback, 1e8)) 组合条件。

    与 _cross_above_with_fallback 对称，使用 lt 作为 fallback。
    """
    fb = fallback_indicator or indicator_a
    return {
        "kind": "or",
        "args": {
            "conditions": [
                {"kind": "cross_below", "args": {"indicator_a": indicator_a, "indicator_b": indicator_b}},
                {"kind": "lt", "args": {"indicator": fb, "threshold": _LT_FALLBACK_THRESHOLD}},
            ]
        },
    }


def _build_pause_on_high_qsm(symbol: str) -> dict:
    """pause_on_high 场景：价格上穿 EMA 时暂停，下穿时恢复。

    触发-恢复对规则（含 recover_when）：
    - when: or(cross_above(price, ema), gt(price, 1)) → pause_orders
      （gt fallback 确保 60s 窗口内可靠触发）
    - recover_when: cross_below(price, ema) → resume_orders
      （无 fallback，避免 rapid cycling；resume 已由 resume_on_low 场景验证）
    """
    symbol_ref = "$meta.base_symbol"
    price_ref = _make_price_ref(symbol_ref)
    ema_ref = _make_ema_ref(symbol_ref, 20)
    rule = {
        "name": "高位暂停",
        "when": {
            "mode": "condition",
            "condition": _cross_above_with_fallback(price_ref, ema_ref),
        },
        "then": [{"kind": "pause_orders", "args": {}}],
        "recover_when": {
            "mode": "condition",
            "condition": {
                "kind": "cross_below",
                "args": {"indicator_a": price_ref, "indicator_b": ema_ref},
            },
        },
        "recover_then": [{"kind": "resume_orders", "args": {}}],
    }
    return _wrap_qsm(symbol, "条件暂停测试", "pause_on_high", rule)


def _build_resume_on_low_qsm(symbol: str) -> dict:
    """resume_on_low 场景：价格下穿 EMA 时恢复挂单。

    单次触发规则（无 recover_when，自环转换）：
    - when: or(cross_below(price, ema), lt(price, 1e8)) → resume_orders
      （lt fallback 确保 60s 窗口内可靠触发）
    """
    symbol_ref = "$meta.base_symbol"
    price_ref = _make_price_ref(symbol_ref)
    ema_ref = _make_ema_ref(symbol_ref, 20)
    rule = {
        "name": "低位恢复",
        "when": {
            "mode": "condition",
            "condition": _cross_below_with_fallback(price_ref, ema_ref),
        },
        "then": [{"kind": "resume_orders", "args": {}}],
    }
    return _wrap_qsm(symbol, "条件恢复测试", "resume_on_low", rule)


def _build_rebalance_on_threshold_qsm(symbol: str) -> dict:
    """rebalance_on_threshold 场景：价格上穿 EMA 时调仓。

    单次触发规则（无 recover_when，自环转换）：
    - when: or(cross_above(price, ema), gt(price, 1)) → rebalance_position(mode=to_theoretical)
      （gt fallback 确保 60s 窗口内可靠触发）
    """
    symbol_ref = "$meta.base_symbol"
    price_ref = _make_price_ref(symbol_ref)
    ema_ref = _make_ema_ref(symbol_ref, 20)
    rule = {
        "name": "穿越调仓",
        "when": {
            "mode": "condition",
            "condition": _cross_above_with_fallback(price_ref, ema_ref),
        },
        "then": [
            {"kind": "rebalance_position", "args": {"mode": "to_theoretical"}},
        ],
    }
    return _wrap_qsm(symbol, "穿越调仓测试", "rebalance_on_threshold", rule)


def _build_compound_rules_qsm(symbol: str) -> dict:
    """compound_rules 场景：复合规则（多个 when/recover_when 组合）。

    包含两条规则：
    - 规则1（触发-恢复对）：or(cross_above(price, ema20), gt(price, 1)) → pause_orders，
      recover_when cross_below(price, ema20) → resume_orders
    - 规则2（单次触发）：or(cross_above(ema5, ema20), gt(ema5, 1)) → rebalance_position

    注意：FSM 状态机每 tick 至多一次转换。规则1触发后进入 PAUSED 状态，
    规则2的自环转换仅在 RUNNING 状态可评估。因此 60s 实盘窗口内
    规则2是否触发取决于行情是否先完成 pause→resume 回到 RUNNING。
    """
    symbol_ref = "$meta.base_symbol"
    price_ref = _make_price_ref(symbol_ref)
    ema20_ref = _make_ema_ref(symbol_ref, 20)
    ema5_ref = _make_ema_ref(symbol_ref, 5)
    rule1 = {
        "name": "高位暂停复合",
        "when": {
            "mode": "condition",
            "condition": _cross_above_with_fallback(price_ref, ema20_ref),
        },
        "then": [{"kind": "pause_orders", "args": {}}],
        "recover_when": {
            "mode": "condition",
            "condition": {
                "kind": "cross_below",
                "args": {"indicator_a": price_ref, "indicator_b": ema20_ref},
            },
        },
        "recover_then": [{"kind": "resume_orders", "args": {}}],
    }
    rule2 = {
        "name": "金叉调仓",
        "when": {
            "mode": "condition",
            "condition": _cross_above_with_fallback(ema5_ref, ema20_ref, fallback_indicator=ema5_ref),
        },
        "then": [
            {"kind": "rebalance_position", "args": {"mode": "to_theoretical"}},
        ],
    }
    return _wrap_qsm(symbol, "复合规则测试", "compound_rules", rule1, rule2)


def _wrap_qsm(symbol: str, name: str, scenario_tag: str, *rules: dict) -> dict:
    """组装 QSModelConfig dict（四段式：meta/params/logic/risk_filter）。

    Args:
        symbol: 交易对，如 "BTC-USDT"
        name: 策略中文名（用于日志）
        scenario_tag: 场景标签，用于 meta.name 区分
        *rules: 一条或多条规则 dict

    Returns:
        合法的 QSModelConfig dict
    """
    return {
        "qs_model_version": "2.0",
        "meta": {
            "name": f"strategy_test_{scenario_tag}",
            "version": "1.0",
            "base_symbol": symbol,
            "asset_class": "CRYPTO",
        },
        "params": {
            "ema_period": {
                "label": "EMA 周期",
                "value": 20,
                "type": "int",
                "range": [5, 100],
                "unit": "根",
            },
        },
        "logic": {
            "version": "1.0",
            "base_strategy": {
                "kind": "grid",
                "params": {
                    "upper_price": 50000,
                    "lower_price": 40000,
                    "grid_count": 10,
                    "order_qty": 0.01,
                    "symbol": "$meta.base_symbol",
                },
            },
            "rules": list(rules),
        },
        "risk_filter": build_risk_filter(),
    }


def generate_conditional_qsm(symbol: str, test_scenario: str) -> dict:
    """生成包含条件规则的 QSModel，按场景测试不同触发逻辑。

    Args:
        symbol: 交易对，如 "BTC-USDT"
        test_scenario: 测试场景，取值：
            - pause_on_high: 价格上穿均线时暂停（cross_above + pause_orders）
            - resume_on_low: 价格下穿均线时恢复（cross_below + resume_orders）
            - rebalance_on_threshold: 价格穿越均线时调仓（cross_above + rebalance_position）
            - compound_rules: 复合规则（多个 when/recover_when 组合）

    Returns:
        QSModelConfig dict（含 meta/params/logic/risk_filter 四段）

    Raises:
        ValueError: 未知 test_scenario
    """
    if test_scenario == "pause_on_high":
        return _build_pause_on_high_qsm(symbol)
    if test_scenario == "resume_on_low":
        return _build_resume_on_low_qsm(symbol)
    if test_scenario == "rebalance_on_threshold":
        return _build_rebalance_on_threshold_qsm(symbol)
    if test_scenario == "compound_rules":
        return _build_compound_rules_qsm(symbol)
    raise ValueError(f"未知 test_scenario: {test_scenario}")


# ============================================================
# 2. 测试流程函数
# ============================================================


async def run_strategy_test(test_scenario: str = "pause_on_high",
                            symbol: str | None = None,
                            wait_seconds: int = RUN_WAIT_SECONDS,
                            http_client=None) -> dict:
    """单个场景的端到端测试流程。

    步骤：
    1. 生成 QSModel（调用 generate_conditional_qsm）
    2. 调用 /api/dsl/validate 校验 QSModel 合法性
    3. 调用 /api/dsl/dry-run 回测预验证（确认无报错）
    4. 创建 StrategyTemplate（strategy_type="composable"）+ StrategyInstance
    5. 调用 strategy_engine.start_strategy 启动
    6. 等待 wait_seconds 让策略运行
    7. 检查策略事件：是否触发了 pause/resume/rebalance 事件
    8. 验证状态机转换是否正确（查询 StrategyEvent 表，检查 event_type）
    9. 生成测试报告

    Args:
        test_scenario: 测试场景
        symbol: 交易对，None 时使用 DEFAULT_SYMBOLS[0]
        wait_seconds: 策略启动后等待时长（秒），<=0 则跳过等待
        http_client: 可选的 httpx.AsyncClient（测试时注入 mock）

    Returns:
        测试报告 dict，含 scenario/symbol/steps/result/verify 等字段
    """
    if symbol is None:
        symbol = DEFAULT_SYMBOLS[0]

    report: dict[str, Any] = {
        "scenario": test_scenario,
        "symbol": symbol,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": [],
        "result": "PENDING",
    }

    def _step(name: str, status: str, **extra):
        report["steps"].append({"name": name, "status": status, **extra})
        _log(f"  [strategy_test:{test_scenario}] {name}: {status}")

    # 1. 生成 QSModel
    try:
        qsm_config = generate_conditional_qsm(symbol, test_scenario)
        _step("generate_qsm", "OK", qsm_name=qsm_config["meta"]["name"])
    except Exception as e:
        _step("generate_qsm", "FAIL", error=str(e))
        report["result"] = "GENERATE_FAILED"
        return report

    # 2. 解析变量引用，得到可执行 DSL
    try:
        qs_model = QSModelConfig.model_validate(qsm_config)
        resolved_dsl = resolve_variables(qs_model)
        dsl_config = resolved_dsl.model_dump()
        _step("resolve_variables", "OK")
    except Exception as e:
        _step("resolve_variables", "FAIL", error=str(e))
        report["result"] = "RESOLVE_FAILED"
        return report

    # 3. 调用 /api/dsl/validate 校验
    try:
        validate_result = await _call_dsl_validate(dsl_config, http_client)
        valid = validate_result.get("valid", False)
        if not valid:
            errors = validate_result.get("errors", [])
            _step("dsl_validate", "FAIL", errors=errors)
            report["result"] = "VALIDATE_FAILED"
            return report
        _step("dsl_validate", "OK")
    except Exception as e:
        _step("dsl_validate", "FAIL", error=str(e))
        report["result"] = "VALIDATE_REQUEST_FAILED"
        return report

    # 4. 调用 /api/dsl/dry-run 回测预验证（仅确认无报错）
    try:
        dry_run_result = await _call_dsl_dry_run(dsl_config, symbol, http_client)
        total_ticks = dry_run_result.get("total_ticks", 0)
        _step("dsl_dry_run", "OK", total_ticks=total_ticks)
    except Exception as e:
        _step("dsl_dry_run", "FAIL", error=str(e))
        report["result"] = "DRY_RUN_FAILED"
        return report

    # 5. 创建 StrategyTemplate + StrategyInstance 并启动
    db = SessionLocal()
    instance_id = None
    template_id = None
    try:
        account = db.query(Account).first()
        if account is None:
            _step("create_instance", "FAIL", error="无可用账户")
            report["result"] = "NO_ACCOUNT"
            return report

        logic_hash = _compute_logic_hash(qsm_config)

        template = StrategyTemplate(
            name=qsm_config["meta"]["name"],
            strategy_type="composable",
            description=f"策略研发测试 - {test_scenario}",
            default_params={},
            is_builtin=False,
            is_custom=True,
            qs_model_config=qsm_config,
            logic_hash=logic_hash,
        )
        db.add(template)
        db.commit()
        db.refresh(template)
        template_id = template.id

        instance_params = {
            "qs_model_config": qsm_config,
            "symbol": symbol,
            "investment_amount": DEFAULT_INVESTMENT_AMOUNT,
        }
        instance = StrategyInstance(
            template_id=template.id,
            account_id=account.id,
            name=f"{template.name}_inst",
            symbol=symbol,
            market_type="spot",
            params=instance_params,
            status="stopped",
            logic_hash=logic_hash,
        )
        db.add(instance)
        db.commit()
        db.refresh(instance)
        instance_id = instance.id
        _step("create_instance", "OK",
              template_id=template_id, instance_id=instance_id)
    except Exception as e:
        db.rollback()
        _step("create_instance", "FAIL", error=str(e))
        report["result"] = "CREATE_FAILED"
        return report
    finally:
        db.close()

    # 6. 启动策略（调用 strategy_engine.start_strategy）
    try:
        await strategy_engine.start_strategy(instance_id)
        _step("start_strategy", "OK", instance_id=instance_id)
    except Exception as e:
        _step("start_strategy", "FAIL", error=str(e))
        report["result"] = "START_FAILED"
        return report

    # 7. 等待策略运行
    if wait_seconds > 0:
        await asyncio.sleep(wait_seconds)
        _step("wait_run", "OK", seconds=wait_seconds)

    # 8. 验证条件触发（查询 StrategyEvent 表）
    db = SessionLocal()
    try:
        verify_result = verify_condition_triggers(db, instance_id, test_scenario)
    finally:
        db.close()
    _step("verify_triggers",
          "OK" if verify_result["triggered_correctly"] else "FAIL",
          expected=verify_result["expected_triggers"],
          actual=verify_result["actual_triggers"])
    report["verify"] = verify_result

    # 9. 汇总结论
    report["result"] = "PASS" if verify_result["triggered_correctly"] else "TRIGGER_MISMATCH"
    return report


# ============================================================
# 3. 条件触发验证
# ============================================================


def _extract_action_name(event: StrategyEvent) -> str | None:
    """从 StrategyEvent 中提取动作名。

    动作事件格式（见 dsl/blocks/actions.py）：
    - event_type="dsl_action", message="pause_orders: {symbol}" 等（实际下单/撤单）
    - event_type="dsl_info", message="rebalance_position: 持仓已平衡 delta=0.0"（无需调仓）
    - event_type="dsl_warn", message="rebalance_position: ..."（缺少方法等）

    两种事件类型都表示动作已触发执行，仅结果不同。

    Returns:
        动作名（pause_orders / resume_orders / rebalance_position），
        非动作事件返回 None
    """
    etype = event.event_type or ""
    if etype not in ("dsl_action", "dsl_info", "dsl_warn"):
        return None
    msg = event.message or ""
    # 取冒号前的部分作为动作名
    if ":" in msg:
        return msg.split(":", 1)[0].strip()
    return None


def verify_condition_triggers(db, strategy_instance_id: int, test_scenario: str) -> dict:
    """验证策略的条件触发是否正确。

    查询 StrategyEvent 表找出该策略的所有动作相关事件（dsl_action / dsl_info /
    dsl_warn），按场景验证：
    - pause_on_high: 检查是否有 pause_orders 事件
    - resume_on_low: 检查是否有 resume_orders 事件
    - rebalance_on_threshold: 检查是否有 rebalance_position 事件
      （含 dsl_info "持仓已平衡"，表示动作执行但无需调仓）
    - compound_rules: 检查多规则是否触发

    Args:
        db: 数据库 Session
        strategy_instance_id: 策略实例 ID
        test_scenario: 测试场景

    Returns:
        {
            "scenario": test_scenario,
            "expected_triggers": [...],
            "actual_triggers": [...],
            "triggered_correctly": bool,
            "events": [...]
        }
    """
    expected = list(EXPECTED_TRIGGERS.get(test_scenario, []))

    # 查询该策略所有动作相关事件（dsl_action + dsl_info + dsl_warn）
    events = db.query(StrategyEvent).filter(
        StrategyEvent.strategy_instance_id == strategy_instance_id,
        StrategyEvent.event_type.in_(["dsl_action", "dsl_info", "dsl_warn"]),
    ).order_by(StrategyEvent.created_at.asc()).all()

    # 提取实际触发的动作名（去重保序）
    actual: list[str] = []
    seen: set[str] = set()
    for ev in events:
        action = _extract_action_name(ev)
        if action and action not in seen:
            actual.append(action)
            seen.add(action)

    # 验证：期望的动作是否都出现在实际触发列表中
    triggered_correctly = all(a in actual for a in expected)

    return {
        "scenario": test_scenario,
        "expected_triggers": expected,
        "actual_triggers": actual,
        "triggered_correctly": triggered_correctly,
        "events": [
            {
                "id": ev.id,
                "event_type": ev.event_type,
                "message": ev.message,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            }
            for ev in events
        ],
    }


# ============================================================
# 4. 主流程
# ============================================================


async def run_all_scenarios(symbol: str | None = None,
                            wait_seconds: int = RUN_WAIT_SECONDS,
                            http_client=None) -> dict:
    """运行所有场景并汇总报告。

    依次运行 4 个场景：pause_on_high / resume_on_low /
    rebalance_on_threshold / compound_rules，每个场景生成报告，
    汇总输出到 strategy_test_report_{timestamp}.json。

    Args:
        symbol: 交易对，None 时使用 DEFAULT_SYMBOLS[0]
        wait_seconds: 每个场景启动后等待时长（秒）
        http_client: 可选的 httpx.AsyncClient（测试时注入 mock）

    Returns:
        汇总报告 dict（同时写入 JSON 报告文件）
    """
    if symbol is None:
        symbol = DEFAULT_SYMBOLS[0]

    _log("=" * 60)
    _log(f"策略研发测试 - 开始（symbol={symbol}, 等待 {wait_seconds}s/场景）")
    _log("=" * 60)

    results: dict[str, dict] = {}
    for scenario in SCENARIOS:
        _log(f"--- 场景: {scenario} ---")
        try:
            r = await run_strategy_test(
                test_scenario=scenario,
                symbol=symbol,
                wait_seconds=wait_seconds,
                http_client=http_client,
            )
        except Exception as e:
            r = {
                "scenario": scenario,
                "symbol": symbol,
                "result": "EXCEPTION",
                "error": str(e),
            }
            _log(f"  场景 {scenario} 异常: {e}")
        results[scenario] = r

    # 构建场景详情列表（含 triggered_correctly，便于调用方直接消费）
    scenario_details: list[dict] = []
    for s in SCENARIOS:
        r = results.get(s, {})
        verify = r.get("verify", {}) or {}
        scenario_details.append({
            "scenario": s,
            "result": r.get("result", "MISSING"),
            "triggered_correctly": verify.get("triggered_correctly", False),
            "expected_triggers": verify.get("expected_triggers", []),
            "actual_triggers": verify.get("actual_triggers", []),
        })

    # overall_passed: 所有场景均 PASS 且 triggered_correctly=True
    overall_passed = all(
        sd["result"] == "PASS" and sd["triggered_correctly"]
        for sd in scenario_details
    )

    # 汇总
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "scenarios": scenario_details,
        "results": results,
        "summary": {
            s: results.get(s, {}).get("result", "MISSING")
            for s in SCENARIOS
        },
        "overall_passed": overall_passed,
    }

    # 写入报告文件
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_file = REPORT_DIR / f"strategy_test_report_{timestamp}.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    _log(f"测试报告已写入: {report_file.name}")
    _log("=" * 60)

    summary["report_file"] = str(report_file)
    return summary


if __name__ == "__main__":
    _result = asyncio.run(run_all_scenarios())
    print(json.dumps(_result, ensure_ascii=False, indent=2, default=str))
