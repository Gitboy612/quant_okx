"""strategy_test_runner.py 单元测试。

测试用例：
1. test_generate_conditional_qsm_pause_on_high: pause_on_high 场景 QSModel 通过 schema validate
2. test_generate_conditional_qsm_resume_on_low: resume_on_low 场景 QSModel 合法
3. test_generate_conditional_qsm_rebalance: rebalance_on_threshold 场景 QSModel 合法
4. test_generate_conditional_qsm_compound: compound_rules 场景 QSModel 合法
5. test_verify_condition_triggers_pause: 模拟 pause_orders 事件，验证检测到
6. test_verify_condition_triggers_resume: 模拟 resume_orders 事件
7. test_verify_condition_triggers_rebalance: 模拟 rebalance_position 事件
8. test_verify_condition_triggers_missing: 无事件时 triggered_correctly=False

导入风格参考 test_run_iteration_should_start.py：sys.path 注入 backend 根目录 +
脚本所在目录（strategy_test_runner.py 与 run_iteration.py 同为脚本而非包）。
"""
import sys
import os
from unittest.mock import MagicMock, Mock, patch
from datetime import datetime, timezone

# 注入 backend 根目录到 sys.path
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_DIR)

# 注入 strategy_test_runner.py 所在目录（脚本而非包）
_SCRIPT_DIR = os.path.join(_BACKEND_DIR, "tests", "reports", "strategy_research")
sys.path.insert(0, _SCRIPT_DIR)

import pytest

# 导入真实 schema 与生成器辅助
from dsl.schema import QSModelConfig, resolve_variables
from research.qsm_generator import validate_qsm

# 测试目标模块
import strategy_test_runner
import run_iteration


# ============================================================
# Mock 工厂
# ============================================================


def _make_event_mock(event_type: str, message: str, ev_id: int = 1,
                     created_at: datetime | None = None):
    """构造一个 Mock 的 StrategyEvent 对象。

    Args:
        event_type: 事件类型，如 "dsl_action" / "dsl_info"
        message: 事件消息，如 "pause_orders: BTC-USDT"
        ev_id: 事件 ID
        created_at: 创建时间，None 时用固定时间
    """
    ev = Mock()
    ev.id = ev_id
    ev.event_type = event_type
    ev.message = message
    ev.created_at = created_at or datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)
    return ev


def _make_db_mock_with_events(events: list):
    """构造 mock DB session，使 verify_condition_triggers 中的查询链返回指定 events。

    查询链：db.query(StrategyEvent).filter(...).order_by(...).all()
    """
    session = MagicMock()
    query_mock = MagicMock()
    filter_mock = MagicMock()
    order_mock = MagicMock()
    session.query.return_value = query_mock
    query_mock.filter.return_value = filter_mock
    filter_mock.order_by.return_value = order_mock
    order_mock.all.return_value = events
    return session


@pytest.fixture(autouse=True)
def _silence_log():
    """静默 _log，避免污染真实 execution.log。

    strategy_test_runner._log 是从 run_iteration 导入的引用，
    patch 它不影响其它模块（仅影响 strategy_test_runner 内的调用）。
    """
    with patch.object(strategy_test_runner, "_log"):
        yield


# ============================================================
# 1-4. generate_conditional_qsm 场景测试
# ============================================================


def test_generate_conditional_qsm_pause_on_high():
    """pause_on_high 场景 QSModel 通过 QSModelConfig schema validate。"""
    qsm = strategy_test_runner.generate_conditional_qsm("ETH-USDT", "pause_on_high")

    # 四段式结构
    assert qsm["qs_model_version"] == "2.0"
    assert "meta" in qsm
    assert "params" in qsm
    assert "logic" in qsm
    assert "risk_filter" in qsm

    # meta 名标识场景
    assert qsm["meta"]["name"] == "strategy_test_pause_on_high"
    assert qsm["meta"]["base_symbol"] == "ETH-USDT"

    # 含规则且为触发-恢复对
    rules = qsm["logic"]["rules"]
    assert len(rules) == 1
    rule = rules[0]
    # when 用 or(cross_above, gt) 包装确保 60s 窗口内可靠触发
    when_cond = rule["when"]["condition"]
    assert when_cond["kind"] == "or"
    assert when_cond["args"]["conditions"][0]["kind"] == "cross_above"
    assert when_cond["args"]["conditions"][1]["kind"] == "gt"
    assert rule["then"][0]["kind"] == "pause_orders"
    # recover_when 无 fallback（避免 rapid cycling），保持原始 cross_below
    assert rule["recover_when"]["condition"]["kind"] == "cross_below"
    assert rule["recover_then"][0]["kind"] == "resume_orders"

    # Pydantic schema 校验通过
    assert validate_qsm(qsm) is True
    QSModelConfig.model_validate(qsm)


