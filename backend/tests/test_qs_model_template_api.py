"""QS-Model 模板 API 测试。

验证 QS-Model v2.0 四段式配置的端到端流程：
- 创建含 qs_model_config 的模板，验证 logic_hash 被计算（SHA-256）
- 创建相同 logic 的第二个模板，验证 duplicate_hint 返回且不落库
- force=True 时强制创建成功
- 从 QS-Model 模板创建实例，验证 instance.logic_hash 和 params["qs_model_config"]
- 旧 dsl_config 模板仍可正常创建（向后兼容），dsl_config 也会计算 logic_hash

测试方式：FastAPI TestClient + 内存 SQLite + 覆盖 get_db / get_current_user 依赖。
与 test_dsl_template_api.py 风格一致，构建仅注册 strategies 路由的独立测试 app。
"""
import sys
import os
import hashlib
import json

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
    """建立内存 DB、覆盖依赖，返回 (client, SessionLocal, account_id)。"""
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
# 合法 QS-Model v2.0 配置
# ============================================================

VALID_QS_MODEL_CONFIG = {
    "qs_model_version": "2.0",
    "meta": {
        "name": "BTC 网格策略",
        "version": "v1.2.0",
        "author": "quant_team",
        "description": "基于网格的低频策略",
        "asset_class": "CRYPTO",
        "frequency": "15min",
        "base_symbol": "BTC-USDT",
    },
    "params": {
        "fast_period": {"label": "快均线周期", "value": 10, "type": "int", "range": [2, 100], "unit": "根"},
        "slow_period": {"label": "慢均线周期", "value": 30, "type": "int", "range": [10, 200], "unit": "根"},
    },
    "logic": {
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
                        "args": {"threshold": 0.05},
                    },
                },
                "then": [{"kind": "pause_orders"}, {"kind": "hold_position"}],
            }
        ],
    },
    "risk_filter": {
        "max_position_ratio": 0.8,
        "daily_max_loss": 0.05,
        "min_trade_size": 0.001,
        "blacklist_hours": ["00:00", "01:00"],
    },
}


# 仅 logic 段内容相同，meta/params/risk_filter 不同的第二个配置
# （logic_hash 只对 logic 段做哈希，因此应与 VALID_QS_MODEL_CONFIG 产生相同 hash）
DUPLICATE_LOGIC_QS_MODEL_CONFIG = {
    "qs_model_version": "2.0",
    "meta": {
        "name": "另一个名字的策略",
        "version": "v2.0.0",
        "base_symbol": "ETH-USDT",
    },
    "params": {},
    "logic": VALID_QS_MODEL_CONFIG["logic"],  # 引用相同 logic 段
    "risk_filter": None,
}


# 旧版 DSL 配置（向后兼容验证）
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
    "rules": [],
}


