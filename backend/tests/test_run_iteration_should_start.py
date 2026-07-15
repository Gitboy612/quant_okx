"""Task 9: run_iteration.py should_start 分支测试。

测试用例：
1. test_research_type_rotation: N=0,1,2,3 分别调用对应生成器（mock 生成器）
2. test_validate_failure_skips: validate 失败时跳过并记录日志
3. test_dry_run_failure_skips: dry-run 夏普<0 时跳过
4. test_successful_creates_and_starts: 全流程通过时创建 StrategyTemplate + StrategyInstance 并启动
5. test_failure_records_to_log: 失败时记录到 execution.log

导入风格参考 test_qsm_generator.py：sys.path 注入 backend 根目录。
"""
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from pathlib import Path

# 注入 backend 根目录到 sys.path
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_DIR)

# 注入 run_iteration.py 所在目录（脚本而非包）
_SCRIPT_DIR = os.path.join(_BACKEND_DIR, "tests", "reports", "strategy_research")
sys.path.insert(0, _SCRIPT_DIR)

import pytest

# 导入真实生成器输出供 mock 返回值使用
from research.qsm_generator import (
    generate_classic_variant,
    generate_dsl_innovation,
    generate_backtest_candidates,
    generate_ab_variants,
)

import run_iteration


# ============================================================
# Mock 工厂
# ============================================================


def _make_valid_qsm():
    """生成一个合法 QSModelConfig dict（用于 mock 返回值）。"""
    return generate_classic_variant("BTC-USDT", 0)


def _make_mock_http_client(validate_valid=True, dry_run_steps=None):
    """构造 mock httpx.AsyncClient。

    Args:
        validate_valid: validate 端点返回是否通过
        dry_run_steps: dry-run 端点返回的 steps（None 时用默认上涨数据）
    """
    client = AsyncMock()

    validate_resp = Mock()
    validate_resp.raise_for_status = Mock()
    validate_resp.json = Mock(return_value={
        "valid": validate_valid,
        "errors": [] if validate_valid else [
            {"layer": "schema", "code": "INVALID", "message": "校验失败"},
        ],
    })

    if dry_run_steps is None:
        # 默认：价格持续上涨（好指标，夏普>0，回撤=0）
        dry_run_steps = [{"price": 100.0 + i * 0.5} for i in range(100)]

    dry_run_resp = Mock()
    dry_run_resp.raise_for_status = Mock()
    dry_run_resp.json = Mock(return_value={
        "steps": dry_run_steps,
        "total_ticks": len(dry_run_steps),
        "triggered_count": 0,
        "state_changes": 0,
        "final_state": "RUNNING",
    })

    async def _post(url, json=None):
        if "validate" in url:
            return validate_resp
        return dry_run_resp

    client.post = _post
    return client


def _make_mock_db_session(account_exists=True):
    """构造 mock DB session。

    - query(Account).first() -> account（或 None）
    - query(StrategyInstance).filter(...).all() -> [] （无运行实例，A/B 回退经典）
    - add/commit/refresh 正常执行
    """
    session = MagicMock()
    account = Mock()
    account.id = 1

    query_mock = MagicMock()
    # query(Account).first() 和 query(StrategyInstance).filter().all()
    query_mock.filter.return_value.all.return_value = []
    query_mock.first.return_value = account if account_exists else None
    session.query.return_value = query_mock

    # add/commit/refresh/rollback/close
    session.add = Mock()
    session.commit = Mock()
    session.refresh = Mock()
    session.rollback = Mock()
    session.close = Mock()

    # 模拟 db.refresh 后 template/instance 有 id
    def _refresh(obj):
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = 999
    session.refresh.side_effect = _refresh

    return session


@pytest.fixture
def redirect_log(tmp_path):
    """重定向 LOG_FILE 到临时目录，避免污染真实日志。"""
    original = run_iteration.LOG_FILE
    log_file = tmp_path / "execution.log"
    run_iteration.LOG_FILE = log_file
    yield log_file
    run_iteration.LOG_FILE = original


# ============================================================
# 1. test_research_type_rotation
# ============================================================


@pytest.mark.asyncio
async def test_research_type_rotation(redirect_log):
    """N=0,1,2,3 分别调用对应生成器（mock 生成器）。"""
    http_client = _make_mock_http_client(validate_valid=True)

    for n in range(4):
        valid_qsm = _make_valid_qsm()
        valid_dsl = generate_dsl_innovation("BTC-USDT", 0)
        valid_candidates = [_make_valid_qsm()]

        with patch.object(run_iteration, "generate_classic_variant", return_value=valid_qsm) as m_classic, \
             patch.object(run_iteration, "generate_dsl_innovation", return_value=valid_dsl) as m_dsl, \
             patch.object(run_iteration, "generate_backtest_candidates", return_value=valid_candidates) as m_backtest, \
             patch.object(run_iteration, "generate_ab_variants", return_value=[valid_qsm]) as m_ab, \
             patch.object(run_iteration, "SessionLocal", return_value=_make_mock_db_session()), \
             patch.object(run_iteration, "strategy_engine") as m_engine:

            m_engine.start_strategy = AsyncMock()

            result = await run_iteration._run_should_start_branch(
                execution_count=n * 12,
                research_type=n,
                running_snapshots=[],
                http_client=http_client,
            )

            # 验证对应生成器被调用
            if n == 0:
                m_classic.assert_called_once()
            elif n == 1:
                m_dsl.assert_called_once()
            elif n == 2:
                m_backtest.assert_called_once()
            elif n == 3:
                m_ab.assert_called_once()

            # 验证成功启动
            assert result["started"] is True, f"N={n} 启动失败: {result}"
            assert result["research_type"] == n