def test_generate_conditional_qsm_resume_on_low():
    """resume_on_low 场景 QSModel 合法（单次触发 cross_below → resume_orders）。"""
    qsm = strategy_test_runner.generate_conditional_qsm("BTC-USDT", "resume_on_low")

    assert qsm["meta"]["name"] == "strategy_test_resume_on_low"
    rules = qsm["logic"]["rules"]
    assert len(rules) == 1
    rule = rules[0]
    # when 用 or(cross_below, lt) 包装确保 60s 窗口内可靠触发
    when_cond = rule["when"]["condition"]
    assert when_cond["kind"] == "or"
    assert when_cond["args"]["conditions"][0]["kind"] == "cross_below"
    assert when_cond["args"]["conditions"][1]["kind"] == "lt"
    assert rule["then"][0]["kind"] == "resume_orders"
    # 单次触发，无 recover_when
    assert rule.get("recover_when") is None

    # schema 校验
    assert validate_qsm(qsm) is True
    QSModelConfig.model_validate(qsm)


def test_generate_conditional_qsm_rebalance():
    """rebalance_on_threshold 场景 QSModel 合法（cross_above → rebalance_position）。"""
    qsm = strategy_test_runner.generate_conditional_qsm("ETH-USDT", "rebalance_on_threshold")

    assert qsm["meta"]["name"] == "strategy_test_rebalance_on_threshold"
    rules = qsm["logic"]["rules"]
    assert len(rules) == 1
    rule = rules[0]
    # when 用 or(cross_above, gt) 包装确保 60s 窗口内可靠触发
    when_cond = rule["when"]["condition"]
    assert when_cond["kind"] == "or"
    assert when_cond["args"]["conditions"][0]["kind"] == "cross_above"
    assert when_cond["args"]["conditions"][1]["kind"] == "gt"
    assert rule["then"][0]["kind"] == "rebalance_position"
    # 单次触发，无 recover_when
    assert rule.get("recover_when") is None

    # schema 校验
    assert validate_qsm(qsm) is True
    QSModelConfig.model_validate(qsm)


def test_generate_conditional_qsm_compound():
    """compound_rules 场景 QSModel 合法（含 2 条规则：触发-恢复对 + 单次触发）。"""
    qsm = strategy_test_runner.generate_conditional_qsm("BTC-USDT", "compound_rules")

    assert qsm["meta"]["name"] == "strategy_test_compound_rules"
    rules = qsm["logic"]["rules"]
    assert len(rules) == 2

    # 规则1：触发-恢复对（pause/resume）
    rule1 = rules[0]
    when1_cond = rule1["when"]["condition"]
    assert when1_cond["kind"] == "or"
    assert when1_cond["args"]["conditions"][0]["kind"] == "cross_above"
    assert when1_cond["args"]["conditions"][1]["kind"] == "gt"
    assert rule1["then"][0]["kind"] == "pause_orders"
    # recover_when 无 fallback，保持原始 cross_below
    assert rule1["recover_when"]["condition"]["kind"] == "cross_below"
    assert rule1["recover_then"][0]["kind"] == "resume_orders"

    # 规则2：单次触发（rebalance_position，cross_above(ema5, ema20)）
    rule2 = rules[1]
    when2_cond = rule2["when"]["condition"]
    assert when2_cond["kind"] == "or"
    assert when2_cond["args"]["conditions"][0]["kind"] == "cross_above"
    assert when2_cond["args"]["conditions"][1]["kind"] == "gt"
    assert rule2["then"][0]["kind"] == "rebalance_position"
    assert rule2.get("recover_when") is None

    # schema 校验
    assert validate_qsm(qsm) is True
    QSModelConfig.model_validate(qsm)


