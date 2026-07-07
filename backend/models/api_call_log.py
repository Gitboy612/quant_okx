from sqlalchemy import Column, Integer, String, DateTime, Text
from datetime import datetime, timezone
from database import Base


class ApiCallLog(Base):
    __tablename__ = "api_call_logs"

    id = Column(Integer, primary_key=True, index=True)
    strategy_instance_id = Column(Integer, nullable=True, index=True)
    account_name = Column(String, nullable=True)
    endpoint = Column(String, nullable=False)
    method = Column(String, nullable=False)
    request_body = Column(Text, nullable=True)
    response_code = Column(String, nullable=True)
    response_body = Column(Text, nullable=True)
    status = Column(String, default="success")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
