"""策略模板导出 / 导入（分享功能）测试。

验证 GET /api/strategies/templates/{id}/export 与
POST /api/strategies/templates/import 端到端流程：

1. 导出端点：创建模板 → 导出 → 验证 JSON 结构与 Content-Disposition
2. 导入端点：用导出的 JSON 导入 → 验证新模板字段与 logic_hash 一致性
3. 导入校验：无效请求体 / 缺少必填字段 / 不兼容版本 / QS-Model 结构非法
4. logic_hash 一致性：相同配置导出再导入，hash 应保持一致

测试方式：FastAPI TestClient + 内存 SQLite + 覆盖 get_db / get_current_user 依赖。
与 test_qs_model_template_api.py 风格一致。
"""
import sys
import os
import copy
import json
import hashlib

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
    },
    "risk_filter": {
        "max_position_ratio": 0.8,
        "daily_max_loss": 0.05,
        "min_trade_size": 0.001,
        "blacklist_hours": ["00:00", "01:00"],
    },
}


def _create_template(client, name="分享测试模板", config=None):
    """创建一个含 qs_model_config 的模板，返回 (id, logic_hash, 响应)。"""
    resp = client.post(
        "/api/strategies/templates",
        json={
            "name": name,
            "strategy_type": "composable",
            "description": "用于导出/导入测试",
            "default_params": {"symbol": "BTC-USDT", "order_qty": 0.01},
            "param_schema": {"order_qty": {"type": "float"}},
            "qs_model_config": config if config is not None else VALID_QS_MODEL_CONFIG,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"], resp.json()["logic_hash"], resp.json()


# ============================================================
# 1. 导出端点：创建模板 → 导出 → 验证 JSON 结构
# ============================================================


def test_export_template_returns_valid_json(test_env):
    """GET /templates/{id}/export：
    - 状态码 200
    - 响应体含 export_version="1.0"、exported_at、template 三层结构
    - template.qs_model_config 含完整四段（meta/params/logic/risk_filter）
    - template.name / strategy_type / default_params 与原模板一致
    - Content-Disposition 含 attachment 与文件名
    """
    client, _, _ = test_env
    template_id, logic_hash, _ = _create_template(client, name="导出测试")

    resp = client.get(f"/api/strategies/templates/{template_id}/export")
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert data["export_version"] == "1.0"
    assert "exported_at" in data
    # exported_at 应为 ISO 格式字符串（以 Z 结尾）
    assert isinstance(data["exported_at"], str)
    assert data["exported_at"].endswith("Z")

    tmpl = data["template"]
    assert tmpl["name"] == "导出测试"
    assert tmpl["strategy_type"] == "composable"
    assert tmpl["description"] == "用于导出/导入测试"
    assert tmpl["default_params"] == {"symbol": "BTC-USDT", "order_qty": 0.01}
    assert tmpl["param_schema"] == {"order_qty": {"type": "float"}}

    # qs_model_config 完整四段
    qs = tmpl["qs_model_config"]
    assert qs is not None
    assert qs["qs_model_version"] == "2.0"
    for section in ("meta", "params", "logic", "risk_filter"):
        assert section in qs, f"导出载荷应包含 qs_model_config.{section}"
    assert qs["meta"]["base_symbol"] == "BTC-USDT"
    assert qs["logic"]["base_strategy"]["kind"] == "grid"
    assert qs["risk_filter"]["max_position_ratio"] == 0.8

    # Content-Disposition 头
    cd = resp.headers.get("content-disposition", "")
    assert "attachment" in cd, f"Content-Disposition 应含 attachment: {cd}"
    assert "filename=" in cd, f"Content-Disposition 应含 filename: {cd}"
    # RFC 5987 编码的中文文件名
    assert "filename*=UTF-8''" in cd, f"应含 RFC 5987 编码文件名: {cd}"


def test_export_nonexistent_template_returns_404(test_env):
    """GET /templates/999999/export 不存在的模板返回 404。"""
    client, _, _ = test_env
    resp = client.get("/api/strategies/templates/999999/export")
    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


def test_export_legacy_dsl_config_template_wraps_to_qs_model(test_env):
    """仅含 dsl_config（无 qs_model_config）的旧模板导出时：
    - qs_model_config 自动包装为 QS-Model 结构
    - logic 段等于原 dsl_config
    - risk_filter 为 None
    """
    client, _, _ = test_env
    dsl_config = {
        "version": "1.0",
        "base_strategy": {"kind": "grid", "params": {"upper_price": 50000}},
        "rules": [],
    }
    resp = client.post(
        "/api/strategies/templates",
        json={
            "name": "旧DSL导出",
            "strategy_type": "composable",
            "default_params": {"symbol": "BTC-USDT"},
            "dsl_config": dsl_config,
        },
    )
    assert resp.status_code == 200
    template_id = resp.json()["id"]

    export_resp = client.get(f"/api/strategies/templates/{template_id}/export")
    assert export_resp.status_code == 200
    qs = export_resp.json()["template"]["qs_model_config"]
    assert qs is not None
    assert qs["qs_model_version"] == "2.0"
    assert qs["logic"] == dsl_config
    assert qs["risk_filter"] is None


# ============================================================
# 2. 导入端点：用导出的 JSON 导入 → 验证新模板
# ============================================================


def test_import_template_from_exported_json(test_env):
    """完整 round-trip：创建模板 → 导出 → 用导出 JSON 导入：
    - 导入返回 200，新模板 id 非 None
    - 新模板名称带 "（导入）" 后缀
    - qs_model_config 完整保留
    - logic_hash 与原模板一致
    - 数据库中存在两个相同 logic_hash 的模板
    """
    client, SessionLocal, _ = test_env
    template_id, original_hash, _ = _create_template(client, name="RoundTrip-原始")

    # 导出
    export_resp = client.get(f"/api/strategies/templates/{template_id}/export")
    assert export_resp.status_code == 200
    exported = export_resp.json()

    # 导入
    import_resp = client.post("/api/strategies/templates/import", json=exported)
    assert import_resp.status_code == 200, import_resp.text
    imported = import_resp.json()

    # 新模板字段
    assert imported["id"] is not None
    assert imported["id"] != template_id, "导入应创建新模板，id 不能与原模板相同"
    assert imported["name"] == "RoundTrip-原始（导入）"
    assert imported["is_custom"] is True
    assert imported["is_builtin"] is False
    assert imported["strategy_type"] == "composable"

    # qs_model_config 完整保留
    assert imported["qs_model_config"] is not None
    assert imported["qs_model_config"]["meta"]["base_symbol"] == "BTC-USDT"
    assert imported["qs_model_config"]["logic"]["base_strategy"]["kind"] == "grid"

    # logic_hash 一致
    assert imported["logic_hash"] == original_hash, (
        f"导入后 logic_hash 应与原模板一致：{imported['logic_hash']} != {original_hash}"
    )

    # 数据库中存在两个相同 logic_hash 的模板
    db = SessionLocal()
    try:
        from models.strategy import StrategyTemplate

        cnt = db.query(StrategyTemplate).filter(
            StrategyTemplate.logic_hash == original_hash
        ).count()
        assert cnt == 2, "导出再导入后应有 2 个相同 logic_hash 的模板"

        new_tmpl = db.query(StrategyTemplate).filter(
            StrategyTemplate.name == "RoundTrip-原始（导入）"
        ).first()
        assert new_tmpl is not None
        assert new_tmpl.qs_model_config is not None
        assert new_tmpl.logic_hash == original_hash
    finally:
        db.close()


def test_import_template_name_collision_appends_suffix(test_env):
    """导入时若 "X（导入）" 已存在，则追加 -2/-3 后缀避免重名。"""
    client, _, _ = test_env
    template_id, _, _ = _create_template(client, name="碰撞测试")

    # 第一次导入：名称为 "碰撞测试（导入）"
    export_resp = client.get(f"/api/strategies/templates/{template_id}/export")
    exported = export_resp.json()
    first_import = client.post("/api/strategies/templates/import", json=exported)
    assert first_import.status_code == 200
    assert first_import.json()["name"] == "碰撞测试（导入）"

    # 第二次导入：名称应为 "碰撞测试（导入）-2"
    second_import = client.post("/api/strategies/templates/import", json=exported)
    assert second_import.status_code == 200, second_import.text
    assert second_import.json()["name"] == "碰撞测试（导入）-2"

    # 第三次导入：名称应为 "碰撞测试（导入）-3"
    third_import = client.post("/api/strategies/templates/import", json=exported)
    assert third_import.status_code == 200
    assert third_import.json()["name"] == "碰撞测试（导入）-3"


# ============================================================
# 3. 导入校验：无效请求体 / 缺少必填字段 / 不兼容版本
# ============================================================


def test_import_missing_export_version(test_env):
    """请求体缺少 export_version 字段返回 400。"""
    client, _, _ = test_env
    resp = client.post("/api/strategies/templates/import", json={"template": {}})
    assert resp.status_code == 400
    assert "export_version" in resp.json()["detail"]


def test_import_unsupported_version(test_env):
    """export_version 不在白名单内返回 400。"""
    client, _, _ = test_env
    resp = client.post(
        "/api/strategies/templates/import",
        json={
            "export_version": "2.0",  # 不支持
            "template": {"name": "x", "qs_model_config": {}},
        },
    )
    assert resp.status_code == 400
    assert "不支持的导出版本" in resp.json()["detail"]


def test_import_missing_template_field(test_env):
    """缺少 template 字段返回 400。"""
    client, _, _ = test_env
    resp = client.post(
        "/api/strategies/templates/import",
        json={"export_version": "1.0"},
    )
    assert resp.status_code == 400
    assert "template" in resp.json()["detail"]


def test_import_missing_qs_model_config(test_env):
    """template.qs_model_config 缺失返回 400。"""
    client, _, _ = test_env
    resp = client.post(
        "/api/strategies/templates/import",
        json={
            "export_version": "1.0",
            "template": {"name": "x", "strategy_type": "composable"},
        },
    )
    assert resp.status_code == 400
    assert "qs_model_config" in resp.json()["detail"]


def test_import_qs_model_missing_required_section(test_env):
    """qs_model_config 缺少四段中的某一段返回 400。"""
    client, _, _ = test_env
    incomplete_config = copy.deepcopy(VALID_QS_MODEL_CONFIG)
    del incomplete_config["logic"]  # 删除 logic 段

    resp = client.post(
        "/api/strategies/templates/import",
        json={
            "export_version": "1.0",
            "template": {
                "name": "缺段测试",
                "strategy_type": "composable",
                "qs_model_config": incomplete_config,
            },
        },
    )
    assert resp.status_code == 400
    assert "缺少必填段" in resp.json()["detail"]
    assert "logic" in resp.json()["detail"]


def test_import_qs_model_invalid_structure(test_env):
    """qs_model_config 四段都在但 meta 字段类型非法（Pydantic 校验失败）返回 400。"""
    client, _, _ = test_env
    bad_config = copy.deepcopy(VALID_QS_MODEL_CONFIG)
    # meta.name 应为 str，改为 int 触发 Pydantic 校验失败
    bad_config["meta"]["name"] = 12345

    resp = client.post(
        "/api/strategies/templates/import",
        json={
            "export_version": "1.0",
            "template": {
                "name": "结构非法",
                "strategy_type": "composable",
                "qs_model_config": bad_config,
            },
        },
    )
    assert resp.status_code == 400
    assert "结构校验失败" in resp.json()["detail"]


def test_import_invalid_dsl_logic_fails_validation(test_env):
    """logic 段引用未知的 base_strategy kind，DSLValidator 校验失败返回 400。"""
    client, _, _ = test_env
    bad_config = copy.deepcopy(VALID_QS_MODEL_CONFIG)
    bad_config["logic"]["base_strategy"]["kind"] = "nonexistent_strategy_kind"

    resp = client.post(
        "/api/strategies/templates/import",
        json={
            "export_version": "1.0",
            "template": {
                "name": "坏DSL",
                "strategy_type": "composable",
                "qs_model_config": bad_config,
            },
        },
    )
    assert resp.status_code == 400
    assert "DSL 校验失败" in resp.json()["detail"]


def test_import_non_dict_body_returns_400(test_env):
    """请求体不是 JSON 对象（如列表）返回 400。"""
    client, _, _ = test_env
    resp = client.post(
        "/api/strategies/templates/import",
        json=[1, 2, 3],  # 列表而非对象
    )
    assert resp.status_code == 400
    assert "JSON 对象" in resp.json()["detail"]


# ============================================================
# 4. logic_hash 一致性：相同配置导出再导入，hash 应一致
# ============================================================


def test_logic_hash_consistent_across_export_import(test_env):
    """相同配置导出再导入，logic_hash 应完全一致：
    - 原模板 logic_hash
    - 导出 JSON 中（虽然导出载荷不含 logic_hash，但 qs_model_config.logic 段相同）
    - 导入后新模板 logic_hash
    三者基于相同 logic 段，hash 必须一致。
    """
    client, SessionLocal, _ = test_env
    template_id, original_hash, _ = _create_template(client, name="Hash一致性-原始")
    assert original_hash is not None

    # 导出
    export_resp = client.get(f"/api/strategies/templates/{template_id}/export")
    assert export_resp.status_code == 200
    exported = export_resp.json()

    # 导出的 logic 段应与原模板相同
    exported_logic = exported["template"]["qs_model_config"]["logic"]
    expected_hash = hashlib.sha256(
        json.dumps(exported_logic, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert expected_hash == original_hash, (
        "基于导出 logic 段重新计算的 hash 应与原模板 logic_hash 一致"
    )

    # 导入
    import_resp = client.post("/api/strategies/templates/import", json=exported)
    assert import_resp.status_code == 200
    imported_hash = import_resp.json()["logic_hash"]

    assert imported_hash == original_hash, (
        f"导入后 logic_hash 应与原模板一致：{imported_hash} != {original_hash}"
    )

    # 直接用 create_template 创建相同 logic 的模板（不经过导出/导入），
    # 验证三种路径产生相同 hash
    direct_resp = client.post(
        "/api/strategies/templates",
        json={
            "name": "Hash一致性-直接创建",
            "strategy_type": "composable",
            "default_params": {"symbol": "BTC-USDT"},
            "qs_model_config": VALID_QS_MODEL_CONFIG,
            "force": True,  # 强制创建（相同 logic_hash）
        },
    )
    assert direct_resp.status_code == 200
    direct_hash = direct_resp.json()["logic_hash"]
    assert direct_hash == original_hash, (
        "直接创建的模板 logic_hash 也应与导出/导入路径一致"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
