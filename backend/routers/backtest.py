"""回测路由。

- POST /api/backtest/run     执行回测
- GET  /api/backtest/history  获取历史回测记录（内存存储，重启丢失）
- POST /api/backtest/export   导出回测参数为策略实例配置
"""
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from middleware.auth import get_current_user
from models.user import User
from services.backtest_engine import BacktestConfig, BacktestResult, backtest_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


# ============================================================
# Schemas
# ============================================================

class BacktestRequest(BaseModel):
    """回测请求体。"""
    symbol: str
    strategy_type: str
    params: dict
    start_time: str
    end_time: str
    interval: str = "1H"
    initial_capital: float = 10000.0
    slippage: float = 0.001
    fee_rate: float = 0.001


class ExportRequest(BaseModel):
    """导出为策略实例配置请求体。"""
    symbol: str
    strategy_type: str
    params: dict
    name: str | None = None
    notes: str | None = None


# ============================================================
# 内存历史存储（重启后丢失；如需持久化可扩展到 DB）
# ============================================================

_history_store: list[dict] = []
_HISTORY_MAX = 50


def _serialize_result(result: BacktestResult) -> dict:
    return {
        "config": result.config,
        "trades": result.trades,
        "equity_curve": result.equity_curve,
        "metrics": result.metrics,
        "kline_count": result.kline_count,
        "error": result.error,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


# ============================================================
# 路由
# ============================================================

@router.post("/run")
def run_backtest(
    body: BacktestRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """执行回测。

    同步执行（基于历史数据离线计算），可能耗时数秒。
    """
    config = BacktestConfig(
        symbol=body.symbol,
        strategy_type=body.strategy_type,
        params=body.params,
        start_time=body.start_time,
        end_time=body.end_time,
        interval=body.interval,
        initial_capital=body.initial_capital,
        slippage=body.slippage,
        fee_rate=body.fee_rate,
    )

    try:
        result = backtest_engine.run_backtest(config)
    except Exception as e:
        logger.exception("backtest run failed")
        raise HTTPException(status_code=500, detail=f"回测执行失败: {e}")

    payload = _serialize_result(result)

    # 写入内存历史
    _history_store.insert(0, payload)
    if len(_history_store) > _HISTORY_MAX:
        _history_store[_HISTORY_MAX:] = []

    return payload


@router.get("/history")
def get_history(
    limit: int = 20,
    user: User = Depends(get_current_user),
) -> dict:
    """获取历史回测记录（最近优先，最多 50 条）。"""
    n = max(1, min(limit, _HISTORY_MAX))
    return {"data": _history_store[:n], "total": len(_history_store)}


@router.post("/export")
def export_to_instance(
    body: ExportRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """导出回测参数为策略实例配置。

    返回可直接用于 POST /api/strategies/instances 的 payload（不含 account_id，
    由前端选择账户后再补充）。
    """
    name = body.name or f"Backtest-{body.symbol}-{body.strategy_type}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    instance_payload: dict[str, Any] = {
        "name": name,
        "symbol": body.symbol,
        "market_type": "swap" if body.symbol.endswith("-SWAP") else "spot",
        "params": body.params,
        "strategy_type": body.strategy_type,
        "notes": body.notes,
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    return {
        "instance_payload": instance_payload,
        "message": "参数已导出，请选择账户后创建策略实例",
    }
