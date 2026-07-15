"""可拼接策略 DSL 静态校验器。

按 spec.md「Requirement: DSL 静态校验」实现五层校验：

1. structure  —— Pydantic Schema 结构校验（失败则直接返回，后续层无法执行）
2. reference  —— 所有 BlockRef 的 kind 在对应注册表中存在
3. type       —— Condition 的输入类型与谓词期望类型匹配
4. semantic   —— Rule 语义完整性（非空 then / 触发器字段一致 / 命名唯一 / 可恢复）
5. resource   —— P0 轻量资源校验（K 线周期 / 下单量），不实际请求 OKX

校验器为纯同步代码：`DSLValidator().validate(config) -> ValidationResult`。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pydantic

from dsl.schema import StrategyDSL, Trigger, ConditionRef
from dsl.registry import (
    indicator_registry,
    condition_registry,
    action_registry,
    event_registry,
    base_strategy_registry,
)

# 导入积木库子模块以触发 @indicator / @condition / @action / @event /
# @base_strategy 装饰器注册。仅在模块首次导入时生效，重复导入无副作用。
import dsl.blocks.indicators  # noqa: F401
import dsl.blocks.conditions  # noqa: F401
import dsl.blocks.events  # noqa: F401
import dsl.blocks.actions  # noqa: F401
import dsl.blocks.bases  # noqa: F401


# OKX 支持的 K 线周期（bar 参数大小写敏感：分钟小写 m，小时大写 H，天/周/月大写）。
SUPPORTED_WINDOWS = {
    "1m", "3m", "5m", "15m", "30m",
    "1H", "2H", "4H", "6H", "12H",
    "1D", "1W", "1M",
}
# 用户友好：接受示例中出现的小写 h/d 别名（如 "1h"/"1d"）。
# 注意：并非所有小写形式都接受（例如 "2h" 不在别名表内，须用规范形式 "2H"）。
WINDOW_ALIASES = {"1h", "1d"}


@dataclass
class ValidationError:
    """单条校验错误。

    Attributes:
        layer: 出错层级 structure / reference / type / semantic / resource
        code:  机器可读错误码，如 "UNKNOWN_KIND" / "EMPTY_THEN"
        message: 人类可读中文说明
        path: 配置路径，如 "rules[0].when.condition"
    """

    layer: str
    code: str
    message: str
    path: str


@dataclass
class ValidationResult:
    """校验结果。"""

    valid: bool = True
    errors: list[ValidationError] = field(default_factory=list)

    def add_error(self, layer: str, code: str, message: str, path: str) -> None:
        self.errors.append(ValidationError(layer, code, message, path))
        self.valid = False


class DSLValidator:
    """可拼接策略 DSL 静态校验器。

    用法::

        result = DSLValidator().validate(dsl_config_dict)
        if not result.valid:
            for e in result.errors:
                print(e.layer, e.code, e.path, e.message)
    """

    def __init__(self) -> None:
        self.result = ValidationResult()

    # ============================================================
    # 入口
    # ============================================================

    def validate(self, config: dict | StrategyDSL) -> ValidationResult:
        """对 DSL 配置执行五层静态校验，返回 ValidationResult。"""
        self.result = ValidationResult()

        # 1. 结构校验（失败则直接返回）
        dsl = self._validate_structure(config)
        if dsl is None:
            return self.result

        # 2. 引用校验
        self._validate_references(dsl)
        # 3. 类型校验
        self._validate_types(dsl)
        # 4. 语义校验
        self._validate_semantics(dsl)
        # 5. 资源校验
        self._validate_resources(dsl)

        return self.result

    # ============================================================
    # Layer 1: 结构校验
    # ============================================================

    def _validate_structure(self, config: dict | StrategyDSL) -> StrategyDSL | None:
        """用 Pydantic 解析配置；失败则记录结构错误并返回 None。"""
        if isinstance(config, StrategyDSL):
            return config
        try:
            return StrategyDSL.model_validate(config)
        except pydantic.ValidationError as e:
            for err in e.errors():
                loc = err.get("loc", ())
                path = ".".join(str(x) for x in loc) if loc else ""
                msg = err.get("msg", "结构校验失败")
                self.result.add_error("structure", "SCHEMA_ERROR", msg, path)
            return None

    # ============================================================
    # Layer 2: 引用校验
    # ============================================================

    def _validate_references(self, dsl: StrategyDSL) -> None:
        # 基础策略
        if dsl.base_strategy is None or dsl.base_strategy.kind is None:
            # 无基础策略的纯规则策略：必须有至少一条规则
            if len(dsl.rules) == 0:
                self.result.add_error(
                    "reference", "NO_BASE_NO_RULES",
                    "无基础策略时至少需要一条规则",
                    "rules",
                )
        else:
            if not base_strategy_registry.exists(dsl.base_strategy.kind):
                self.result.add_error(
                    "reference", "UNKNOWN_KIND",
                    f"未知基础策略 kind: {dsl.base_strategy.kind}",
                    "base_strategy.kind",
                )

        for i, rule in enumerate(dsl.rules):
            base = f"rules[{i}]"
            self._validate_trigger_refs(rule.when, f"{base}.when")
            if rule.recover_when is not None:
                self._validate_trigger_refs(rule.recover_when, f"{base}.recover_when")
            for j, action in enumerate(rule.then):
                if not action_registry.exists(action.kind):
                    self.result.add_error(
                        "reference", "UNKNOWN_KIND",
                        f"未知动作 kind: {action.kind}",
                        f"{base}.then[{j}].kind",
                    )
            for j, action in enumerate(rule.recover_then):
                if not action_registry.exists(action.kind):
                    self.result.add_error(
                        "reference", "UNKNOWN_KIND",
                        f"未知动作 kind: {action.kind}",
                        f"{base}.recover_then[{j}].kind",
                    )

    def _validate_trigger_refs(self, trigger: Trigger, path: str) -> None:
        if trigger.condition is not None:
            self._validate_condition_ref(trigger.condition, f"{path}.condition")
        if trigger.event is not None:
            if not event_registry.exists(trigger.event.kind):
                self.result.add_error(
                    "reference", "UNKNOWN_KIND",
                    f"未知事件 kind: {trigger.event.kind}",
                    f"{path}.event.kind",
                )
        if trigger.extra_condition is not None:
            self._validate_condition_ref(trigger.extra_condition, f"{path}.extra_condition")

    def _validate_condition_ref(self, cond: ConditionRef, path: str) -> None:
        """递归校验 ConditionRef 及其嵌套的 indicator / conditions / condition。"""
        if not condition_registry.exists(cond.kind):
            self.result.add_error(
                "reference", "UNKNOWN_KIND",
                f"未知条件 kind: {cond.kind}",
                f"{path}.kind",
            )
            # 未知条件无法确定结构，仍尝试递归其 args 中已知的嵌套引用
        args = cond.args or {}

        # 比较类条件嵌套的 indicator
        ind = args.get("indicator")
        if isinstance(ind, dict):
            ind_kind = ind.get("kind")
            if not indicator_registry.exists(ind_kind):
                self.result.add_error(
                    "reference", "UNKNOWN_KIND",
                    f"未知指标 kind: {ind_kind}",
                    f"{path}.args.indicator.kind",
                )

        # 逻辑组合 and/or 嵌套的 conditions
        subs = args.get("conditions")
        if isinstance(subs, list):
            for j, sub in enumerate(subs):
                if isinstance(sub, dict):
                    self._validate_condition_ref(ConditionRef(**sub), f"{path}.args.conditions[{j}]")

        # 逻辑组合 not 嵌套的 condition
        sub_single = args.get("condition")
        if isinstance(sub_single, dict):
            self._validate_condition_ref(ConditionRef(**sub_single), f"{path}.args.condition")

    # ============================================================
    # Layer 3: 类型校验
    # ============================================================

    def _validate_types(self, dsl: StrategyDSL) -> None:
        for i, rule in enumerate(dsl.rules):
            base = f"rules[{i}]"
            self._validate_trigger_types(rule.when, f"{base}.when")
            if rule.recover_when is not None:
                self._validate_trigger_types(rule.recover_when, f"{base}.recover_when")

    def _validate_trigger_types(self, trigger: Trigger, path: str) -> None:
        if trigger.condition is not None:
            self._validate_condition_type(trigger.condition, f"{path}.condition")
        if trigger.extra_condition is not None:
            self._validate_condition_type(trigger.extra_condition, f"{path}.extra_condition")

    def _validate_condition_type(self, cond: ConditionRef, path: str) -> None:
        cls = condition_registry.get(cond.kind)
        if cls is None:
            # 引用层已报错；类型层无法判断，跳过（仍递归子条件）
            self._recurse_condition_type(cond, path)
            return

        input_type = getattr(cls, "input_type", None)
        args = cond.args or {}

        if input_type == "number":
            # 比较类条件期望 args.indicator 为数值型指标引用
            ind = args.get("indicator")
            if not isinstance(ind, dict):
                self.result.add_error(
                    "type", "TYPE_MISMATCH",
                    f"条件 {cond.kind} 期望数值型指标，但 args.indicator 不是有效指标引用",
                    f"{path}.args.indicator",
                )
            else:
                ind_cls = indicator_registry.get(ind.get("kind"))
                if ind_cls is not None:
                    output_type = getattr(ind_cls, "output_type", None)
                    if output_type not in (int, float):
                        self.result.add_error(
                            "type", "TYPE_MISMATCH",
                            f"指标 {ind.get('kind')} 输出类型 {output_type!r} 不是数值型，"
                            f"不能用于条件 {cond.kind}",
                            f"{path}.args.indicator",
                        )
        elif input_type == "bool":
            # 仅逻辑组合条件（and/or/not 等）期望 args.conditions（列表）或 args.condition（单个）
            # 普通 bool 条件（cross_above/cross_below/in_range/out_range）有自己的参数 schema，跳过此检查
            param_schema = getattr(cls, "param_schema", {}) or {}
            is_logic_combinator = "conditions" in param_schema or "condition" in param_schema
            if is_logic_combinator:
                has_conditions = isinstance(args.get("conditions"), list)
                has_condition = isinstance(args.get("condition"), dict)
                if not (has_conditions or has_condition):
                    self.result.add_error(
                        "type", "TYPE_MISMATCH",
                        f"逻辑组合条件 {cond.kind} 期望 args.conditions 或 args.condition 为子条件引用",
                        f"{path}.args",
                    )

        # 递归校验嵌套子条件
        self._recurse_condition_type(cond, path)

    def _recurse_condition_type(self, cond: ConditionRef, path: str) -> None:
        """对 and/or/not 等嵌套的子条件递归做类型校验。"""
        args = cond.args or {}
        subs = args.get("conditions")
        if isinstance(subs, list):
            for j, sub in enumerate(subs):
                if isinstance(sub, dict):
                    self._validate_condition_type(ConditionRef(**sub), f"{path}.args.conditions[{j}]")
        sub_single = args.get("condition")
        if isinstance(sub_single, dict):
            self._validate_condition_type(ConditionRef(**sub_single), f"{path}.args.condition")

    # ============================================================
    # Layer 4: 语义校验
    # ============================================================

    def _validate_semantics(self, dsl: StrategyDSL) -> None:
        seen_names: set[str] = set()
        for i, rule in enumerate(dsl.rules):
            base = f"rules[{i}]"

            # then 至少一个 Action
            if len(rule.then) == 0:
                self.result.add_error(
                    "semantic", "EMPTY_THEN",
                    f"规则 '{rule.name}' 的 then 为空，至少需要一个动作",
                    f"{base}.then",
                )

            # recover_then 非空但 recover_when 缺失
            if rule.recover_when is None and len(rule.recover_then) > 0:
                self.result.add_error(
                    "semantic", "RECOVER_WITHOUT_WHEN",
                    f"规则 '{rule.name}' 配置了 recover_then 但缺少 recover_when",
                    f"{base}.recover_when",
                )

            # 死锁检测：有 recover_when 但 recover_then 为空 → 无法回到 RUNNING
            if rule.recover_when is not None and len(rule.recover_then) == 0:
                self.result.add_error(
                    "semantic", "UNRECOVERABLE_STATE",
                    f"规则 '{rule.name}' 有 recover_when 但 recover_then 为空，无法回到 RUNNING",
                    f"{base}.recover_then",
                )

            # 触发器 mode 与字段一致性
            self._validate_trigger_semantics(rule.when, f"{base}.when", rule.name)
            if rule.recover_when is not None:
                self._validate_trigger_semantics(rule.recover_when, f"{base}.recover_when", rule.name)

            # 规则名唯一
            if rule.name in seen_names:
                self.result.add_error(
                    "semantic", "DUPLICATE_RULE_NAME",
                    f"规则名重复: '{rule.name}'",
                    f"{base}.name",
                )
            seen_names.add(rule.name)

    def _validate_trigger_semantics(self, trigger: Trigger, path: str, rule_name: str) -> None:
        if trigger.mode == "condition" and trigger.condition is None:
            self.result.add_error(
                "semantic", "CONDITION_TRIGGER_MISSING_CONDITION",
                f"规则 '{rule_name}' 的触发器 mode=condition 但 condition 为空",
                f"{path}.condition",
            )
        if trigger.mode == "event" and trigger.event is None:
            self.result.add_error(
                "semantic", "EVENT_TRIGGER_MISSING_EVENT",
                f"规则 '{rule_name}' 的触发器 mode=event 但 event 为空",
                f"{path}.event",
            )

    # ============================================================
    # Layer 5: 资源校验（P0 轻量版，不请求 OKX）
    # ============================================================

    def _validate_resources(self, dsl: StrategyDSL) -> None:
        for i, rule in enumerate(dsl.rules):
            base = f"rules[{i}]"

            # 收集触发器中所有指标引用，检查 window 周期
            indicators: list[tuple[dict, str]] = []
            self._collect_indicator_refs(rule.when, f"{base}.when", indicators)
            if rule.recover_when is not None:
                self._collect_indicator_refs(rule.recover_when, f"{base}.recover_when", indicators)
            for ind_args, ind_path in indicators:
                self._check_window(ind_args, ind_path)

            # 收集所有动作，检查 place_order 的 qty
            for j, action in enumerate(rule.then):
                self._check_action_resource(action, f"{base}.then[{j}]")
            for j, action in enumerate(rule.recover_then):
                self._check_action_resource(action, f"{base}.recover_then[{j}]")

    def _collect_indicator_refs(
        self, trigger: Trigger, path: str, out: list[tuple[dict, str]]
    ) -> None:
        """从触发器中递归收集所有指标引用的 args 字典与路径。"""
        if trigger.condition is not None:
            self._collect_indicator_refs_from_condition(trigger.condition, f"{path}.condition", out)
        if trigger.extra_condition is not None:
            self._collect_indicator_refs_from_condition(
                trigger.extra_condition, f"{path}.extra_condition", out
            )

    def _collect_indicator_refs_from_condition(
        self, cond: ConditionRef, path: str, out: list[tuple[dict, str]]
    ) -> None:
        args = cond.args or {}
        ind = args.get("indicator")
        if isinstance(ind, dict):
            out.append((ind.get("args") or {}, f"{path}.args.indicator"))
        subs = args.get("conditions")
        if isinstance(subs, list):
            for j, sub in enumerate(subs):
                if isinstance(sub, dict):
                    self._collect_indicator_refs_from_condition(
                        ConditionRef(**sub), f"{path}.args.conditions[{j}]", out
                    )
        sub_single = args.get("condition")
        if isinstance(sub_single, dict):
            self._collect_indicator_refs_from_condition(
                ConditionRef(**sub_single), f"{path}.args.condition", out
            )

    def _check_window(self, ind_args: dict, path: str) -> None:
        window = ind_args.get("window")
        if window is None:
            return
        if not isinstance(window, str):
            self.result.add_error(
                "resource", "UNSUPPORTED_WINDOW",
                f"指标 window 参数应为字符串，实际为 {type(window).__name__}: {window!r}",
                f"{path}.args.window",
            )
            return
        if window not in SUPPORTED_WINDOWS and window not in WINDOW_ALIASES:
            self.result.add_error(
                "resource", "UNSUPPORTED_WINDOW",
                f"不支持的 K 线周期: {window!r}，支持的周期: "
                f"{sorted(SUPPORTED_WINDOWS | WINDOW_ALIASES)}",
                f"{path}.args.window",
            )

    def _check_action_resource(self, action, path: str) -> None:
        if action.kind != "place_order":
            return
        qty = action.args.get("qty")
        valid = isinstance(qty, (int, float)) and not isinstance(qty, bool) and qty > 0
        if not valid:
            self.result.add_error(
                "resource", "INVALID_QTY",
                f"place_order 的 qty 必须 > 0，实际为: {qty!r}",
                f"{path}.args.qty",
            )


def validate(config: dict | StrategyDSL) -> ValidationResult:
    """便捷函数：等价于 DSLValidator().validate(config)。"""
    return DSLValidator().validate(config)
