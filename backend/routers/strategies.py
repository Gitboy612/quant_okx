import hashlib
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from models.strategy import StrategyTemplate, StrategyInstance
from models.log import OperationLog
from schemas.strategy import StrategyInstanceCreate, StrategyInstanceUpdate, StrategyTemplateCreate, StrategyTemplateUpdate
from services.strategy_engine import strategy_engine
from middleware.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


def to_utc_iso(dt: datetime | None) -> str | None:
    """将 datetime 序列化为带 Z 后缀的 UTC ISO 字符串。

    - None 返回 None
    - naive datetime（无 tzinfo，SQLite 常见情况）视为 UTC
    - aware datetime 转换为 UTC
    - 输出 isoformat 并确保以 'Z' 结尾
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _compute_logic_hash(qs_model_config: dict | None, dsl_config: dict | None) -> str | None:
    """计算 logic 段的 SHA-256 哈希。

    优先使用 qs_model_config.logic，回退到 dsl_config（向后兼容）。
    使用 sort_keys=True 规范化 JSON，确保相同内容产生相同哈希。
    """
    logic_source: dict | None = None
    if qs_model_config:
        logic_source = qs_model_config.get("logic", {}) or {}
    elif dsl_config:
        logic_source = dsl_config
    if logic_source is None:
        return None
    canonical_json = json.dumps(logic_source, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _serialize_template(template: StrategyTemplate, duplicate_hint: str | None = None) -> dict:
    """序列化模板为响应 dict。

    若 qs_model_config 为空但 dsl_config 非空，自动包装为 QS-Model 结构（读取兼容）。
    """
    if template.qs_model_config:
        qs_config = template.qs_model_config
    elif template.dsl_config:
        qs_config = {
            "qs_model_version": "2.0",
            "meta": {"name": template.name, "base_symbol": ""},
            "params": {},
            "logic": template.dsl_config,
            "risk_filter": None,
        }
    else:
        qs_config = None
    return {
        "id": template.id,
        "name": template.name,
        "strategy_type": template.strategy_type,
        "description": template.description,
        "default_params": template.default_params,
        "param_schema": template.param_schema,
        "is_builtin": template.is_builtin,
        "is_custom": template.is_custom,
        "dsl_config": template.dsl_config,
        "qs_model_config": qs_config,
        "logic_hash": template.logic_hash,
        "duplicate_hint": duplicate_hint,
    }


@router.get("/templates")
def list_templates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    templates = db.query(StrategyTemplate).all()
    return [_serialize_template(t) for t in templates]


@router.post("/templates")
def create_template(
    body: StrategyTemplateCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    existing = db.query(StrategyTemplate).filter(
        StrategyTemplate.name == body.name,
        StrategyTemplate.is_custom == True,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="同名自定义模板已存在")

    # 计算 logic 段哈希：优先 qs_model_config.logic，回退 dsl_config（向后兼容）
    logic_hash = _compute_logic_hash(body.qs_model_config, body.dsl_config)

    # 重复逻辑去重提示：若已有相同 logic_hash 的模板且未强制创建，返回提示而不落库
    if logic_hash is not None and not body.force:
        dup = db.query(StrategyTemplate).filter(
            StrategyTemplate.logic_hash == logic_hash,
        ).first()
        if dup:
            hint = f"检测到已有相同逻辑的模板『{dup.name}』，是否仍要创建？"
            return {
                "id": None,
                "name": body.name,
                "strategy_type": body.strategy_type,
                "description": body.description,
                "default_params": body.default_params,
                "param_schema": body.param_schema,
                "is_builtin": False,
                "is_custom": True,
                "dsl_config": body.dsl_config,
                "qs_model_config": body.qs_model_config,
                "logic_hash": logic_hash,
                "duplicate_hint": hint,
            }

    template = StrategyTemplate(
        name=body.name,
        strategy_type=body.strategy_type,
        description=body.description,
        default_params=body.default_params,
        param_schema=body.param_schema,
        is_builtin=False,
        is_custom=True,
        dsl_config=body.dsl_config,
        qs_model_config=body.qs_model_config,
        logic_hash=logic_hash,
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    log = OperationLog(
        user_id=user.id,
        action="create_strategy_template",
        target_type="strategy_template",
        target_id=template.id,
        detail={"name": body.name, "type": body.strategy_type},
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    db.commit()

    return _serialize_template(template)


@router.put("/templates/{template_id}")
def update_template(
    template_id: int,
    body: StrategyTemplateUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    template = db.query(StrategyTemplate).filter(StrategyTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="策略模板不存在")

    # Partial update：仅更新请求中提供的字段，未提供字段保持原值
    if body.name is not None:
        template.name = body.name
    if body.description is not None:
        template.description = body.description
    if body.default_params is not None:
        template.default_params = body.default_params
    if body.param_schema is not None:
        template.param_schema = body.param_schema
    if body.dsl_config is not None:
        template.dsl_config = body.dsl_config
    if body.qs_model_config is not None:
        template.qs_model_config = body.qs_model_config

    # logic_hash 重算：若 qs_model_config.logic 段变化，重新计算 SHA-256
    # （参考 create_template 中的 _compute_logic_hash 计算逻辑）
    # 若 qs_model_config 未提供或 logic 未变化，保留原 logic_hash
    if body.qs_model_config is not None:
        new_logic_hash = _compute_logic_hash(template.qs_model_config, template.dsl_config)
        if new_logic_hash != template.logic_hash:
            template.logic_hash = new_logic_hash

    db.commit()
    db.refresh(template)

    log = OperationLog(
        user_id=user.id,
        action="update_strategy_template",
        target_type="strategy_template",
        target_id=template.id,
        detail={"name": template.name},
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    db.commit()

    return _serialize_template(template)


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    template = db.query(StrategyTemplate).filter(StrategyTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="策略模板不存在")
    if template.is_builtin:
        raise HTTPException(status_code=400, detail="内置模板不可删除")

    db.delete(template)
    db.commit()

    log = OperationLog(
        user_id=user.id,
        action="delete_strategy_template",
        target_type="strategy_template",
        target_id=template_id,
        detail={"name": template.name},
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    db.commit()

    return {"message": "自定义模板已删除"}


@router.get("/instances")
def list_instances(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    instances = db.query(StrategyInstance).order_by(StrategyInstance.created_at.desc()).all()
    result = []
    for inst in instances:
        template = db.query(StrategyTemplate).filter(StrategyTemplate.id == inst.template_id).first()
        result.append({
            "id": inst.id,
            "template_id": inst.template_id,
            "template_name": template.name if template else "",
            "strategy_type": template.strategy_type if template else "",
            "account_id": inst.account_id,
            "name": inst.name,
            "symbol": inst.symbol,
            "market_type": inst.market_type,
            "params": inst.params,
            "status": inst.status,
            "logic_hash": inst.logic_hash,
            "started_at": to_utc_iso(inst.started_at),
            "stopped_at": to_utc_iso(inst.stopped_at),
            "created_at": to_utc_iso(inst.created_at),
            "updated_at": to_utc_iso(inst.updated_at),
        })
    return result


@router.post("/instances")
def create_instance(
    body: StrategyInstanceCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    template = db.query(StrategyTemplate).filter(StrategyTemplate.id == body.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="策略模板不存在")

    # QS-Model 币对锁定：模板 meta.base_symbol 非空时，强制 instance symbol 为该值（忽略用户输入）
    qs_meta_base_symbol = ""
    qs_config = getattr(template, "qs_model_config", None)
    if isinstance(qs_config, dict):
        meta = qs_config.get("meta") or {}
        if isinstance(meta, dict):
            qs_meta_base_symbol = (meta.get("base_symbol") or "").strip()
    if qs_meta_base_symbol and qs_meta_base_symbol != body.symbol:
        logger.warning(
            "create_instance: 模板 %s 锁定 base_symbol=%s，忽略用户传入的 symbol=%s",
            template.id, qs_meta_base_symbol, body.symbol,
        )
        body.symbol = qs_meta_base_symbol

    merged_params = {**template.default_params, **body.params, "symbol": body.symbol}
    # 若模板含 qs_model_config，合并到 params（类似 dsl_config 的合并逻辑）
    if getattr(template, "qs_model_config", None) is not None:
        merged_params["qs_model_config"] = template.qs_model_config

    instance = StrategyInstance(
        template_id=body.template_id,
        account_id=body.account_id,
        name=body.name,
        symbol=body.symbol,
        market_type=body.market_type,
        params=merged_params,
        status="stopped",
        logic_hash=template.logic_hash,  # 创建时的逻辑版本快照
    )
    db.add(instance)
    db.commit()
    db.refresh(instance)

    log = OperationLog(
        user_id=user.id,
        action="create_strategy",
        target_type="strategy",
        target_id=instance.id,
        detail={"name": body.name, "type": template.strategy_type, "symbol": body.symbol},
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    db.commit()

    return {"id": instance.id, "message": "策略实例创建成功"}


@router.put("/instances/{instance_id}")
async def update_instance(
    instance_id: int,
    body: StrategyInstanceUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    instance = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
    if not instance:
        raise HTTPException(status_code=404, detail="策略实例不存在")

    # 委托 engine.update_params 处理 params 更新：检测 logic 段变化，
    # 运行中改 logic 抛 400，非运行时允许并重算 logic_hash。
    # 先做 params 校验（可能抛 400），再更新 name，避免 400 时 name 已落库。
    if body.params is not None:
        await strategy_engine.update_params(instance_id, body.params)
        # engine 在独立 session 中已提交 params / logic_hash；刷新本 session 视图
        db.refresh(instance)

    if body.name is not None:
        instance.name = body.name
        db.commit()

    log = OperationLog(
        user_id=user.id,
        action="update_strategy_params",
        target_type="strategy",
        target_id=instance_id,
        detail={"params": body.params if body.params is not None else instance.params},
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    db.commit()

    return {"message": "策略参数已更新"}


@router.delete("/instances/{instance_id}")
def delete_instance(
    instance_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    instance = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
    if not instance:
        raise HTTPException(status_code=404, detail="策略实例不存在")

    if instance.status == "running":
        import asyncio
        asyncio.create_task(strategy_engine.stop_strategy(instance_id))

    db.delete(instance)

    log = OperationLog(
        user_id=user.id,
        action="delete_strategy",
        target_type="strategy",
        target_id=instance_id,
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    db.commit()

    return {"message": "策略实例已删除"}


@router.post("/instances/{instance_id}/start")
async def start_instance(
    instance_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    instance = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
    if not instance:
        raise HTTPException(status_code=404, detail="策略实例不存在")

    if instance.status == "running":
        raise HTTPException(status_code=400, detail="策略已在运行中")

    feasibility = await strategy_engine.check_feasibility(instance_id)
    if not feasibility.get("ok"):
        raise HTTPException(status_code=400, detail=feasibility.get("reason", "可行性检查未通过"))

    await strategy_engine.start_strategy(instance_id)

    log = OperationLog(
        user_id=user.id,
        action="start_strategy",
        target_type="strategy",
        target_id=instance_id,
        detail={"name": instance.name, "feasibility": feasibility},
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    db.commit()

    return {"message": "策略已启动", "feasibility": feasibility}


@router.get("/instances/{instance_id}/feasibility")
async def check_feasibility(
    instance_id: int,
    user: User = Depends(get_current_user),
):
    return await strategy_engine.check_feasibility(instance_id)


@router.get("/api-call-logs")
def list_api_call_logs(
    strategy_instance_id: int | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from models.api_call_log import ApiCallLog
    query = db.query(ApiCallLog)
    if strategy_instance_id is not None:
        query = query.filter(ApiCallLog.strategy_instance_id == strategy_instance_id)
    logs = query.order_by(ApiCallLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": l.id,
            "strategy_instance_id": l.strategy_instance_id,
            "account_name": l.account_name,
            "endpoint": l.endpoint,
            "method": l.method,
            "request_body": l.request_body,
            "response_code": l.response_code,
            "response_body": l.response_body,
            "status": l.status,
            "created_at": to_utc_iso(l.created_at),
        }
        for l in logs
    ]


@router.get("/api-call-logs/files")
def list_api_log_files(
    category: str = Query("all"),
    user: User = Depends(get_current_user),
):
    from services.log_service import list_log_files as get_files
    return get_files(category)


@router.get("/api-call-logs/files/{filename}")
def read_api_log_file(
    filename: str,
    lines: int = Query(200, ge=1, le=2000),
    category: str = Query("all"),
    user: User = Depends(get_current_user),
):
    from services.log_service import read_log_file
    content = read_log_file(filename, category=category, tail_lines=lines)
    if not content:
        raise HTTPException(status_code=404, detail="日志文件不存在")
    return {"filename": filename, "category": category, "lines": lines, "content": content}


@router.post("/instances/{instance_id}/pause")
async def pause_instance(
    instance_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    instance = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
    if not instance:
        raise HTTPException(status_code=404, detail="策略实例不存在")

    await strategy_engine.pause_strategy(instance_id)

    log = OperationLog(
        user_id=user.id,
        action="pause_strategy",
        target_type="strategy",
        target_id=instance_id,
        detail={"name": instance.name},
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    db.commit()

    return {"message": "策略已暂停"}


@router.post("/instances/{instance_id}/resume")
async def resume_instance(
    instance_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    instance = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
    if not instance:
        raise HTTPException(status_code=404, detail="策略实例不存在")

    await strategy_engine.resume_strategy(instance_id)

    log = OperationLog(
        user_id=user.id,
        action="resume_strategy",
        target_type="strategy",
        target_id=instance_id,
        detail={"name": instance.name},
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    db.commit()

    return {"message": "策略已恢复"}


@router.post("/instances/{instance_id}/stop")
async def stop_instance(
    instance_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    instance = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
    if not instance:
        raise HTTPException(status_code=404, detail="策略实例不存在")

    await strategy_engine.stop_strategy(instance_id)

    log = OperationLog(
        user_id=user.id,
        action="stop_strategy",
        target_type="strategy",
        target_id=instance_id,
        detail={"name": instance.name},
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    db.commit()

    return {"message": "策略已停止"}
