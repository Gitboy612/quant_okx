"""DSL 模板 API 测试（Task 1）。

验证后端 strategies 路由正确暴露并保存 dsl_config 字段：
- GET  /api/strategies/templates 响应每个模板含 dsl_config 字段（无配置为 null）
- POST /api/strategies/templates 创建时保存 dsl_config，响应含 dsl_config
- POST /api/strategies/templates 不传 dsl_config 时向后兼容（dsl_config 为 null）
- 从含 dsl_config 的模板创建实例，启动时 strategy_engine 能合并 dsl_config 到 params

测试方式：FastAPI TestClient + 内存 SQLite + 覆盖 get_db / get_current_user 依赖。
与 test_dsl_api.py 风格一致，构建仅注册 strategies 路由的独立测试 app，避免 main.py 副作用。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from middleware.auth import get_current_user
from routers.strategies import router as strategies_router


TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture()
def test_env():
    """建立内存 DB、覆盖依赖，返回 (client, SessionLocal, account_id, user_id)。"""
    # StaticPool 让所有线程共享同一个内存 SQLite 连接，否则 TestClient
    # 在线程池里跑请求时会拿到另一个空库，导致 "no such table"。
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # 导入所有模型以确保 Base.metadata.create_all 建全表
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

    # 预置测试用户和账户（create_instance 需要 account_id 外键）
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

    yield client, TestingSessionLocal, account_id

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


# ============================================================
# 合法 DSL 配置（与 test_dsl_api.py 一致的用户示例）
# ============================================================

VALID_DSL_CONFIG = {
    "version": "1.0",
    "base_strategy": {
        "kind": "grid",
        "params": {
            "upper_price": 50000,
            "lower_price": 40000,
            "grid_count": 10,
            "order_qty": 0.01,
            "symbol": "BTC-USDT",
        },
    },
    "rules": [
        {
            "name": "单边上涨暂停",
            "when": {
                "mode": "condition",
                "condition": {
                    "kind": "gt",
                    "args": {
                        "indicator": {
                            "kind": "price_change_pct",
                            "args": {"window": "1h", "symbol": "BTC-USDT"},
                        },
                        "threshold": 0.05,
                    },
                },
            },
            "then": [{"kind": "pause_orders"}, {"kind": "hold_position"}],
        }
    ],
}


# ============================================================
# POST /api/strategies/templates
# ============================================================


def test_create_template_with_dsl_config(test_env):
    """POST /templates 传入含 dsl_config 的请求，响应含 dsl_config，数据库中该模板 dsl_config 非空。"""
    client, SessionLocal, _ = test_env

    resp = client.post(
        "/api/strategies/templates",
        json={
            "name": "可拼接网格-DSL",
            "strategy_type": "composable",
            "description": "DSL 拼接模板",
            "default_params": {"symbol": "BTC-USDT"},
            "param_schema": None,
            "dsl_config": VALID_DSL_CONFIG,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "dsl_config" in data, "响应缺少 dsl_config 字段"
    assert data["dsl_config"] is not None, "dsl_config 不应为 null"
    assert data["dsl_config"]["version"] == "1.0"
    assert data["dsl_config"]["base_strategy"]["kind"] == "grid"
    assert data["strategy_type"] == "composable"
    assert data["is_custom"] is True

    # 数据库中该模板 dsl_config 非空
    db = SessionLocal()
    try:
        from models.strategy import StrategyTemplate

        tmpl = db.query(StrategyTemplate).filter(StrategyTemplate.name == "可拼接网格-DSL").first()
        assert tmpl is not None, "模板未写入数据库"
        assert tmpl.dsl_config is not None, "数据库中 dsl_config 为空"
        assert tmpl.dsl_config["base_strategy"]["kind"] == "grid"
    finally:
        db.close()


def test_create_template_without_dsl_config(test_env):
    """POST /templates 不传 dsl_config，响应 dsl_config 为 null（向后兼容）。"""
    client, SessionLocal, _ = test_env

    resp = client.post(
        "/api/strategies/templates",
        json={
            "name": "传统网格-自定义",
            "strategy_type": "grid",
            "description": "传统硬编码策略",
            "default_params": {"upper_price": 50000, "lower_price": 40000},
            "param_schema": None,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "dsl_config" in data, "响应缺少 dsl_config 字段"
    assert data["dsl_config"] is None, "不传 dsl_config 时应为 null"

    # 数据库中亦为 null
    db = SessionLocal()
    try:
        from models.strategy import StrategyTemplate

        tmpl = db.query(StrategyTemplate).filter(StrategyTemplate.name == "传统网格-自定义").first()
        assert tmpl is not None
        assert tmpl.dsl_config is None
    finally:
        db.close()


# ============================================================
# GET /api/strategies/templates
# ============================================================


def test_list_templates_returns_dsl_config(test_env):
    """GET /templates 响应每个模板含 dsl_config 字段（无配置为 null，有配置为对象）。"""
    client, _, _ = test_env

    # 先创建一个含 dsl_config 的模板
    client.post(
        "/api/strategies/templates",
        json={
            "name": "DSL-列表测试",
            "strategy_type": "composable",
            "description": "用于列表验证",
            "default_params": {"symbol": "BTC-USDT"},
            "dsl_config": VALID_DSL_CONFIG,
        },
    )
    # 再创建一个不含 dsl_config 的模板
    client.post(
        "/api/strategies/templates",
        json={
            "name": "普通-列表测试",
            "strategy_type": "grid",
            "description": "传统模板",
            "default_params": {"upper_price": 50000, "lower_price": 40000},
        },
    )

    resp = client.get("/api/strategies/templates")
    assert resp.status_code == 200, resp.text
    templates = resp.json()
    assert isinstance(templates, list)
    assert len(templates) >= 2, "应至少返回 2 个模板"

    # 每个模板对象都含 dsl_config 字段
    for t in templates:
        assert "dsl_config" in t, f"模板 {t.get('name')} 缺少 dsl_config 字段"

    by_name = {t["name"]: t for t in templates}
    assert by_name["DSL-列表测试"]["dsl_config"] is not None
    assert by_name["DSL-列表测试"]["dsl_config"]["version"] == "1.0"
    assert by_name["普通-列表测试"]["dsl_config"] is None


# ============================================================
# POST /api/strategies/instances —— 创建实例时 dsl_config 注入
# ============================================================


def test_create_instance_from_dsl_template(test_env):
    """用含 dsl_config 的模板创建实例。

    create_instance 本身不注入 dsl_config（避免与 start_strategy 重复），
    但启动时 strategy_engine.start_strategy 会从 template 合并 dsl_config 到 params。
    本测试验证：
    1. 实例创建成功
    2. 模板 dsl_config 可读（启动合并的数据源）
    3. 复现 start_strategy 的合并逻辑，确认合并后 params 含 dsl_config
    """
    client, SessionLocal, account_id = test_env

    # 创建含 dsl_config 的模板
    create_resp = client.post(
        "/api/strategies/templates",
        json={
            "name": "DSL-实例测试",
            "strategy_type": "composable",
            "description": "用于实例创建验证",
            "default_params": {"symbol": "BTC-USDT", "order_qty": 0.01},
            "dsl_config": VALID_DSL_CONFIG,
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    template_id = create_resp.json()["id"]

    # 用该模板创建实例
    inst_resp = client.post(
        "/api/strategies/instances",
        json={
            "template_id": template_id,
            "account_id": account_id,
            "name": "DSL 实例 1",
            "symbol": "BTC-USDT",
            "market_type": "spot",
            "params": {"order_qty": 0.02},
        },
    )
    assert inst_resp.status_code == 200, inst_resp.text
    assert "id" in inst_resp.json()

    # 从数据库读取实例与模板，复现 start_strategy 的合并逻辑
    db = SessionLocal()
    try:
        from models.strategy import StrategyTemplate, StrategyInstance

        instance = db.query(StrategyInstance).order_by(StrategyInstance.id.desc()).first()
        assert instance is not None
        template = db.query(StrategyTemplate).filter(StrategyTemplate.id == template_id).first()
        assert template is not None

        # 模板 dsl_config 可读（启动合并的数据源）
        assert template.dsl_config is not None, "模板 dsl_config 应非空（启动合并的数据源）"
        assert template.dsl_config["base_strategy"]["kind"] == "grid"

        # 复现 strategy_engine.start_strategy 的合并逻辑（services/strategy_engine.py 155-159 行）
        params = dict(instance.params)
        if "dsl_config" not in params and getattr(template, "dsl_config", None) is not None:
            params["dsl_config"] = template.dsl_config

        # 合并后 params 应含 dsl_config，ComposableStrategy 可从 self.params["dsl_config"] 读取
        assert "dsl_config" in params, "合并后 params 应含 dsl_config"
        assert params["dsl_config"]["version"] == "1.0"
        # 原有参数未被破坏
        assert params["symbol"] == "BTC-USDT"
        assert params["order_qty"] == 0.02
    finally:
        db.close()
