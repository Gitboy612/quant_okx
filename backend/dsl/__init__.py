"""可拼接策略 DSL（积木式策略语言）模块。

导入 schema 与 registry 以便外部直接使用 from dsl import StrategyDSL。
积木库（blocks/）在各子模块中通过装饰器自动注册，需在 ComposableStrategy 首次使用前导入一次。
"""
from dsl.schema import (
    StrategyDSL, Rule, Trigger, BaseStrategyRef,
    BlockRef, IndicatorRef, ConditionRef, ActionRef, EventRef,
    QSModelConfig, StrategyMeta, ParamDefinition, RiskFilter,
    resolve_variables,
)
from dsl.registry import (
    Registry, indicator_registry, condition_registry, action_registry,
    event_registry, base_strategy_registry,
    indicator, condition, action, event, base_strategy,
)

__all__ = [
    "StrategyDSL", "Rule", "Trigger", "BaseStrategyRef",
    "BlockRef", "IndicatorRef", "ConditionRef", "ActionRef", "EventRef",
    "QSModelConfig", "StrategyMeta", "ParamDefinition", "RiskFilter",
    "resolve_variables",
    "Registry", "indicator_registry", "condition_registry", "action_registry",
    "event_registry", "base_strategy_registry",
    "indicator", "condition", "action", "event", "base_strategy",
]
