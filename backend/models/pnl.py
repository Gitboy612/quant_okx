from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, Boolean, Index
from datetime import datetime, timezone
from database import Base


class PnlRecord(Base):
    __tablename__ = "pnl_records"

    __table_args__ = (
        Index("ix_pnl_records_strategy_recorded", "strategy_instance_id", "recorded_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    strategy_instance_id = Column(Integer, ForeignKey("strategy_instances.id"), nullable=True)
    equity = Column(Float, nullable=True)
    unrealized_pnl = Column(Float, nullable=True)
    realized_pnl = Column(Float, nullable=True)
    total_pnl = Column(Float, nullable=True)
    is_final = Column(Boolean, default=False, nullable=False, server_default="0")
    recorded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
