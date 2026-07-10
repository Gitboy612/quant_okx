"""StrategyEngine OKXClient 生命周期测试（Task 2.5）。

覆盖：
- check_feasibility 调用后 client 被关闭（不泄漏连接）
- _get_client_for_account 按账户复用 OKXClient（同账户共享 / 不同账户隔离）
- start_strategy 通过 _get_client_for_account 获取共享 client
- StrategyEngine.aclose 清理所有缓存的 client

测试策略：用 ``unittest.mock`` 替换 OKXClient、SessionLocal、OrderManager、
OKXWsClient、decrypt 与策略类，避免真实网络与事件循环副作用。
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.strategy_engine import StrategyEngine
from models.strategy import StrategyTemplate, StrategyInstance
from models.account import Account


# ============================================================
# 辅助构造
# ============================================================


def _make_account(account_id: int, name: str = "acct") -> MagicMock:
    acct = MagicMock(spec=Account)
    acct.id = account_id
    acct.name = name
    acct.api_key_encrypted = f"key-{account_id}"
    acct.secret_key_encrypted = f"secret-{account_id}"
    acct.passphrase_encrypted = f"pass-{account_id}"
    acct.trade_mode = "demo"
    return acct


def _mock_db(mapping: dict) -> MagicMock:
    """构造 mock db，``db.query(Model).filter(...).first()`` 返回 mapping[Model]。"""
    db = MagicMock()

    def query(model):
        q = MagicMock()
        q.filter.return_value.first.return_value = mapping.get(model)
        return q

    db.query.side_effect = query
    return db


@pytest.fixture(autouse=True)
def _isolate_engine_state():
    """隔离 StrategyEngine 类级可变状态（_account_clients / _tasks），避免测试间污染。"""
    saved_clients = dict(StrategyEngine._account_clients)
    saved_tasks = dict(StrategyEngine._tasks)
    yield
    StrategyEngine._account_clients.clear()
    StrategyEngine._account_clients.update(saved_clients)
    StrategyEngine._tasks.clear()
    StrategyEngine._tasks.update(saved_tasks)


# ============================================================
# Task 2.1: check_feasibility 不泄漏连接
# ============================================================


@pytest.mark.asyncio
async def test_check_feasibility_closes_client(monkeypatch):
    """check_feasibility 执行后 client.aclose() 被调用，且不进入账户共享缓存。"""
    engine = StrategyEngine()

    account = _make_account(1)
    instance = MagicMock(spec=StrategyInstance)
    instance.id = 7
    instance.params = {
        "symbol": "BTC-USDT",
        "upper_price": 50000,
        "lower_price": 40000,
        "grid_count": 10,
        "order_qty": 0.01,
    }
    template = MagicMock(spec=StrategyTemplate)
    template.strategy_type = "grid"

    db = _mock_db({StrategyInstance: instance, StrategyTemplate: template, Account: account})
    monkeypatch.setattr("services.strategy_engine.SessionLocal", lambda: db)

    client = MagicMock()
    client.get_ticker = AsyncMock(return_value=[{"last": "45000"}])
    client.get_balance = AsyncMock(
        return_value={"details": [{"ccy": "USDT", "availBal": "10000"}]}
    )
    client.aclose = AsyncMock()
    okx_cls = MagicMock(return_value=client)
    monkeypatch.setattr("services.strategy_engine.OKXClient", okx_cls)

    result = await engine.check_feasibility(7)

    assert result["ok"] is True
    # client 被创建一次
    okx_cls.assert_called_once()
    # 关键：client 被关闭，无泄漏
    client.aclose.assert_awaited()
    # check_feasibility 自建 client 不进入账户共享缓存
    assert engine._account_clients == {}


@pytest.mark.asyncio
async def test_check_feasibility_closes_client_on_exception(monkeypatch):
    """check_feasibility 中途异常时 finally 仍关闭 client。"""
    engine = StrategyEngine()

    account = _make_account(1)
    instance = MagicMock(spec=StrategyInstance)
    instance.id = 7
    instance.params = {"symbol": "BTC-USDT"}
    template = MagicMock(spec=StrategyTemplate)
    template.strategy_type = "arbitrage"

    db = _mock_db({StrategyInstance: instance, StrategyTemplate: template, Account: account})
    monkeypatch.setattr("services.strategy_engine.SessionLocal", lambda: db)

    client = MagicMock()
    client.get_ticker = AsyncMock(side_effect=RuntimeError("boom"))
    client.aclose = AsyncMock()
    monkeypatch.setattr("services.strategy_engine.OKXClient", MagicMock(return_value=client))

    result = await engine.check_feasibility(7)

    # 异常被外层 except 捕获，返回失败
    assert result["ok"] is False
    assert "检查异常" in result["reason"]
    # finally 仍关闭 client
    client.aclose.assert_awaited()


# ============================================================
# Task 2.2: _get_client_for_account 按账户共享
# ============================================================


@pytest.mark.asyncio
async def test_get_client_for_account_shares_per_account(monkeypatch):
    """同账户多次调用复用同一 OKXClient；不同账户隔离；aclose 清理全部缓存。"""
    engine = StrategyEngine()

    created = []

    def fake_okx_ctor(**kwargs):
        c = MagicMock()
        c.aclose = AsyncMock()
        c.ctor_kwargs = kwargs
        created.append(c)
        return c

    monkeypatch.setattr("services.strategy_engine.OKXClient", fake_okx_ctor)

    acct1 = _make_account(1, "acct1")
    acct2 = _make_account(2, "acct2")

    # 同账户两次调用（模拟同账户多个实例启动）→ 同一 client
    c1 = engine._get_client_for_account(acct1, strategy_instance_id=10)
    c2 = engine._get_client_for_account(acct1, strategy_instance_id=20)
    assert c1 is c2
    assert len(created) == 1
    # 首次创建时 strategy_instance_id 被传入
    assert created[0].ctor_kwargs["strategy_instance_id"] == 10

    # 不同账户 → 不同 client
    c3 = engine._get_client_for_account(acct2, strategy_instance_id=30)
    assert c3 is not c1
    assert len(created) == 2

    # 缓存中两个账户
    assert set(engine._account_clients.keys()) == {"1", "2"}

    # 引擎关闭：清理所有 client
    await engine.aclose()
    assert engine._account_clients == {}
    created[0].aclose.assert_awaited()
    created[1].aclose.assert_awaited()


# ============================================================
# Task 2.3: start_strategy 通过 _get_client_for_account 获取共享 client
# ============================================================


@pytest.mark.asyncio
async def test_start_strategy_uses_shared_client(monkeypatch):
    """start_strategy 通过 _get_client_for_account 获取 client 并传入策略。"""
    engine = StrategyEngine()

    instance = MagicMock(spec=StrategyInstance)
    instance.id = 100
    instance.template_id = 1
    instance.account_id = 1
    instance.params = {"symbol": "BTC-USDT"}
    instance.status = "stopped"
    instance.started_at = None
    template = MagicMock(spec=StrategyTemplate)
    template.id = 1
    template.strategy_type = "grid"
    template.dsl_config = None
    account = _make_account(1)

    db = _mock_db({StrategyInstance: instance, StrategyTemplate: template, Account: account})
    monkeypatch.setattr("services.strategy_engine.SessionLocal", lambda: db)

    # 桩 _get_client_for_account，验证 start_strategy 走该方法且 client 被传入策略
    shared_client = MagicMock()
    captured = {}

    def fake_get(acct, strategy_instance_id=None):
        captured["account_id"] = acct.id
        captured["strategy_instance_id"] = strategy_instance_id
        return shared_client

    monkeypatch.setattr(engine, "_get_client_for_account", fake_get)

    # 桩策略类
    mock_strategy = MagicMock()
    mock_strategy.start = AsyncMock()
    mock_strategy.execute = AsyncMock()
    mock_strategy.ws_client = None
    mock_strategy_cls = MagicMock(return_value=mock_strategy)
    monkeypatch.setitem(StrategyEngine._strategy_map, "grid", mock_strategy_cls)

    # 桩 start_strategy 内部其余依赖
    monkeypatch.setattr("services.order_manager.OrderManager", MagicMock())
    monkeypatch.setattr("services.okx_ws_client.OKXWsClient", MagicMock())
    monkeypatch.setattr("services.encryption_service.decrypt", lambda x: "decrypted")

    try:
        await engine.start_strategy(100)

        # 走了 _get_client_for_account，且参数正确
        assert captured["strategy_instance_id"] == 100
        assert captured["account_id"] == 1

        # 共享 client 被传入策略构造
        assert mock_strategy_cls.call_args.kwargs["client"] is shared_client

        # 实例被标记为 running 并注册到 _tasks
        assert instance.status == "running"
        assert 100 in engine._tasks
    finally:
        # 清理后台任务
        entry = engine._tasks.pop(100, None)
        if entry:
            task = entry[0]
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


@pytest.mark.asyncio
async def test_start_strategy_same_account_shares_client(monkeypatch):
    """同账户两个实例启动复用同一个 OKXClient（端到端共享验证）。"""
    engine = StrategyEngine()

    # 桩 OKXClient 构造，记录创建次数
    created = []

    def fake_okx_ctor(**kwargs):
        c = MagicMock()
        c.aclose = AsyncMock()
        c.ctor_kwargs = kwargs
        created.append(c)
        return c

    monkeypatch.setattr("services.strategy_engine.OKXClient", fake_okx_ctor)

    # 两个实例属于同一账户
    inst1 = MagicMock(spec=StrategyInstance)
    inst1.id = 101
    inst1.template_id = 1
    inst1.account_id = 1
    inst1.params = {"symbol": "BTC-USDT"}
    inst1.status = "stopped"
    inst1.started_at = None
    inst2 = MagicMock(spec=StrategyInstance)
    inst2.id = 102
    inst2.template_id = 1
    inst2.account_id = 1
    inst2.params = {"symbol": "BTC-USDT"}
    inst2.status = "stopped"
    inst2.started_at = None
    template = MagicMock(spec=StrategyTemplate)
    template.id = 1
    template.strategy_type = "grid"
    template.dsl_config = None
    account = _make_account(1)

    # 用一个可切换的 db mock：根据调用顺序返回 inst1 / inst2
    state = {"idx": 0}

    def query_db():
        db = MagicMock()
        instances = [inst1, inst2]

        def query(model):
            q = MagicMock()
            if model is StrategyInstance:
                idx = state["idx"]
                q.filter.return_value.first.return_value = (
                    instances[idx] if idx < len(instances) else None
                )
            elif model is StrategyTemplate:
                q.filter.return_value.first.return_value = template
            elif model is Account:
                q.filter.return_value.first.return_value = account
            return q

        db.query.side_effect = query
        return db

    monkeypatch.setattr("services.strategy_engine.SessionLocal", query_db)

    # 桩策略类
    def make_mock_strategy():
        s = MagicMock()
        s.start = AsyncMock()
        s.execute = AsyncMock()
        s.ws_client = None
        return s

    mock_strategy_cls = MagicMock(side_effect=lambda **kw: make_mock_strategy())
    monkeypatch.setitem(StrategyEngine._strategy_map, "grid", mock_strategy_cls)
    monkeypatch.setattr("services.order_manager.OrderManager", MagicMock())
    monkeypatch.setattr("services.okx_ws_client.OKXWsClient", MagicMock())
    monkeypatch.setattr("services.encryption_service.decrypt", lambda x: "decrypted")

    try:
        await engine.start_strategy(101)
        state["idx"] = 1
        await engine.start_strategy(102)

        # 同账户两个实例 → 仅创建一个 OKXClient
        assert len(created) == 1
        assert 101 in engine._tasks
        assert 102 in engine._tasks
    finally:
        for iid in [101, 102]:
            entry = engine._tasks.pop(iid, None)
            if entry:
                task = entry[0]
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
