"""策略数据库状态与内存执行任务同步测试。"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.strategy import StrategyInstance
from services.strategy_engine import StrategyEngine
from strategies.base_strategy import BaseStrategy


def _mock_db_with_instance(instance):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = instance
    return db


@pytest.fixture(autouse=True)
def isolate_engine_tasks():
    saved_tasks = dict(StrategyEngine._tasks)
    saved_heartbeat = dict(StrategyEngine._last_heartbeat_ts)
    StrategyEngine._tasks.clear()
    StrategyEngine._last_heartbeat_ts.clear()
    yield
    StrategyEngine._tasks.clear()
    StrategyEngine._tasks.update(saved_tasks)
    StrategyEngine._last_heartbeat_ts.clear()
    StrategyEngine._last_heartbeat_ts.update(saved_heartbeat)


@pytest.mark.asyncio
async def test_pause_without_live_task_does_not_write_false_paused_status(monkeypatch):
    instance = MagicMock(spec=StrategyInstance)
    instance.status = "running"
    db = _mock_db_with_instance(instance)
    monkeypatch.setattr("services.strategy_engine.SessionLocal", lambda: db)

    with pytest.raises(HTTPException) as exc_info:
        await StrategyEngine().pause_strategy(1)

    assert exc_info.value.status_code == 409
    assert instance.status == "running"
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_resume_finished_task_reconciles_to_stopped_instead_of_false_running(monkeypatch):
    instance = MagicMock(spec=StrategyInstance)
    instance.status = "paused"
    db = _mock_db_with_instance(instance)
    monkeypatch.setattr("services.strategy_engine.SessionLocal", lambda: db)

    finished_task = asyncio.create_task(asyncio.sleep(0))
    await finished_task
    StrategyEngine._tasks[1] = (finished_task, MagicMock())

    with pytest.raises(HTTPException) as exc_info:
        await StrategyEngine().resume_strategy(1)

    assert exc_info.value.status_code == 409
    assert instance.status == "stopped"
    db.commit.assert_called_once()
    assert 1 not in StrategyEngine._tasks


@pytest.mark.asyncio
async def test_pause_waits_for_order_cleanup_before_writing_paused(monkeypatch):
    instance = MagicMock(spec=StrategyInstance)
    instance.status = "running"
    db = _mock_db_with_instance(instance)
    monkeypatch.setattr("services.strategy_engine.SessionLocal", lambda: db)
    monkeypatch.setattr(
        "services.strategy_engine.pnl_accounting_engine.incremental_update",
        AsyncMock(),
    )

    cleanup_finished = False

    async def cleanup():
        nonlocal cleanup_finished
        await asyncio.sleep(0)
        cleanup_finished = True

    strategy = MagicMock()
    strategy.client = MagicMock()
    strategy.pause.side_effect = lambda: asyncio.create_task(cleanup())
    live_task = asyncio.create_task(asyncio.sleep(60))
    StrategyEngine._tasks[1] = (live_task, strategy)

    try:
        await StrategyEngine().pause_strategy(1)
    finally:
        live_task.cancel()

    assert cleanup_finished is True
    assert instance.status == "paused"
    db.commit.assert_called_once()


def test_completed_task_callback_reconciles_running_status_to_stopped(monkeypatch):
    instance = MagicMock(spec=StrategyInstance)
    instance.status = "running"
    instance.stopped_at = None
    db = _mock_db_with_instance(instance)
    monkeypatch.setattr("services.strategy_engine.SessionLocal", lambda: db)

    task = MagicMock()
    task.cancelled.return_value = False
    task.exception.return_value = None
    StrategyEngine._tasks[1] = (task, MagicMock())

    StrategyEngine()._on_strategy_task_done(1, task)

    assert instance.status == "stopped"
    assert instance.stopped_at is not None
    db.commit.assert_called_once()
    assert 1 not in StrategyEngine._tasks


def test_failed_task_callback_reconciles_running_status_to_error(monkeypatch):
    instance = MagicMock(spec=StrategyInstance)
    instance.status = "running"
    db = _mock_db_with_instance(instance)
    monkeypatch.setattr("services.strategy_engine.SessionLocal", lambda: db)

    task = MagicMock()
    task.cancelled.return_value = False
    task.exception.return_value = RuntimeError("boom")
    StrategyEngine._tasks[1] = (task, MagicMock())

    StrategyEngine()._on_strategy_task_done(1, task)

    assert instance.status == "error"
    db.commit.assert_called_once()
    assert 1 not in StrategyEngine._tasks


@pytest.mark.asyncio
async def test_leverage_setup_failure_aborts_start_instead_of_false_running():
    strategy = MagicMock(spec=BaseStrategy)
    strategy._running = True
    strategy._paused = False
    strategy._ws_client = None
    strategy._apply_leverage_settings = AsyncMock(return_value=False)
    strategy.update_status = MagicMock()

    with pytest.raises(RuntimeError, match="杠杆设置失败"):
        await BaseStrategy.start(strategy)

    assert strategy._running is False
    strategy.update_status.assert_called_once_with("error")
