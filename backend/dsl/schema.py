from pydantic import BaseModel, Field
from typing import Any, Literal


class BlockRef(BaseModel):
    """统一积木引用形态"""
    kind: str
    args: dict[str, Any] = Field(default_factory=dict)


class IndicatorRef(BlockRef):
    pass


class ConditionRef(BlockRef):
    pass


class ActionRef(BlockRef):
    pass


class EventRef(BlockRef):
    """事件类积木，kind 以 on_ 前缀"""
    pass


class Trigger(BaseModel):
    """Rule 的触发器：condition（每 tick 评估）或 event（仅事件发生时触发）或 event+extra_condition"""
    mode: Literal["condition", "event"] = "condition"
    condition: ConditionRef | None = None
    event: EventRef | None = None
    extra_condition: ConditionRef | None = None


class Rule(BaseModel):
    name: str
    when: Trigger
    then: list[ActionRef] = Field(default_factory=list)
    recover_when: Trigger | None = None
    recover_then: list[ActionRef] = Field(default_factory=list)
    cool_down_seconds: float = 0.0


class BaseStrategyRef(BaseModel):
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)


class StrategyDSL(BaseModel):
    version: Literal["1.0"] = "1.0"
    base_strategy: BaseStrategyRef
    rules: list[Rule] = Field(default_factory=list)


# ===================== QS-Model v2.0 四段式复合结构 =====================


class StrategyMeta(BaseModel):
    """QS-Model 元信息段：策略基本信息"""
    name: str
    version: str = "v1.0.0"
    author: str = ""
    description: str = ""
    asset_class: str = "CRYPTO"
    frequency: str = ""  # 如 15min/1h/1d
    base_symbol: str = ""  # 基准交易对，如 BTC-USDT


class ParamDefinition(BaseModel):
    """QS-Model 参数段：单个可变参数定义"""
    label: str  # 中文显示名，如"快均线周期"
    value: Any  # 默认值
    type: str  # int/float/string/bool/select
    range: list[Any] | None = None  # 取值范围 [min, max]
    description: str = ""
    options: list[Any] | None = None  # select 类型的选项
    option_labels: list[str] | None = None  # 选项中文标签
    unit: str = ""  # 单位，如 "%" / "秒"


class RiskFilter(BaseModel):
    """QS-Model 风控段：可选风险控制"""
    max_position_ratio: float | None = None  # 最大持仓比例
    daily_max_loss: float | None = None  # 每日最大亏损
    min_trade_size: float | None = None  # 最小交易量
    blacklist_hours: list[str] | None = None  # 黑名单时段，如 ["00:00", "01:00"]


class QSModelConfig(BaseModel):
    """QS-Model v2.0 完整配置：四段式复合结构"""
    qs_model_version: str = "2.0"
    meta: StrategyMeta
    params: dict[str, ParamDefinition] = Field(default_factory=dict)  # 参数名 -> 定义
    logic: StrategyDSL  # 复用现有 StrategyDSL
    risk_filter: RiskFilter | None = None


# ===================== 变量引用解析 =====================


_PARAMS_PREFIX = "$params."
_META_PREFIX = "$meta."


def _resolve_value(value: Any, params: dict[str, ParamDefinition],
                   param_overrides: dict[str, Any] | None,
                   meta_dict: dict[str, Any]) -> Any:
    """递归解析单个值：若是字符串变量引用则替换，否则递归处理 dict/list。"""
    if isinstance(value, str):
        if value.startswith(_PARAMS_PREFIX):
            key = value[len(_PARAMS_PREFIX):]
            if param_overrides is not None and key in param_overrides:
                return param_overrides[key]
            if key in params:
                return params[key].value
            # 找不到引用则原样返回
            return value
        if value.startswith(_META_PREFIX):
            key = value[len(_META_PREFIX):]
            if key in meta_dict:
                return meta_dict[key]
            return value
        return value
    if isinstance(value, dict):
        return {k: _resolve_value(v, params, param_overrides, meta_dict)
                for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(v, params, param_overrides, meta_dict)
                for v in value]
    return value


def resolve_variables(qs_model: QSModelConfig,
                      param_overrides: dict[str, Any] | None = None) -> StrategyDSL:
    """
    解析 QS-Model 中的变量引用，返回最终可执行的 StrategyDSL。

    - 遍历 logic 段中所有参数值
    - 若值是字符串且以 "$params." 开头，替换为 params 中对应参数的 value（优先用 param_overrides）
    - 若值是字符串且以 "$meta." 开头，替换为 meta 中对应字段值
    - 其它值保持不变
    - 返回新的 StrategyDSL 对象（不修改原对象）
    """
    # model_dump() 默认深拷贝返回纯 dict/list 结构，修改不影响原对象
    logic_data = qs_model.logic.model_dump()
    params = qs_model.params
    meta_dict = qs_model.meta.model_dump()

    resolved = _resolve_value(logic_data, params, param_overrides, meta_dict)
    return StrategyDSL.model_validate(resolved)
