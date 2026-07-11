from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON
from datetime import datetime, timezone
from database import Base


class NotificationRule(Base):
    """通知规则模型。

    每条规则定义：哪些事件类型（event_types）触发哪个渠道（channel_type），
    以及该渠道的具体配置（channel_config，如 SMTP/webhook_url/bot_token 等）。

    event_types 为 JSON 数组，支持 "*" 通配符匹配所有事件。
    """
    __tablename__ = "notification_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    event_types = Column(JSON, nullable=False, default=list)  # ["order_failed", "strategy_error", ...]
    channel_type = Column(String, nullable=False)  # "email" | "webhook" | "telegram"
    channel_config = Column(JSON, nullable=False, default=dict)  # 渠道特定配置
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