def test_generate_conditional_qsm_unknown_scenario():
    """未知场景应抛 ValueError。"""
    with pytest.raises(ValueError, match="未知 test_scenario"):
        strategy_test_runner.generate_conditional_qsm("BTC-USDT", "unknown_scenario")


def test_generate_conditional_qsm_resolves_variables():
    """生成的 QSModel 经 resolve_variables 解析后 $meta.base_symbol 被替换。"""
    qsm = strategy_test_runner.generate_conditional_qsm("ETH-USDT", "pause_on_high")
    config = QSModelConfig.model_validate(qsm)
    resolved = resolve_variables(config)
    # 基础策略 symbol 应被解析为实际值
    assert resolved.base_strategy.params["symbol"] == "ETH-USDT"
    # 规则中的指标引用也应被解析
    # 注：when 用 or(cross_above, gt) 包装，需深入 cross_above 子条件取 indicator_a/b
    # 注意：resolve_variables 后顶层 condition 为 ConditionRef 对象（可点访问），
    # 但子条件仍是 dict（需用 ["kind"] 访问）
    rule = resolved.rules[0]
    when_cond = rule.when.condition
    assert when_cond.kind == "or"
    cross_above = when_cond.args["conditions"][0]
    assert cross_above["kind"] == "cross_above"
    indicator_a = cross_above["args"]["indicator_a"]
    assert indicator_a["args"]["symbol"] == "ETH-USDT"
    indicator_b = cross_above["args"]["indicator_b"]
    assert indicator_b["args"]["symbol"] == "ETH-USDT"


# ============================================================
# 5-8. verify_condition_triggers 验证测试
# ============================================================


def test_verify_condition_triggers_pause():
    """模拟 pause_orders 事件，验证检测到且 triggered_correctly=True。

    注：verify_condition_triggers 的 DB 查询已 filter(event_type=="dsl_action")，
    故 mock 仅返回 dsl_action 事件（与非动作事件过滤在 DB 层完成）。
    """
    events = [
        _make_event_mock("dsl_action", "pause_orders: ETH-USDT", ev_id=1),
    ]
    db = _make_db_mock_with_events(events)

    result = strategy_test_runner.verify_condition_triggers(db, 999, "pause_on_high")

    assert result["scenario"] == "pause_on_high"
    assert result["expected_triggers"] == ["pause_orders"]
    assert result["actual_triggers"] == ["pause_orders"]
    assert result["triggered_correctly"] is True
    # events 列表包含全部 dsl_action 事件
    assert len(result["events"]) == 1
    assert result["events"][0]["message"] == "pause_orders: ETH-USDT"
    assert result["events"][0]["event_type"] == "dsl_action"


def test_verify_condition_triggers_resume():
    """模拟 resume_orders 事件，验证检测到且 triggered_correctly=True。"""
    events = [
        _make_event_mock("dsl_action", "resume_orders: BTC-USDT", ev_id=10),
    ]
    db = _make_db_mock_with_events(events)

    result = strategy_test_runner.verify_condition_triggers(db, 100, "resume_on_low")

    assert result["scenario"] == "resume_on_low"
    assert result["expected_triggers"] == ["resume_orders"]
    assert result["actual_triggers"] == ["resume_orders"]
    assert result["triggered_correctly"] is True


def test_verify_condition_triggers_rebalance():
    """模拟 rebalance_position 事件，验证检测到且 triggered_correctly=True。

    rebalance 事件 message 含 side/sz/symbol/delta，需正确提取动作名。
    """
    events = [
        _make_event_mock(
            "dsl_action",
            "rebalance_position: buy 0.5 ETH-USDT (delta=0.5)",
            ev_id=20,
        ),
    ]
    db = _make_db_mock_with_events(events)

    result = strategy_test_runner.verify_condition_triggers(db, 200, "rebalance_on_threshold")

    assert result["scenario"] == "rebalance_on_threshold"
    assert result["expected_triggers"] == ["rebalance_position"]
    assert result["actual_triggers"] == ["rebalance_position"]
    assert result["triggered_correctly"] is True


