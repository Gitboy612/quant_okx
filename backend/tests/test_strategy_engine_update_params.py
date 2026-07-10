"""StrategyEngine.update_params logic 变化检测测试（Task 7.4）。

覆盖三种场景：
1. 仅改 params（不触发重编译）→ 允许更新，logic_hash 不变
2. 改 logic（运行中拒绝 400）→ 抛 HTTPException(400)
3. 改 logic（已停止允许）→ 更新 params 并重算 logic_hash

测试策略：用 unittest.mock 替换 SessionLocal 返回 mock db，
构造带 qs_model_config 的 instance，验证 update_params 行为。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, AsyncMock

import pytest
from fastapi import HTTPException

from services.strategy_engine import StrategyEngine, _compute_logic_hash_from_params
from models.strategy import StrategyInstance


# ============================================================
# 辅助构造
# ============================================================


def _logic_v1() -> dict:
    """logic 段版本 1。"""
    return {
        "version": "1.0",
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "event",
                    "event": {"kind": "on_interval", "args": {"seconds": 60}},
                },
                "then": [{"kind": "log_event", "args": {"message": "v1"}}],
            }
        ],
    }


def _logic_v2() -> dict:
    """logic 段版本 2（与 v1 不同，触发 hash 变化）。"""
    return {
        "version": "1.0",
        "rules": [
            {
                "name": "r1",
                "when": {
                    "mode": "event",
                    "event": {"kind": "on_interval", "args": {"seconds": 120}},
                },
                "then": [{"kind": "log_event", "args": {"message": "v2"}}],
            }
        ],
    }


def _qs_model(logic: dict) -> dict:
    """构造完整的 qs_model_config。"""
    return {
        "qs_model_version": "2.0",
        "meta": {"name": "test", "base_symbol": "BTC-USDT"},
        "params": {},
        "logic": logic,
        "risk_filter": None,
    }


def _make_instance(
    params: dict,
    status: str = "stopped",
    logic_hash: str | None = None,
) -> MagicMock:
    """构造 mock StrategyInstance。"""
    inst = MagicMock(spec=StrategyInstance)
    inst.id = 1
    inst.params = params
    inst.status = status
    inst.logic_hash = logic_hash
    inst.updated_at = None
    return inst


def _mock_db_with_instance(instance) -> MagicMock:
    """构造 mock db，db.query(StrategyInstance).filter().first() 返回 instance。"""
    db = MagicMock()

    def query(model):
        q = MagicMock()
        if model is StrategyInstance:
            q.filter.return_value.first.return_value = instance
        else:
            q.filter.return_value.first.return_value = None
        return q

    db.query.side_effect = query
    return db


@pytest.fixture(autouse=True)
def _isolate_engine_state():
    """隔离 StrategyEngine 类级可变状态（_tasks），避免测试间污染。"""
    saved_tasks = dict(StrategyEngine._tasks)
    yield
    StrategyEngine._tasks.clear()
    StrategyEngine._tasks.update(saved_tasks)


# ============================================================
# 场景 1：仅改 params（不触发重编译）
# ============================================================


@pytest.mark.asyncio
async def test_update_params_only_params_change_allowed(monkeypatch):
    """仅改 params（logic 段不变）→ 允许更新，logic_hash 不变（Task 7.4 场景 1）。

    运行中实例改非 logic 字段（如 order_qty）应被允许，且同步更新内存策略 params。
    """
    engine = StrategyEngine()

    old_qs = _qs_model(_logic_v1())
    new_qs = _qs_model(_logic_v1())  # logic 相同
    old_params = {"qs_model_config": old_qs, "order_qty": 0.01, "symbol": "BTC-USDT"}
    new_params = {"qs_model_config": new_qs, "order_qty": 0.02, "symbol": "BTC-USDT"}

    original_hash = _compute_logic_hash_from_params(old_params)
    instance = _make_instance(old_params, status="running", logic_hash=original_hash)
    db = _mock_db_with_instance(instance)
    monkeypatch.setattr("services.strategy_engine.SessionLocal", lambda: db)

    # 模拟运行中策略对象
    mock_strategy = MagicMock()
    engine._tasks[1] = (MagicMock(), mock_strategy)

    await engine.update_params(1, new_params)

    # params 已更新
    assert instance.params is new_params
    # logic_hash 未变（logic 段未变化）
    assert instance.logic_hash == original_hash
    # db.commit 被调用
    db.commit.assert_called()
    # 运行中实例内存策略 params 已同步
    assert mock_strategy.params is new_params


@pytest.mark.asyncio
async def test_update_params_no_qs_model_allows_any_change(monkeypatch):
    """无 qs_model_config 的实例（传统硬编码策略）改 params 不触发拒绝。"""
    engine = StrategyEngine()

    old_params = {"upper_price": 50000, "lower_price": 40000, "symbol": "BTC-USDT"}
    new_params = {"upper_price": 52000, "lower_price": 40000, "symbol": "BTC-USDT"}

    instance = _make_instance(old_params, status="running", logic_hash=None)
    db = _mock_db_with_instance(instance)
    monkeypatch.setattr("services.strategy_engine.SessionLocal", lambda: db)

    await engine.update_params(1, new_params)

    assert instance.params is new_params
    assert instance.logic_hash is None  # 无 logic，hash 保持 None


# ============================================================
# 场景 2：改 logic（运行中拒绝 400）
# ============================================================


@pytest.mark.asyncio
async def test_update_params_logic_change_running_rejected(monkeypatch):
    """改 logic 段且实例 running → 拒绝并抛 HTTPException(400)（Task 7.4 场景 2）。"""
    engine = StrategyEngine()

    old_qs = _qs_model(_logic_v1())
    new_qs = _qs_model(_logic_v2())  # logic 变化
    old_params = {"qs_model_config": old_qs, "symbol": "BTC-USDT"}
    new_params = {"qs_model_config": new_qs, "symbol": "BTC-USDT"}

    old_hash = _compute_logic_hash_from_params(old_params)
    instance = _make_instance(old_params, status="running", logic_hash=old_hash)
    db = _mock_db_with_instance(instance)
    monkeypatch.setattr("services.strategy_engine.SessionLocal", lambda: db)

    with pytest.raises(HTTPException) as exc_info:
        await engine.update_params(1, new_params)

    assert exc_info.value.status_code == 400
    assert "运行中不能修改 logic 结构" in exc_info.value.detail
    # params 未被修改（拒绝时不应写入）
    assert instance.params is old_params


@pytest.mark.asyncio
async def test_update_params_logic_change_running_no_db_commit(monkeypatch):
    """改 logic 运行中拒绝时 db.commit 不被调用（不落库）。"""
    engine = StrategyEngine()

    old_qs = _qs_model(_logic_v1())
    new_qs = _qs_model(_logic_v2())
    old_params = {"qs_model_config": old_qs}
    new_params = {"qs_model_config": new_qs}

    instance = _make_instance(old_params, status="running")
    db = _mock_db_with_instance(instance)
    monkeypatch.setattr("services.strategy_engine.SessionLocal", lambda: db)

    with pytest.raises(HTTPException):
        await engine.update_params(1, new_params)

    db.commit.assert_not_called()


# ============================================================
# 场景 3：改 logic（已停止允许）
# ============================================================


@pytest.mark.asyncio
async def test_update_params_logic_change_stopped_allowed(monkeypatch):
    """改 logic 段且实例 stopped → 允许更新并重算 logic_hash（Task 7.4 场景 3）。"""
    engine = StrategyEngine()

    old_qs = _qs_model(_logic_v1())
    new_qs = _qs_model(_logic_v2())  # logic 变化
    old_params = {"qs_model_config": old_qs, "symbol": "BTC-USDT"}
    new_params = {"qs_model_config": new_qs, "symbol": "BTC-USDT"}

    old_hash = _compute_logic_hash_from_params(old_params)
    new_hash = _compute_logic_hash_from_params(new_params)
    assert old_hash != new_hash  # 确认测试数据有效：logic 确实变了

    instance = _make_instance(old_params, status="stopped", logic_hash=old_hash)
    db = _mock_db_with_instance(instance)
    monkeypatch.setattr("services.strategy_engine.SessionLocal", lambda: db)

    await engine.update_params(1, new_params)

    # params 已更新
    assert instance.params is new_params
    # logic_hash 已重算为新值
    assert instance.logic_hash == new_hash
    # db.commit 被调用
    db.commit.assert_called()


@pytest.mark.asyncio
async def test_update_params_logic_change_paused_allowed(monkeypatch):
    """改 logic 段且实例 paused → 允许更新并重算 logic_hash（非 running 均允许）。"""
    engine = StrategyEngine()

    old_qs = _qs_model(_logic_v1())
    new_qs = _qs_model(_logic_v2())
    old_params = {"qs_model_config": old_qs}
    new_params = {"qs_model_config": new_qs}

    old_hash = _compute_logic_hash_from_params(old_params)
    new_hash = _compute_logic_hash_from_params(new_params)

    instance = _make_instance(old_params, status="paused", logic_hash=old_hash)
    db = _mock_db_with_instance(instance)
    monkeypatch.setattr("services.strategy_engine.SessionLocal", lambda: db)

    await engine.update_params(1, new_params)

    assert instance.params is new_params
    assert instance.logic_hash == new_hash


# ============================================================
# 辅助函数 _compute_logic_hash_from_params 单元测试
# ============================================================


def test_compute_logic_hash_stable_across_key_order():
    """logic 段 dict 键顺序不同时 hash 相同（sort_keys=True）。"""
    logic_a = {"version": "1.0", "rules": []}
    logic_b = {"rules": [], "version": "1.0"}  # 键顺序不同

    qs_a = {"qs_model_config": {"logic": logic_a}}
    qs_b = {"qs_model_config": {"logic": logic_b}}

    assert _compute_logic_hash_from_params(qs_a) == _compute_logic_hash_from_params(qs_b)


def test_compute_logic_hash_differs_for_different_logic():
    """不同 logic 段产生不同 hash。"""
    h1 = _compute_logic_hash_from_params({"qs_model_config": {"logic": _logic_v1()}})
    h2 = _compute_logic_hash_from_params({"qs_model_config": {"logic": _logic_v2()}})
    assert h1 != h2


def test_compute_logic_hash_fallback_to_dsl_config():
    """无 qs_model_config 时回退到 dsl_config。"""
    dsl = {"version": "1.0", "rules": []}
    h = _compute_logic_hash_from_params({"dsl_config": dsl})
    assert h is not None
    assert len(h) == 64  # SHA-256 hex


def test_compute_logic_hash_none_when_no_logic():
    """无 logic 来源时返回 None。"""
    assert _compute_logic_hash_from_params({"symbol": "BTC-USDT"}) is None
    assert _compute_logic_hash_from_params(None) is None
    assert _compute_logic_hash_from_params({}) is None
