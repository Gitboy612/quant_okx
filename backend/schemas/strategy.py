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
    dsl_config: dict | None = None  # 可拼接策略配置，可选