def test_verify_condition_triggers_missing():
    """无事件时 triggered_correctly=False 且 actual_triggers 为空。"""
    db = _make_db_mock_with_events([])

    result = strategy_test_runner.verify_condition_triggers(db, 999, "pause_on_high")

    assert result["scenario"] == "pause_on_high"
    assert result["expected_triggers"] == ["pause_orders"]
    assert result["actual_triggers"] == []
    assert result["triggered_correctly"] is False
    assert result["events"] == []


def test_verify_condition_triggers_compound_partial():
    """compound_rules 场景：期望的 pause_orders 未触发时 triggered_correctly=False。

    compound_rules 仅期望 pause_orders（FSM 限制 rule2 在 PAUSED 状态不可评估），
    模拟只触发 resume_orders（非期望动作），应判定未通过。
    """
    events = [
        _make_event_mock("dsl_action", "resume_orders: BTC-USDT", ev_id=1),
    ]
    db = _make_db_mock_with_events(events)

    result = strategy_test_runner.verify_condition_triggers(db, 300, "compound_rules")

    assert result["expected_triggers"] == ["pause_orders"]
    assert result["actual_triggers"] == ["resume_orders"]
    assert result["triggered_correctly"] is False


def test_verify_condition_triggers_compound_full():
    """compound_rules 场景：三个动作都触发时 triggered_correctly=True。"""
    events = [
        _make_event_mock("dsl_action", "pause_orders: BTC-USDT", ev_id=1),
        _make_event_mock("dsl_action", "resume_orders: BTC-USDT", ev_id=2),
        _make_event_mock("dsl_action", "rebalance_position: buy 0.3 BTC-USDT (delta=0.3)", ev_id=3),
    ]
    db = _make_db_mock_with_events(events)

    result = strategy_test_runner.verify_condition_triggers(db, 400, "compound_rules")

    assert result["actual_triggers"] == ["pause_orders", "resume_orders", "rebalance_position"]
    assert result["triggered_correctly"] is True


def test_verify_condition_triggers_dedup():
    """同一动作多次触发应在 actual_triggers 中去重。"""
    events = [
        _make_event_mock("dsl_action", "pause_orders: BTC-USDT", ev_id=1),
        _make_event_mock("dsl_action", "pause_orders: BTC-USDT", ev_id=2),
        _make_event_mock("dsl_action", "resume_orders: BTC-USDT", ev_id=3),
    ]
    db = _make_db_mock_with_events(events)

    result = strategy_test_runner.verify_condition_triggers(db, 500, "pause_on_high")

    # pause_orders 去重为 1 个，但仍包含 resume_orders
    assert result["actual_triggers"] == ["pause_orders", "resume_orders"]
    # pause_on_high 只期望 pause_orders，所以通过
    assert result["triggered_correctly"] is True


def test_extract_action_name_filters_non_dsl_action():
    """_extract_action_name 接受 dsl_action / dsl_info / dsl_warn 三类事件。

    这三类事件都表示动作已触发执行（仅结果不同：成功/无需操作/警告），
    均应正确提取动作名。其他事件类型（如 fsm_transition / info）才返回 None。
    """
    # dsl_action 事件正确提取动作名
    ev_action = _make_event_mock("dsl_action", "pause_orders: BTC-USDT")
    assert strategy_test_runner._extract_action_name(ev_action) == "pause_orders"

    # dsl_info / dsl_warn 也提取动作名（动作已触发但无需操作/警告）
    ev_info = _make_event_mock("dsl_info", "rebalance_position: 持仓已平衡")
    assert strategy_test_runner._extract_action_name(ev_info) == "rebalance_position"

    ev_warn = _make_event_mock("dsl_warn", "rebalance_position: 跳过")
    assert strategy_test_runner._extract_action_name(ev_warn) == "rebalance_position"

    # 非动作类事件（fsm_transition / info / error 等）返回 None
    ev_fsm = _make_event_mock("fsm_transition", "RUNNING -> PAUSED")
    assert strategy_test_runner._extract_action_name(ev_fsm) is None

    ev_info_non_action = _make_event_mock("info", "tick 处理完成")
    assert strategy_test_runner._extract_action_name(ev_info_non_action) is None

    # dsl_action 但无冒号也返回 None
    ev_no_colon = _make_event_mock("dsl_action", "no_colon_message")
    assert strategy_test_runner._extract_action_name(ev_no_colon) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
