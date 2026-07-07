from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from datetime import datetime, timezone
from database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    strategy_instance_id = Column(Integer, ForeignKey("strategy_instances.id"), nullable=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False)
    order_id = Column(String, nullable=True)
    side = Column(String, nullable=False)
    order_type = Column(String, nullable=False)
    price = Column(Float, nullable=True)
    quantity = Column(Float, nullable=True)
    filled_quantity = Column(Float, default=0)
    status = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
