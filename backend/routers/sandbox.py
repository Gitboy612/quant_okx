"""策略沙箱路由。

- POST /api/sandbox/start        启动沙箱运行
- GET  /api/sandbox/{id}/status  查询沙箱状态
- POST /api/sandbox/{id}/stop    停止沙箱
- GET  /api/sandbox/{id}/result  获取沙箱结果
- GET  /api/sandbox/list         列出所有沙箱实例

沙箱模式：使用真实实时行情运行策略，但不触发真实下单。
所有下单操作被 mock 拦截，返回虚拟订单 ID 并记录到内存。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from middleware.auth import get_current_user
from models.user import User
from services.sandbox_service import sandbox_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


# ============================================================
# Schemas
# ============================================================


class SandboxStartRequest(BaseModel):
    """启动沙箱请求体。"""

    qs_model_config: dict = Field(
        ...,
        description="QS-Model 四段式配置（meta/params/logic/risk_filter）",
    )
    symbol: str = Field(..., description="交易对，如 BTC-USDT")
    duration_seconds: int = Field(
        default=300, ge=10, le=86400, description="沙箱运行时长（秒），默认 300s"
    )
    tick_interval: float = Field(
        default=5.0, ge=1.0, le=3600, description="tick 间隔（秒），默认 5s"
    )
    account_id: int | None = Field(
        default=None, description="可选账户 ID，用于读取真实行情；不传则用第一个可用账户"
    )


class SandboxStatusResponse(BaseModel):
    """沙箱状态响应。"""

    sandbox_id: str
    symbol: str
    status: str
    started_at: str
    ended_at: str
    duration_seconds: float
    order_count: int
    pnl_point_count: int
    error: str


# ============================================================
# 路由
# ============================================================


@router.post("/start")
async def start_sandbox(
    body: SandboxStartRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """启动沙箱运行。

    使用真实实时行情运行策略，但所有下单操作被 mock 拦截，
    返回虚拟订单 ID 并记录到内存。沙箱到期后自动停止。

    需要至少一个有效的 OKX 账户用于读取行情数据。
    """
    try:
        sandbox_id = await sandbox_service.run_sandbox(
            qs_model_config=body.qs_model_config,
            symbol=body.symbol,
            duration_seconds=body.duration_seconds,
            tick_interval=body.tick_interval,
            account_id=body.account_id,
        )
    except Exception as e:
        logger.exception("sandbox start failed")
        raise HTTPException(status_code=500, detail=f"沙箱启动失败: {e}")

    status = sandbox_service.get_status(sandbox_id)
    return {
        "sandbox_id": sandbox_id,
        "status": status,
        "message": "沙箱已启动，使用实时行情运行策略（不触发真实下单）",
    }


@router.get("/{sandbox_id}/status")
def get_sandbox_status(
    sandbox_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """查询沙箱运行状态。"""
    status = sandbox_service.get_status(sandbox_id)
    if status is None:
        raise HTTPException(status_code=404, detail="沙箱实例不存在")
    return status


@router.post("/{sandbox_id}/stop")
async def stop_sandbox(
    sandbox_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """停止沙箱运行。"""
    status = sandbox_service.get_status(sandbox_id)
    if status is None:
        raise HTTPException(status_code=404, detail="沙箱实例不存在")
    result = await sandbox_service.stop_sandbox(sandbox_id)
    return {
        "sandbox_id": sandbox_id,
        "status": result,
        "message": "沙箱已停止",
    }


@router.get("/{sandbox_id}/result")
def get_sandbox_result(
    sandbox_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """获取沙箱完整结果。

    返回虚拟订单列表、PnL 曲线、策略事件等完整数据。
    沙箱运行中也可查询（返回当前快照）。
    """
    result = sandbox_service.get_result(sandbox_id)
    if result is None:
        raise HTTPException(status_code=404, detail="沙箱实例不存在")
    return result


@router.get("/list")
def list_sandboxes(
    user: User = Depends(get_current_user),
) -> dict:
    """列出所有沙箱实例状态。"""
    return {"data": sandbox_service.list_sandboxes()}
