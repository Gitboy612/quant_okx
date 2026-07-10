"""UTC 时间序列化测试（Task 16）。

验证 routers/logs.py 与 routers/strategies.py 输出的时间字段：
- 始终以 'Z' 后缀标注 UTC
- naive datetime（SQLite 存储丢失 tzinfo 的情况）视为 UTC
- aware datetime 转换为 UTC
- None 仍返回 None

测试方式：FastAPI TestClient + 内存 SQLite + 覆盖 get_db / get_current_user 依赖。
"""
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from middleware.auth import get_current_user
from routers.logs import router as logs_router, to_utc_iso as logs_to_utc_iso
from routers.strategies import router as strategies_router, to_utc_iso as strat_to_utc_iso


TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture()
def test_env():
    """建立内存 DB、注册 logs + strategies 路由，返回 (client, SessionLocal, user_id)。"""
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    from models.user import User
    from models.account import Account
    from models.strategy import StrategyTemplate, StrategyInstance
    from models.order import Order
    from models.pnl import PnlRecord
    from models.log import OperationLog
    from models.api_call_log import ApiCallLog
    from models.setting import UserSetting
    from models.system_settings import SystemSetting
    from models.strategy_event import StrategyEvent

    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    user = User(username="tester", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    account = Account(
        name="test-account",
        api_key_encrypted="k",
        secret_key_encrypted="s",
        passphrase_encrypted="p",
        trade_mode="demo",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    user_id = user.id
    account_id = account.id
    db.close()

    test_app = FastAPI()
    test_app.include_router(logs_router)
    test_app.include_router(strategies_router)

    def override_get_db():
        db_session = TestingSessionLocal()
        try:
            yield db_session
        finally:
            db_session.close()

    class _MockUser:
        def __init__(self, uid):
            self.id = uid

    def override_get_current_user():
        return _MockUser(user_id)

    test_app.dependency_overrides[get_db] = override_get_db
    test_app.dependency_overrides[get_current_user] = override_get_current_user

    client = TestClient(test_app)

    yield client, TestingSessionLocal, user_id, account_id

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


# ============================================================
# 1. to_utc_iso 辅助函数单元测试
# ============================================================


def test_to_utc_iso_none():
    """None 输入返回 None。"""
    assert logs_to_utc_iso(None) is None
    assert strat_to_utc_iso(None) is None


def test_to_utc_iso_naive_datetime():
    """naive datetime（无 tzinfo）视为 UTC，输出以 Z 结尾。"""
    dt = datetime(2024, 1, 1, 12, 30, 45)
    result = logs_to_utc_iso(dt)
    assert result is not None
    assert result.endswith("Z"), f"应以 Z 结尾，实际: {result}"
    assert "+00:00" not in result, f"不应包含 +00:00，实际: {result}"
    # 验证时间值未被改变
    assert result == "2024-01-01T12:30:45Z"

    # strategies 模块的辅助函数行为一致
    assert strat_to_utc_iso(dt) == "2024-01-01T12:30:45Z"


def test_to_utc_iso_aware_datetime_converted_to_utc():
    """aware datetime（有 tzinfo）转换为 UTC，输出以 Z 结尾。"""
    # UTC+8 时间（北京时间 20:00:00 = UTC 12:00:00）
    cst = timezone(timedelta(hours=8))
    dt = datetime(2024, 1, 1, 20, 0, 0, tzinfo=cst)
    result = logs_to_utc_iso(dt)
    assert result is not None
    assert result.endswith("Z"), f"应以 Z 结尾，实际: {result}"
    assert "+00:00" not in result
    # 应转换为 UTC 12:00:00
    assert result == "2024-01-01T12:00:00Z", f"应转换为 UTC，实际: {result}"


def test_to_utc_iso_already_utc():
    """已经是 UTC 的 aware datetime 输出以 Z 结尾。"""
    dt = datetime(2024, 6, 15, 8, 0, 0, tzinfo=timezone.utc)
    result = strat_to_utc_iso(dt)
    assert result == "2024-06-15T08:00:00Z"


def test_to_utc_iso_with_microseconds():
    """带微秒的 datetime 保留微秒且以 Z 结尾。"""
    dt = datetime(2024, 1, 1, 12, 30, 45, 123456)
    result = logs_to_utc_iso(dt)
    assert result is not None
    assert result.endswith("Z")
    assert result == "2024-01-01T12:30:45.123456Z"


def test_to_utc_iso_negative_timezone():
    """负时区（如 UTC-5）的 aware datetime 正确转换为 UTC。"""
    est = timezone(timedelta(hours=-5))
    # 纽约时间 07:00:00 = UTC 12:00:00
    dt = datetime(2024, 1, 1, 7, 0, 0, tzinfo=est)
    result = strat_to_utc_iso(dt)
    assert result == "2024-01-01T12:00:00Z"


# ============================================================
# 2. /api/logs 端点 - created_at 带 Z 后缀
# ============================================================


def test_logs_api_created_at_has_z_suffix(test_env):
    """GET /api/logs 返回的 created_at 应以 Z 结尾。

    SQLite 存储的 naive datetime 应被序列化为 UTC + Z。
    """
    client, SessionLocal, user_id, _ = test_env

    # 直接写入一条操作日志（模拟 SQLite 存储的 naive datetime）
    db = SessionLocal()
    try:
        from models.log import OperationLog

        log = OperationLog(
            user_id=user_id,
            action="test_action",
            target_type="test",
            target_id=1,
            detail={"k": "v"},
            ip_address="127.0.0.1",
            created_at=datetime(2024, 1, 1, 12, 0, 0),  # naive datetime
        )
        db.add(log)
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/logs")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] >= 1
    item = data["items"][0]
    assert item["created_at"] is not None
    assert item["created_at"].endswith("Z"), f"created_at 应以 Z 结尾，实际: {item['created_at']}"
    assert "+00:00" not in item["created_at"]
    assert item["created_at"] == "2024-01-01T12:00:00Z"


# ============================================================
# 3. /api/strategies/instances 端点 - 时间字段带 Z 后缀
# ============================================================


def test_instances_api_time_fields_have_z_suffix(test_env):
    """GET /api/strategies/instances 返回的时间字段（started_at / stopped_at /
    created_at / updated_at）均应以 Z 结尾。"""
    client, SessionLocal, user_id, account_id = test_env

    # 创建模板
    resp = client.post(
        "/api/strategies/templates",
        json={
            "name": "UTC 序列化测试模板",
            "strategy_type": "grid",
            "default_params": {"symbol": "BTC-USDT"},
        },
    )
    assert resp.status_code == 200, resp.text
    template_id = resp.json()["id"]

    # 创建实例（触发 created_at / updated_at 写入）
    resp = client.post(
        "/api/strategies/instances",
        json={
            "template_id": template_id,
            "account_id": account_id,
            "name": "UTC 实例",
            "symbol": "BTC-USDT",
            "market_type": "spot",
            "params": {},
        },
    )
    assert resp.status_code == 200, resp.text

    # 直接更新 started_at / stopped_at 为 naive datetime（模拟 SQLite 存储）
    db = SessionLocal()
    try:
        from models.strategy import StrategyInstance

        inst = db.query(StrategyInstance).order_by(StrategyInstance.id.desc()).first()
        assert inst is not None
        inst.started_at = datetime(2024, 1, 2, 10, 0, 0)  # naive
        inst.stopped_at = datetime(2024, 1, 3, 11, 30, 0)  # naive
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/strategies/instances")
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) >= 1
    inst_data = items[0]

    # 所有时间字段都应以 Z 结尾
    for field in ("started_at", "stopped_at", "created_at", "updated_at"):
        value = inst_data.get(field)
        assert value is not None, f"{field} 不应为 None"
        assert value.endswith("Z"), f"{field} 应以 Z 结尾，实际: {value}"
        assert "+00:00" not in value, f"{field} 不应包含 +00:00，实际: {value}"

    # 验证具体值（naive datetime 视为 UTC）
    assert inst_data["started_at"] == "2024-01-02T10:00:00Z"
    assert inst_data["stopped_at"] == "2024-01-03T11:30:00Z"


# ============================================================
# 4. /api/strategies/api-call-logs 端点 - created_at 带 Z 后缀
# ============================================================


def test_api_call_logs_created_at_has_z_suffix(test_env):
    """GET /api/strategies/api-call-logs 返回的 created_at 应以 Z 结尾。"""
    client, SessionLocal, user_id, account_id = test_env

    db = SessionLocal()
    try:
        from models.api_call_log import ApiCallLog

        log = ApiCallLog(
            strategy_instance_id=1,
            account_name="test-account",
            endpoint="/api/v5/market/ticker",
            method="GET",
            request_body=None,
            response_code="200",
            response_body='{"code":"0"}',
            status="success",
            created_at=datetime(2024, 1, 1, 9, 15, 0),  # naive
        )
        db.add(log)
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/strategies/api-call-logs")
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) >= 1
    item = items[0]
    assert item["created_at"] is not None
    assert item["created_at"].endswith("Z"), f"created_at 应以 Z 结尾，实际: {item['created_at']}"
    assert "+00:00" not in item["created_at"]
    assert item["created_at"] == "2024-01-01T09:15:00Z"


# ============================================================
# 5. None 时间字段仍返回 None
# ============================================================


def test_none_time_fields_return_none(test_env):
    """未设置的 started_at / stopped_at 应返回 None（不报错）。"""
    client, SessionLocal, user_id, account_id = test_env

    resp = client.post(
        "/api/strategies/templates",
        json={
            "name": "None 时间测试模板",
            "strategy_type": "grid",
            "default_params": {"symbol": "BTC-USDT"},
        },
    )
    template_id = resp.json()["id"]

    client.post(
        "/api/strategies/instances",
        json={
            "template_id": template_id,
            "account_id": account_id,
            "name": "None 时间实例",
            "symbol": "BTC-USDT",
            "market_type": "spot",
            "params": {},
        },
    )

    resp = client.get("/api/strategies/instances")
    items = resp.json()
    inst_data = items[0]
    # 新建实例未启动，started_at / stopped_at 应为 None
    assert inst_data["started_at"] is None
    assert inst_data["stopped_at"] is None
    # created_at / updated_at 应为带 Z 的字符串
    assert inst_data["created_at"] is not None
    assert inst_data["created_at"].endswith("Z")
    assert inst_data["updated_at"] is not None
    assert inst_data["updated_at"].endswith("Z")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
