from pydantic import BaseModel


class StrategyInstanceCreate(BaseModel):
    template_id: int
    account_id: int
    name: str
    symbol: str
    market_type: str
    params: dict


class StrategyInstanceUpdate(BaseModel):
    name: str | None = None
    params: dict | None = None


class StrategyTemplateCreate(BaseModel):
    name: str
    strategy_type: str
    description: str | None = None
    default_params: dict
    param_schema: dict | None = None
    dsl_config: dict | None = None  # 可拼接策略配置，可选（向后兼容）
    qs_model_config: dict | None = None  # QS-Model v2.0 完整配置（四段式复合结构）
    force: bool = False  # 检测到重复 logic_hash 时是否强制创建


class StrategyTemplateUpdate(BaseModel):
    """模板部分更新 schema（PUT /templates/{id}）。

    所有字段均为可选：仅更新请求中提供的字段，未提供字段保持原值。
    """
    name: str | None = None
    qs_model_config: dict | None = None
    dsl_config: dict | None = None
    default_params: dict | None = None
    param_schema: dict | None = None
    description: str | None = None


class StrategyTemplateResponse(BaseModel):
    """模板响应（含 QS-Model 字段与去重提示）。"""
    id: int
    name: str
    strategy_type: str
    description: str | None = None
    default_params: dict
    param_schema: dict | None = None
    is_builtin: bool
    is_custom: bool
    dsl_config: dict | None = None
    qs_model_config: dict | None = None
    logic_hash: str | None = None
    duplicate_hint: str | None = None

