"""E2E 测试基础工具（模拟盘端到端测试）。

提供以下 fixture：
- demo_account_id: 从数据库读取 demo 账户（trade_mode='demo'），无则 None
- test_client: 带认证的 FastAPI TestClient（覆盖 get_current_user）
- cleanup_strategy: 测试后清理创建的策略实例 / 自定义模板 / 关联订单与 PnL 记录
- mock_okx: 自动 patch OKXClient / OKXWsClient / decrypt / instrument_cache，避免真实网络

设计要点：
1. 不实际连接 OKX API —— 所有 OKX 调用通过 mock 返回预设响应
2. 使用真实 SQLite 数据库验证全链路（API → strategy_engine → DB）
3. 无 demo 账户时测试自动跳过（pytestmark.skipif）
4. 每个测试结束后清理 strategy_engine 单例状态（_tasks / _account_clients）
"""
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# ---- sys.path 注入（参考 conftest.py 风格）----
_E2E_DIR = os.path.dirname(os.path.abspath(__file__))
_TESTS_DIR = os.path.dirname(_E2E_DIR)
_BACKEND_ROOT = os.path.dirname(_TESTS_DIR)
for _p in (_BACKEND_ROOT, _TESTS_DIR, _E2E_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database import SessionLocal, init_db
from models.account import Account
from models.user import User
from models.strategy import StrategyTemplate, StrategyInstance
from models.order import Order
from models.pnl import PnlRecord
from models.strategy_event import StrategyEvent
from services.auth_service import hash_password, create_access_token


# ============================================================
# Session-scoped：数据库初始化 + demo 账户检测
# ============================================================


def _get_demo_account_id():
    """从数据库读取第一个 demo 账户 ID，无则返回 None。"""
    db = SessionLocal()
    try:
        acct = db.query(Account).filter(Account.trade_mode == "demo").first()
        return acct.id if acct else None
    except Exception:
        return None
    finally:
        db.close()


DEMO_ACCOUNT_ID = _get_demo_account_id()

SKIP_REASON = "数据库中无 trade_mode='demo' 的模拟盘账户，跳过 E2E 测试"


def _ensure_test_user():
    """确保数据库中有 admin 用户，返回 user_id。"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "admin").first()
        if not user:
            user = User(
                username="admin",
                password_hash=hash_password("admin123"),
                created_at=datetime.now(timezone.utc),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user.id
    finally:
        db.close()


@pytest.fixture(scope="session", autouse=True)
def _init_db_session():
    """Session 级：初始化数据库表 + 种子模板，仅执行一次。"""
    init_db()
    from services.strategy_engine import strategy_engine
    strategy_engine.seed_templates()
    yield


# ============================================================
# Mock OKX API（function-scoped, autouse）
# ============================================================


def _create_mock_okx_client():
    """构造 mock OKXClient，返回预设的行情 / 下单 / 撤单响应。"""
    client = AsyncMock()

    # 行情：BTC-USDT 当前价 45000
    client.get_ticker = AsyncMock(return_value=[{"last": "45000", "instId": "BTC-USDT"}])

    # 账户余额
    client.get_balance = AsyncMock(return_value={
        "totalEq": "10000",
        "details": [{"ccy": "USDT", "availBal": "10000"}],
    })

    # 批量下单：根据 payload 数量返回对应数量的 ordId
    def _batch_side_effect(payloads):
        return {
            "code": "0",
            "data": [
                {"sCode": "0", "ordId": f"mock_{uuid.uuid4().hex[:12]}"}
                for _ in payloads
            ],
        }

    client.batch_place_orders = AsyncMock(side_effect=_batch_side_effect)

    # 单笔下单
    client.place_order = AsyncMock(return_value={
        "code": "0",
        "data": [{"sCode": "0", "ordId": f"mock_{uuid.uuid4().hex[:12]}"}],
    })

    # 撤单
    client.cancel_order = AsyncMock(return_value={"code": "0"})

    # 查询订单状态：默认返回 live
    client.get_order = AsyncMock(return_value=[{"state": "live"}])

    # K 线数据（趋势策略用）：30 根稳定 K 线，不触发均线交叉
    base_ts = 1_700_000_000_000
    bar_ms = 5 * 60 * 1000  # 5m
    client.get_candles = AsyncMock(return_value=[
        [str(base_ts + i * bar_ms), "100", "106", "99", "105", "1", "1", "1", "1"]
        for i in range(30)
    ])

    client.aclose = AsyncMock()
    return client


def _create_mock_ws_client():
    """构造 mock OKXWsClient。"""
    ws = AsyncMock()
    ws.is_connected = True
    ws.connect = AsyncMock()
    ws.subscribe_orders = AsyncMock()
    ws.disconnect = AsyncMock()
    ws.on_order_update = MagicMock()
    return ws


@pytest.fixture(autouse=True)
def mock_okx():
    """自动 patch 所有 OKX 相关组件，测试期间不连接真实 API。

    patch 列表：
    - services.strategy_engine.OKXClient → mock client
    - services.okx_ws_client.OKXWsClient → mock ws client
    - services.encryption_service.decrypt → 返回 "decrypted"
    - services.instrument_cache.InstrumentCache.get_instrument → 返回默认元数据
    - services.pnl_accounting_engine.OKXClient → mock client
    """
    mock_client = _create_mock_okx_client()
    mock_ws = _create_mock_ws_client()

    patches = [
        patch("services.strategy_engine.OKXClient", return_value=mock_client),
        patch("services.okx_ws_client.OKXWsClient", return_value=mock_ws),
        patch("services.encryption_service.decrypt", return_value="decrypted"),
        patch(
            "services.instrument_cache.InstrumentCache.get_instrument",
            new=AsyncMock(return_value={"ctVal": 1.0, "ctType": None, "settleCcy": None}),
        ),
        patch("services.pnl_accounting_engine.OKXClient", return_value=mock_client),
    ]
    for p in patches:
        p.start()

    yield mock_client

    for p in patches:
        p.stop()


# ============================================================
# StrategyEngine 状态隔离（function-scoped, autouse）
# ============================================================


@pytest.fixture(autouse=True)
def _isolate_engine_state():
    """每个测试前后清理 StrategyEngine 单例的可变状态。"""
    from services.strategy_engine import StrategyEngine

    saved_clients = dict(StrategyEngine._account_clients)
    saved_tasks = dict(StrategyEngine._tasks)
    saved_heartbeat = dict(StrategyEngine._last_heartbeat_ts)
    saved_sampling = StrategyEngine._pnl_sampling_task

    yield

    # 测试后：停止所有运行中的策略任务
    for iid, (task, strategy) in list(StrategyEngine._tasks.items()):
        try:
            task.cancel()
        except Exception:
            pass
    StrategyEngine._tasks.clear()
    StrategyEngine._account_clients.clear()
    StrategyEngine._last_heartbeat_ts.clear()
    if StrategyEngine._pnl_sampling_task and not StrategyEngine._pnl_sampling_task.done():
        StrategyEngine._pnl_sampling_task.cancel()
    StrategyEngine._pnl_sampling_task = None

    # 清理 pnl_accounting_engine 单例的 client 缓存
    from services.pnl_accounting_engine import PnlAccountingEngine
    PnlAccountingEngine._client_map.clear()

    # 恢复原始状态（防止跨测试污染）
    StrategyEngine._account_clients = saved_clients
    StrategyEngine._tasks = saved_tasks
    StrategyEngine._last_heartbeat_ts = saved_heartbeat
    StrategyEngine._pnl_sampling_task = saved_sampling


# ============================================================
# 构建测试 App（仅注册 E2E 所需路由）
# ============================================================


def _build_test_app():
    """构建包含 E2E 所需路由的 FastAPI app。"""
    from routers.strategies import router as strategies_router
    from routers.pnl import router as pnl_router
    from routers.orders import router as orders_router
    from routers.ws import router as ws_router
    from routers.auth import router as auth_router
    from routers.dsl import router as dsl_router
    from middleware.auth import get_current_user

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(strategies_router)
    app.include_router(pnl_router)
    app.include_router(orders_router)
    app.include_router(ws_router)
    app.include_router(dsl_router)

    # 覆盖认证：直接返回 mock user，无需登录
    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.username = "admin"
    app.dependency_overrides[get_current_user] = lambda: mock_user
    return app


_test_app = _build_test_app()


# ============================================================
# test_client fixture
# ============================================================


@pytest.fixture
def test_client():
    """提供带认证（dependency_overrides）的 FastAPI TestClient。"""
    with TestClient(_test_app) as client:
        yield client


# ============================================================
# demo_account_id fixture
# ============================================================


@pytest.fixture
def demo_account_id():
    """提供 demo 账户 ID，无 demo 账户时返回 None。"""
    return DEMO_ACCOUNT_ID


# ============================================================
# cleanup_strategy fixture
# ============================================================


@pytest.fixture
def cleanup_strategy():
    """测试后清理创建的策略实例、自定义模板及关联数据。

    用法：在测试中 created["instances"].append(instance_id)
    """
    created = {"instances": [], "templates": []}
    yield created

    db = SessionLocal()
    try:
        # 先停止可能还在运行的策略
        from services.strategy_engine import StrategyEngine
        for iid in created["instances"]:
            entry = StrategyEngine._tasks.get(iid)
            if entry:
                task, strategy = entry
                try:
                    task.cancel()
                except Exception:
                    pass
                del StrategyEngine._tasks[iid]

        for iid in created["instances"]:
            db.query(Order).filter(Order.strategy_instance_id == iid).delete()
            db.query(PnlRecord).filter(PnlRecord.strategy_instance_id == iid).delete()
            db.query(StrategyEvent).filter(StrategyEvent.strategy_instance_id == iid).delete()
            inst = db.query(StrategyInstance).filter(StrategyInstance.id == iid).first()
            if inst:
                db.delete(inst)
        for tid in created["templates"]:
            tpl = db.query(StrategyTemplate).filter(StrategyTemplate.id == tid).first()
            if tpl and not tpl.is_builtin:
                db.delete(tpl)
        db.commit()
    finally:
        db.close()


# ============================================================
# 辅助函数
# ============================================================


def get_builtin_template_id(strategy_type: str) -> int:
    """获取内置模板 ID（grid / trend / arbitrage）。"""
    db = SessionLocal()
    try:
        tpl = db.query(StrategyTemplate).filter(
            StrategyTemplate.strategy_type == strategy_type,
            StrategyTemplate.is_builtin == True,
        ).first()
        return tpl.id if tpl else None
    finally:
        db.close()


def wait_for(condition, timeout=30, interval=0.5, desc="condition"):
    """轮询等待条件满足，超时抛 TimeoutError。

    Args:
        condition: 无参可调用对象，返回 True 表示条件满足
        timeout: 最大等待秒数
        interval: 轮询间隔秒数
        desc: 条件描述（用于错误消息）
    """
    start = time.time()
    while time.time() - start < timeout:
        if condition():
            return True
        time.sleep(interval)
    raise TimeoutError(f"等待 {desc} 超时（{timeout}s）")


def count_live_orders(instance_id: int) -> int:
    """查询 DB 中某策略实例的 live 订单数。"""
    db = SessionLocal()
    try:
        return db.query(Order).filter(
            Order.strategy_instance_id == instance_id,
            Order.status == "live",
        ).count()
    finally:
        db.close()


def get_instance_status(instance_id: int) -> str:
    """查询 DB 中策略实例状态。"""
    db = SessionLocal()
    try:
        inst = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
        return inst.status if inst else None
    finally:
        db.close()


def get_latest_pnl(instance_id: int):
    """查询某策略实例最新的 PnlRecord。"""
    db = SessionLocal()
    try:
        return db.query(PnlRecord).filter(
            PnlRecord.strategy_instance_id == instance_id,
        ).order_by(PnlRecord.recorded_at.desc()).first()
    finally:
        db.close()
