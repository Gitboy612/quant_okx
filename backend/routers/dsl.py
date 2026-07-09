"""可拼接策略 DSL REST API 路由。

参考 spec.md「REST API（新增）」章节：
- GET  /api/dsl/blocks    列出所有可用积木（indicators/conditions/actions/events/base_strategies）
- POST /api/dsl/validate  静态校验 DSL 配置，返回错误列表
- POST /api/dsl/dry-run   历史回放模拟，返回事件时间轴

说明：DSL 校验器与注册表均为纯同步逻辑，且无数据库/鉴权依赖；
此处用 ``async def`` 保持与项目其他路由风格一致。
"""
from fastapi import APIRouter, HTTPException

from dsl.registry import (
    indicator_registry,
    condition_registry,
    action_registry,
    event_registry,
    base_strategy_registry,
)
from dsl.validator import DSLValidator
from dsl.dry_run import DryRunSimulator

# 显式导入积木库子模块以触发 @indicator / @condition / @action / @event /
# @base_strategy 装饰器注册（与 validator.py 中的导入保持一致，重复导入无副作用）。
import dsl.blocks.indicators  # noqa: F401
import dsl.blocks.conditions  # noqa: F401
import dsl.blocks.events  # noqa: F401
import dsl.blocks.actions  # noqa: F401
import dsl.blocks.bases  # noqa: F401

router = APIRouter(prefix="/api/dsl", tags=["dsl"])


def _serialize_blocks(items: list[dict]) -> list[dict]:
    """将注册表 list() 输出转换为可 JSON 序列化的形式。

    registry.list() 返回的 ``output_type`` 字段是 Python 类型对象
    （如 ``float`` / ``int`` / ``dict`` / ``bool``），FastAPI 默认的
    jsonable_encoder 无法序列化类型对象，故在此统一转为类型名字符串
    （``"float"`` / ``"int"`` / ``"dict"`` / ``"bool"``）供前端使用。
    """
    result = []
    for item in items:
        item = dict(item)
        ot = item.get("output_type")
        if isinstance(ot, type):
            item["output_type"] = ot.__name__
        result.append(item)
    return result


@router.get("/blocks")
async def list_blocks():
    """列出所有可用积木，按类别分组，含 category/description/param_schema 等元数据。

    返回格式：
    {
        "indicators": [{kind, category, description, param_schema, output_type, priority}, ...],
        "conditions": [...],
        "actions": [...],
        "events": [...],
        "base_strategies": [...]
    }
    """
    return {
        "indicators": _serialize_blocks(indicator_registry.list()),
        "conditions": _serialize_blocks(condition_registry.list()),
        "actions": _serialize_blocks(action_registry.list()),
        "events": _serialize_blocks(event_registry.list()),
        "base_strategies": _serialize_blocks(base_strategy_registry.list()),
    }


@router.post("/validate")
async def validate_dsl(config: dict):
    """校验 DSL 配置，返回校验结果。

    请求体：DSL 配置 JSON（StrategyDSL 结构）
    响应：
    - 校验通过：{"valid": true, "errors": []}
    - 校验失败：{"valid": false, "errors": [{layer, code, message, path}, ...]}
    """
    result = DSLValidator().validate(config)
    return {
        "valid": result.valid,
        "errors": [
            {"layer": e.layer, "code": e.code, "message": e.message, "path": e.path}
            for e in result.errors
        ],
    }


@router.post("/dry-run")
async def dry_run(request: dict):
    """历史回放模拟。

    请求体：
    {
        "config": {DSL 配置},
        "symbol": "BTC-USDT",
        "bar": "1H",
        "limit": 100
    }

    响应：
    {
        "steps": [{timestamp, price, state, indicator_values, triggered,
                   rule_name, actions, transition}, ...],
        "total_ticks": N,
        "triggered_count": M,
        "state_changes": K,
        "final_state": "RUNNING"
    }

    无 OKX 客户端时使用模拟 K 线数据（前端预览用）；实际历史回放需
    在后端直接调用 ``DryRunSimulator(okx_client)``。
    """
    config = request.get("config", {})
    symbol = request.get("symbol", "BTC-USDT")
    bar = request.get("bar", "1H")
    limit = request.get("limit", 100)

    simulator = DryRunSimulator()
    try:
        result = await simulator.run(config, symbol, bar, limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "steps": [
            {
                "timestamp": s.timestamp,
                "price": s.price,
                "state": s.state,
                "indicator_values": s.indicator_values,
                "triggered": s.triggered,
                "rule_name": s.rule_name,
                "actions": s.actions,
                "transition": s.transition,
            }
            for s in result.steps
        ],
        "total_ticks": result.total_ticks,
        "triggered_count": result.triggered_count,
        "state_changes": result.state_changes,
        "final_state": result.final_state,
    }