def _expected_logic_hash(qs_model_config: dict | None = None, dsl_config: dict | None = None) -> str:
    """复现 routers._compute_logic_hash 的计算逻辑，用于测试断言。"""
    if qs_model_config:
        logic_source = qs_model_config.get("logic", {}) or {}
    elif dsl_config:
        logic_source = dsl_config
    else:
        return None
    canonical = json.dumps(logic_source, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ============================================================
# 1. 创建含 qs_model_config 的模板，验证 logic_hash 被计算
# ============================================================


def test_create_template_with_qs_model_config(test_env):
    """POST /templates 传入含 qs_model_config 的请求：
    - 响应含 qs_model_config 和 logic_hash
    - logic_hash 为 SHA-256（64 位十六进制）
    - 数据库中 qs_model_config / logic_hash 非空
    - duplicate_hint 为 None（首次创建无重复）
    """
    client, SessionLocal, _ = test_env

    resp = client.post(
        "/api/strategies/templates",
        json={
            "name": "QS-Model 网格",
            "strategy_type": "composable",
            "description": "QS-Model v2.0 模板",
            "default_params": {"symbol": "BTC-USDT"},
            "qs_model_config": VALID_QS_MODEL_CONFIG,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["qs_model_config"] is not None, "qs_model_config 不应为 null"
    assert data["qs_model_config"]["qs_model_version"] == "2.0"
    assert data["qs_model_config"]["meta"]["base_symbol"] == "BTC-USDT"

    # logic_hash 被计算
    assert data["logic_hash"] is not None, "logic_hash 不应为 null"
    assert len(data["logic_hash"]) == 64, "SHA-256 应为 64 位十六进制"
    int(data["logic_hash"], 16)  # 应为合法十六进制

    # logic_hash 与预期一致（仅对 logic 段哈希）
    expected = _expected_logic_hash(qs_model_config=VALID_QS_MODEL_CONFIG)
    assert data["logic_hash"] == expected, f"logic_hash 不匹配：{data['logic_hash']} != {expected}"

    # 首次创建无重复提示
    assert data["duplicate_hint"] is None
    assert data["id"] is not None

    # 数据库中字段非空
    db = SessionLocal()
    try:
        from models.strategy import StrategyTemplate

        tmpl = db.query(StrategyTemplate).filter(StrategyTemplate.name == "QS-Model 网格").first()
        assert tmpl is not None
        assert tmpl.qs_model_config is not None
        assert tmpl.qs_model_config["qs_model_version"] == "2.0"
        assert tmpl.logic_hash == expected
        # dsl_config 保持为 None（未传旧字段）
        assert tmpl.dsl_config is None
    finally:
        db.close()


# ============================================================
# 2. 创建相同 logic 的第二个模板，验证 duplicate_hint 返回
# ============================================================


def test_duplicate_logic_hint(test_env):
    """创建第二个 logic 段相同的模板（不同 name）：
    - 响应 duplicate_hint 非空，包含已存在模板的名字
    - id 为 None（未落库）
    - 数据库中仍只有一个该 logic_hash 的模板
    """
    client, SessionLocal, _ = test_env

    # 先创建第一个
    client.post(
        "/api/strategies/templates",
        json={
            "name": "原始 QS-Model",
            "strategy_type": "composable",
            "default_params": {"symbol": "BTC-USDT"},
            "qs_model_config": VALID_QS_MODEL_CONFIG,
        },
    )

    # 再创建 logic 相同的第二个（不同 name，避免触发同名检查）
    resp = client.post(
        "/api/strategies/templates",
        json={
            "name": "重复逻辑 QS-Model",
            "strategy_type": "composable",
            "default_params": {"symbol": "ETH-USDT"},
            "qs_model_config": DUPLICATE_LOGIC_QS_MODEL_CONFIG,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # duplicate_hint 返回
    assert data["duplicate_hint"] is not None, "应返回 duplicate_hint"
    assert "原始 QS-Model" in data["duplicate_hint"], "提示应包含已存在模板的名字"
    assert "是否仍要创建" in data["duplicate_hint"]

    # id 为 None（未落库）
    assert data["id"] is None, "重复时不应落库，id 应为 None"

    # logic_hash 仍被计算
    assert data["logic_hash"] is not None

    # 数据库中没有名为「重复逻辑 QS-Model」的模板
    db = SessionLocal()
    try:
        from models.strategy import StrategyTemplate

        dup = db.query(StrategyTemplate).filter(
            StrategyTemplate.name == "重复逻辑 QS-Model"
        ).first()
        assert dup is None, "重复逻辑模板不应被写入数据库"

        # 该 logic_hash 的模板只有一个
        cnt = db.query(StrategyTemplate).filter(
            StrategyTemplate.logic_hash == data["logic_hash"]
        ).count()
        assert cnt == 1, "相同 logic_hash 的模板应只有一个"
    finally:
        db.close()


# ============================================================
# 3. force=True 时强制创建成功
# ============================================================


def test_force_create_duplicate_logic(test_env):
    """带 force=True 创建相同 logic 的模板：
    - 正常创建成功（id 非 None）
    - duplicate_hint 为 None
    - 数据库中存在两个相同 logic_hash 的模板
    """
    client, SessionLocal, _ = test_env

    # 先创建第一个
    client.post(
        "/api/strategies/templates",
        json={
            "name": "Force-原始",
            "strategy_type": "composable",
            "default_params": {"symbol": "BTC-USDT"},
            "qs_model_config": VALID_QS_MODEL_CONFIG,
        },
    )

    # force=True 创建第二个相同 logic
    resp = client.post(
        "/api/strategies/templates",
        json={
            "name": "Force-强制创建",
            "strategy_type": "composable",
            "default_params": {"symbol": "ETH-USDT"},
            "qs_model_config": DUPLICATE_LOGIC_QS_MODEL_CONFIG,
            "force": True,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # 强制创建成功
    assert data["id"] is not None, "force=True 时应正常创建"
    assert data["duplicate_hint"] is None, "force 创建时 duplicate_hint 应为 None"
    assert data["logic_hash"] is not None

    # 数据库中存在两个相同 logic_hash 的模板
    db = SessionLocal()
    try:
        from models.strategy import StrategyTemplate

        cnt = db.query(StrategyTemplate).filter(
            StrategyTemplate.logic_hash == data["logic_hash"]
        ).count()
        assert cnt == 2, "force 创建后应有 2 个相同 logic_hash 的模板"

        created = db.query(StrategyTemplate).filter(
            StrategyTemplate.name == "Force-强制创建"
        ).first()
        assert created is not None, "强制创建的模板应入库"
        assert created.qs_model_config is not None
    finally:
        db.close()


# ============================================================
# 4. 从 QS-Model 模板创建实例，验证 logic_hash 和 qs_model_config 注入
# ============================================================


def test_create_instance_from_qs_model_template(test_env):
    """从含 qs_model_config 的模板创建实例：
    - instance.logic_hash 等于模板的 logic_hash（逻辑版本快照）
    - instance.params["qs_model_config"] 含模板的 qs_model_config
    - 原有参数未被破坏
    """
    client, SessionLocal, account_id = test_env

    # 创建 QS-Model 模板
    create_resp = client.post(
        "/api/strategies/templates",
        json={
            "name": "QS-实例测试",
            "strategy_type": "composable",
            "default_params": {"symbol": "BTC-USDT", "order_qty": 0.01},
            "qs_model_config": VALID_QS_MODEL_CONFIG,
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    template_id = create_resp.json()["id"]
    template_logic_hash = create_resp.json()["logic_hash"]

    # 用该模板创建实例
    inst_resp = client.post(
        "/api/strategies/instances",
        json={
            "template_id": template_id,
            "account_id": account_id,
            "name": "QS 实例 1",
            "symbol": "BTC-USDT",
            "market_type": "spot",
            "params": {"order_qty": 0.02},
        },
    )
    assert inst_resp.status_code == 200, inst_resp.text
    assert "id" in inst_resp.json()

    # 验证数据库中的实例字段
    db = SessionLocal()
    try:
        from models.strategy import StrategyTemplate, StrategyInstance

        instance = db.query(StrategyInstance).order_by(StrategyInstance.id.desc()).first()
        assert instance is not None

        # logic_hash 快照
        assert instance.logic_hash is not None, "instance.logic_hash 应非空"
        assert instance.logic_hash == template_logic_hash, "instance.logic_hash 应等于模板 logic_hash"

        # qs_model_config 注入到 params
        assert "qs_model_config" in instance.params, "params 应含 qs_model_config"
        assert instance.params["qs_model_config"]["qs_model_version"] == "2.0"
        assert instance.params["qs_model_config"]["meta"]["base_symbol"] == "BTC-USDT"

        # 原有参数未被破坏
        assert instance.params["symbol"] == "BTC-USDT"
        assert instance.params["order_qty"] == 0.02
    finally:
        db.close()


# ============================================================
# 5. 旧 dsl_config 模板仍可正常创建（兼容）
# ============================================================


def test_create_template_with_legacy_dsl_config(test_env):
    """旧 dsl_config 模板创建：
    - 不传 qs_model_config，仅传 dsl_config
    - dsl_config 正常保存
    - logic_hash 从 dsl_config 计算（兼容回退）
    - 响应中 qs_model_config 自动包装为 QS-Model 结构（读取兼容）
    """
    client, SessionLocal, _ = test_env

    resp = client.post(
        "/api/strategies/templates",
        json={
            "name": "旧 DSL 兼容",
            "strategy_type": "composable",
            "default_params": {"symbol": "BTC-USDT"},
            "dsl_config": VALID_DSL_CONFIG,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # dsl_config 正常保存
    assert data["dsl_config"] is not None
    assert data["dsl_config"]["version"] == "1.0"
    assert data["dsl_config"]["base_strategy"]["kind"] == "grid"

    # logic_hash 从 dsl_config 计算
    assert data["logic_hash"] is not None, "dsl_config 也应计算 logic_hash"
    expected = _expected_logic_hash(dsl_config=VALID_DSL_CONFIG)
    assert data["logic_hash"] == expected

    # 读取兼容：qs_model_config 自动包装为 QS-Model 结构
    assert data["qs_model_config"] is not None, "旧 dsl_config 应被包装为 QS-Model"
    assert data["qs_model_config"]["qs_model_version"] == "2.0"
    assert data["qs_model_config"]["logic"] == VALID_DSL_CONFIG
    assert data["qs_model_config"]["risk_filter"] is None

    # 数据库中 qs_model_config 为 None（仅 dsl_config 入库），logic_hash 非空
    db = SessionLocal()
    try:
        from models.strategy import StrategyTemplate

        tmpl = db.query(StrategyTemplate).filter(StrategyTemplate.name == "旧 DSL 兼容").first()
        assert tmpl is not None
        assert tmpl.dsl_config is not None
        assert tmpl.qs_model_config is None, "未传 qs_model_config 时数据库应保持 None"
        assert tmpl.logic_hash == expected
    finally:
        db.close()


# ============================================================
# 6. 不传任何配置的传统模板仍可创建（完全向后兼容）
# ============================================================


def test_create_template_without_any_config(test_env):
    """不传 qs_model_config 也不传 dsl_config 的传统模板：
    - 创建成功
    - logic_hash 为 None
    - qs_model_config 为 None
    - duplicate_hint 为 None
    """
    client, _, _ = test_env

    resp = client.post(
        "/api/strategies/templates",
        json={
            "name": "传统硬编码策略",
            "strategy_type": "grid",
            "default_params": {"upper_price": 50000, "lower_price": 40000},
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] is not None
    assert data["logic_hash"] is None, "无配置时 logic_hash 应为 None"
    assert data["qs_model_config"] is None
    assert data["dsl_config"] is None
    assert data["duplicate_hint"] is None


# ============================================================
# 7. 不同 logic 段产生不同 logic_hash
# ============================================================


def test_different_logic_produces_different_hash(test_env):
    """两个 logic 段不同的模板应产生不同的 logic_hash，且都不会触发去重。"""
    client, _, _ = test_env

    config_a = {
        "qs_model_version": "2.0",
        "meta": {"name": "A", "base_symbol": "BTC-USDT"},
        "params": {},
        "logic": {
            "version": "1.0",
            "base_strategy": {"kind": "grid", "params": {"upper": 100}},
            "rules": [],
        },
        "risk_filter": None,
    }
    config_b = {
        "qs_model_version": "2.0",
        "meta": {"name": "B", "base_symbol": "ETH-USDT"},
        "params": {},
        "logic": {
            "version": "1.0",
            "base_strategy": {"kind": "grid", "params": {"upper": 200}},  # 不同值
            "rules": [],
        },
        "risk_filter": None,
    }

    resp_a = client.post(
        "/api/strategies/templates",
        json={
            "name": "不同逻辑-A",
            "strategy_type": "composable",
            "default_params": {},
            "qs_model_config": config_a,
        },
    )
    assert resp_a.status_code == 200
    hash_a = resp_a.json()["logic_hash"]

    resp_b = client.post(
        "/api/strategies/templates",
        json={
            "name": "不同逻辑-B",
            "strategy_type": "composable",
            "default_params": {},
            "qs_model_config": config_b,
        },
    )
    assert resp_b.status_code == 200
    hash_b = resp_b.json()["logic_hash"]

    assert hash_a != hash_b, "不同 logic 段应产生不同 logic_hash"
    assert resp_b.json()["duplicate_hint"] is None, "不同逻辑不应触发去重"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