# ============================================================
# 2. test_validate_failure_skips
# ============================================================


@pytest.mark.asyncio
async def test_validate_failure_skips(redirect_log):
    """validate 失败时跳过并记录日志。"""
    http_client = _make_mock_http_client(validate_valid=False)

    with patch.object(run_iteration, "SessionLocal", return_value=_make_mock_db_session()), \
         patch.object(run_iteration, "strategy_engine") as m_engine:
        m_engine.start_strategy = AsyncMock()

        result = await run_iteration._run_should_start_branch(
            execution_count=0,
            research_type=0,
            running_snapshots=[],
            http_client=http_client,
        )

    # 验证跳过
    assert result["started"] is False
    assert result["reason"] == "VALIDATE_FAILED"
    # 验证未启动策略
    m_engine.start_strategy.assert_not_called()
    # 验证日志记录了失败
    log_content = redirect_log.read_text(encoding="utf-8")
    assert "VALIDATE_FAILED" in log_content
    assert "DSL 校验未通过" in log_content


# ============================================================
# 3. test_dry_run_failure_skips
# ============================================================


@pytest.mark.asyncio
async def test_dry_run_failure_skips(redirect_log):
    """dry-run 夏普<0（价格持续下跌）时跳过。"""
    # 构造价格持续下跌的 steps（夏普<0，总收益为负）
    bad_steps = [{"price": 200.0 - i * 1.0} for i in range(100)]
    http_client = _make_mock_http_client(validate_valid=True, dry_run_steps=bad_steps)

    with patch.object(run_iteration, "SessionLocal", return_value=_make_mock_db_session()), \
         patch.object(run_iteration, "strategy_engine") as m_engine:
        m_engine.start_strategy = AsyncMock()

        result = await run_iteration._run_should_start_branch(
            execution_count=0,
            research_type=0,
            running_snapshots=[],
            http_client=http_client,
        )

    # 验证跳过
    assert result["started"] is False
    assert result["reason"] == "METRICS_UNQUALIFIED"
    # 验证未启动策略
    m_engine.start_strategy.assert_not_called()
    # 验证日志记录了指标不达标
    log_content = redirect_log.read_text(encoding="utf-8")
    assert "METRICS_UNQUALIFIED" in log_content
    assert "回测指标不达标" in log_content


# ============================================================
# 4. test_successful_creates_and_starts
# ============================================================


@pytest.mark.asyncio
async def test_successful_creates_and_starts(redirect_log):
    """全流程通过时创建 StrategyTemplate + StrategyInstance 并启动。"""
    http_client = _make_mock_http_client(validate_valid=True)
    mock_session = _make_mock_db_session()

    # 追踪 add 的对象
    added_objects = []
    original_add = mock_session.add

    def _track_add(obj):
        added_objects.append(obj)
        original_add(obj)

    mock_session.add = _track_add

    with patch.object(run_iteration, "SessionLocal", return_value=mock_session), \
         patch.object(run_iteration, "strategy_engine") as m_engine:
        m_engine.start_strategy = AsyncMock()

        result = await run_iteration._run_should_start_branch(
            execution_count=12,
            research_type=0,
            running_snapshots=[],
            http_client=http_client,
        )

    # 验证成功
    assert result["started"] is True
    assert result["reason"] == "OK"
    assert result["symbol"] == "BTC-USDT"

    # 验证创建了 StrategyTemplate 和 StrategyInstance
    from models.strategy import StrategyTemplate, StrategyInstance
    templates = [o for o in added_objects if isinstance(o, StrategyTemplate)]
    instances = [o for o in added_objects if isinstance(o, StrategyInstance)]
    assert len(templates) == 1, "应创建 1 个 StrategyTemplate"
    assert len(instances) == 1, "应创建 1 个 StrategyInstance"

    # 验证 Template 属性
    tmpl = templates[0]
    assert tmpl.strategy_type == "composable"
    assert tmpl.qs_model_config is not None
    assert tmpl.logic_hash is not None

    # 验证 Instance 属性
    inst = instances[0]
    assert inst.symbol == "BTC-USDT"
    assert inst.market_type == "spot"
    assert inst.params["qs_model_config"] is not None
    assert inst.params["investment_amount"] == 100.0
    assert inst.logic_hash is not None

    # 验证调用了 start_strategy
    m_engine.start_strategy.assert_called_once()
    # 验证日志记录了成功
    log_content = redirect_log.read_text(encoding="utf-8")
    assert "策略已创建并启动" in log_content


# ============================================================
# 5. test_failure_records_to_log
# ============================================================


@pytest.mark.asyncio
async def test_failure_records_to_log(redirect_log):
    """失败时记录到 execution.log（格式: [timestamp] [step] [error_code] message）。"""
    # 制造一个生成器异常 → GENERATE_FAILED
    with patch.object(run_iteration, "generate_classic_variant", side_effect=RuntimeError("生成器爆炸")), \
         patch.object(run_iteration, "SessionLocal", return_value=_make_mock_db_session()), \
         patch.object(run_iteration, "strategy_engine") as m_engine:
        m_engine.start_strategy = AsyncMock()

        result = await run_iteration._run_should_start_branch(
            execution_count=0,
            research_type=0,
            running_snapshots=[],
            http_client=None,
        )

    # 验证跳过
    assert result["started"] is False
    assert result["reason"] == "GENERATE_FAILED"

    # 验证日志格式
    log_content = redirect_log.read_text(encoding="utf-8")
    assert "[generate]" in log_content
    assert "[GENERATE_FAILED]" in log_content
    assert "策略生成失败" in log_content
    assert "生成器爆炸" in log_content
    # 验证未启动策略
    m_engine.start_strategy.assert_not_called()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
