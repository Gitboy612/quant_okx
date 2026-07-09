"""P0 条件积木库。

提供可拼接策略 DSL 中最基础的条件类积木，分为两组：

- 比较类（category="比较"）：gt / lt / abs_gt / abs_lt
  对单个指标值与阈值做数值比较。
- 逻辑组合类（category="逻辑"）：and / or / not
  对嵌套的子条件（ConditionRef）做布尔组合。

所有条件类通过 `@condition(kind)` 装饰器注册到 `condition_registry`，
执行器与嵌套条件统一通过本模块导出的 `evaluate_condition` 递归求值。
"""
from dsl.registry import condition, condition_registry
from dsl.schema import ConditionRef, IndicatorRef
from dsl.context import ExecutionContext


async def _resolve_indicator_value(ref: IndicatorRef, ctx: ExecutionContext):
    """解析 IndicatorRef 并计算其值（带缓存）。

    优先复用指标库（dsl.blocks.indicators）的 `compute_indicator`；
    若指标库尚未实现（ImportError），则回退到从 `indicator_registry`
    取指标类、实例化并调用其 `compute` 方法，结果按 (kind, args) 缓存到
    `ctx.indicator_cache`，同 tick 内复用。
    """
    try:
        from dsl.blocks.indicators import compute_indicator
        return await compute_indicator(ref, ctx)
    except ImportError:
        # 回退：直接从注册表取指标类计算
        from dsl.registry import indicator_registry
        key = (ref.kind, tuple(sorted(ref.args.items())))
        if key in ctx.indicator_cache:
            return ctx.indicator_cache[key]
        cls = indicator_registry.get(ref.kind)
        if cls is None:
            raise ValueError(f"未知指标 kind: {ref.kind}")
        inst = cls(**ref.args)
        value = await inst.compute(ctx)
        ctx.indicator_cache[key] = value
        return value


async def evaluate_condition(ref: ConditionRef, ctx: ExecutionContext) -> bool:
    """递归求值 ConditionRef。

    供执行器与嵌套条件（and/or/not）复用：根据 ref.kind 从
    `condition_registry` 取出条件类，实例化后调用 `evaluate`。
    未注册的 kind 抛 ValueError。
    """
    cls = condition_registry.get(ref.kind)
    if cls is None:
        raise ValueError(f"未知条件 kind: {ref.kind}")
    inst = cls(**ref.args)
    return await inst.evaluate(ctx)


# ============================ 比较类 ============================


@condition("gt")
class GreaterThan:
    """指标值大于阈值。"""

    category = "比较"
    description = "指标值大于阈值"
    input_type = "number"
    priority = "P0"
    param_schema = {
        "indicator": {"type": "object", "required": True, "description": "指标引用 {kind, args}"},
        "threshold": {"type": "number", "required": True, "description": "阈值"},
    }

    def __init__(self, indicator: dict, threshold: float):
        self.indicator_ref = IndicatorRef(**indicator)
        self.threshold = float(threshold)

    async def evaluate(self, ctx: ExecutionContext) -> bool:
        value = await _resolve_indicator_value(self.indicator_ref, ctx)
        return float(value) > self.threshold


@condition("lt")
class LessThan:
    """指标值小于阈值。"""

    category = "比较"
    description = "指标值小于阈值"
    input_type = "number"
    priority = "P0"
    param_schema = {
        "indicator": {"type": "object", "required": True, "description": "指标引用 {kind, args}"},
        "threshold": {"type": "number", "required": True, "description": "阈值"},
    }

    def __init__(self, indicator: dict, threshold: float):
        self.indicator_ref = IndicatorRef(**indicator)
        self.threshold = float(threshold)

    async def evaluate(self, ctx: ExecutionContext) -> bool:
        value = await _resolve_indicator_value(self.indicator_ref, ctx)
        return float(value) < self.threshold


@condition("abs_gt")
class AbsGreaterThan:
    """指标值的绝对值大于阈值。"""

    category = "比较"
    description = "指标值的绝对值大于阈值"
    input_type = "number"
    priority = "P0"
    param_schema = {
        "indicator": {"type": "object", "required": True, "description": "指标引用 {kind, args}"},
        "threshold": {"type": "number", "required": True, "description": "阈值"},
    }

    def __init__(self, indicator: dict, threshold: float):
        self.indicator_ref = IndicatorRef(**indicator)
        self.threshold = float(threshold)

    async def evaluate(self, ctx: ExecutionContext) -> bool:
        value = await _resolve_indicator_value(self.indicator_ref, ctx)
        return abs(float(value)) > self.threshold


@condition("abs_lt")
class AbsLessThan:
    """指标值的绝对值小于阈值。"""

    category = "比较"
    description = "指标值的绝对值小于阈值"
    input_type = "number"
    priority = "P0"
    param_schema = {
        "indicator": {"type": "object", "required": True, "description": "指标引用 {kind, args}"},
        "threshold": {"type": "number", "required": True, "description": "阈值"},
    }

    def __init__(self, indicator: dict, threshold: float):
        self.indicator_ref = IndicatorRef(**indicator)
        self.threshold = float(threshold)

    async def evaluate(self, ctx: ExecutionContext) -> bool:
        value = await _resolve_indicator_value(self.indicator_ref, ctx)
        return abs(float(value)) < self.threshold


# ============================ 逻辑组合类 ============================


@condition("and")
class AndCondition:
    """所有子条件均为真。"""

    category = "逻辑"
    description = "所有子条件均为真"
    input_type = "bool"
    priority = "P0"
    param_schema = {
        "conditions": {"type": "array", "required": True, "description": "子条件列表"},
    }

    def __init__(self, conditions: list):
        self.condition_refs = [ConditionRef(**c) for c in conditions]

    async def evaluate(self, ctx: ExecutionContext) -> bool:
        for ref in self.condition_refs:
            if not await evaluate_condition(ref, ctx):
                return False
        return True


@condition("or")
class OrCondition:
    """任一子条件为真。"""

    category = "逻辑"
    description = "任一子条件为真"
    input_type = "bool"
    priority = "P0"
    param_schema = {
        "conditions": {"type": "array", "required": True, "description": "子条件列表"},
    }

    def __init__(self, conditions: list):
        self.condition_refs = [ConditionRef(**c) for c in conditions]

    async def evaluate(self, ctx: ExecutionContext) -> bool:
        for ref in self.condition_refs:
            if await evaluate_condition(ref, ctx):
                return True
        return False


@condition("not")
class NotCondition:
    """子条件取反。"""

    category = "逻辑"
    description = "子条件取反"
    input_type = "bool"
    priority = "P0"
    param_schema = {
        "condition": {"type": "object", "required": True, "description": "单个子条件 {kind, args}"},
    }

    def __init__(self, condition: dict):
        self.condition_ref = ConditionRef(**condition)

    async def evaluate(self, ctx: ExecutionContext) -> bool:
        return not await evaluate_condition(self.condition_ref, ctx)
