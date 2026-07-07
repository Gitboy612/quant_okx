from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime, timezone
from database import Base


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    api_key_encrypted = Column(String, nullable=False)
    secret_key_encrypted = Column(String, nullable=False)
    passphrase_encrypted = Column(String, nullable=True)
    trade_mode = Column(String, default="demo")
    exchange = Column(String, default="okx")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
