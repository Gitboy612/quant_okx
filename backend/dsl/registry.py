from typing import Any, Callable


class Registry:
    """积木注册表：kind -> 实现类/工厂"""

    def __init__(self, block_type: str):
        self._block_type = block_type
        self._registry: dict[str, Any] = {}

    def register(self, kind: str, cls: Any) -> None:
        if kind in self._registry:
            # 允许重复注册（测试场景），后者覆盖前者
            pass
        self._registry[kind] = cls

    def get(self, kind: str) -> Any | None:
        return self._registry.get(kind)

    def exists(self, kind: str) -> bool:
        return kind in self._registry

    def list(self) -> list[dict[str, Any]]:
        """返回所有已注册积木的元数据，供前端展示与校验器使用。
        每项形如：{kind, category, label, description, param_schema, output_type, priority, display_template}
        其中 label 与 display_template 为可选元数据（积木类未定义时为 None）。
        """
        result = []
        for kind, cls in self._registry.items():
            result.append({
                "kind": kind,
                "category": getattr(cls, "category", "未分类"),
                "label": getattr(cls, "label", None),
                "description": getattr(cls, "description", ""),
                "param_schema": getattr(cls, "param_schema", {}),
                "output_type": getattr(cls, "output_type", None),
                "priority": getattr(cls, "priority", "P1"),
                "display_template": getattr(cls, "display_template", None),
            })
        return result

    def __contains__(self, kind: str) -> bool:
        return kind in self._registry


# 五个全局注册表
indicator_registry = Registry("indicator")
condition_registry = Registry("condition")
action_registry = Registry("action")
event_registry = Registry("event")
base_strategy_registry = Registry("base_strategy")


def indicator(kind: str):
    def deco(cls):
        indicator_registry.register(kind, cls)
        return cls
    return deco


def condition(kind: str):
    def deco(cls):
        condition_registry.register(kind, cls)
        return cls
    return deco


def action(kind: str):
    def deco(cls):
        action_registry.register(kind, cls)
        return cls
    return deco


def event(kind: str):
    def deco(cls):
        event_registry.register(kind, cls)
        return cls
    return deco


def base_strategy(kind: str):
    def deco(cls):
        base_strategy_registry.register(kind, cls)
        return cls
    return deco
