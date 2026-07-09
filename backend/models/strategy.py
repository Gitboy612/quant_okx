from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, ForeignKey
from datetime import datetime, timezone
from database import Base


class StrategyTemplate(Base):
    __tablename__ = "strategy_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    strategy_type = Column(String, nullable=False)
    description = Column(String, nullable=True)
    default_params = Column(JSON, nullable=False)
    param_schema = Column(JSON, nullable=True)
    is_builtin = Column(Boolean, default=False)
    is_custom = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    dsl_config = Column(JSON, nullable=True)  # 可拼接策略的 DSL 配置；NULL 表示传统硬编码策略（向后兼容）
    qs_model_config = Column(JSON, nullable=True)  # QS-Model v2.0 完整配置（四段式复合结构）
    logic_hash = Column(String, nullable=True, index=True)  # logic 段 SHA-256，用于重复逻辑去重


class StrategyInstance(Base):
    __tablename__ = "strategy_instances"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("strategy_templates.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    name = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    market_type = Column(String, nullable=False)
    params = Column(JSON, nullable=False)
    status = Column(String, default="stopped")
    started_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    logic_hash = Column(String, nullable=True)  # 创建实例时的逻辑版本快照
