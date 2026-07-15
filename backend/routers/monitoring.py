import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from models.strategy_event import StrategyEvent
from middleware.auth import get_current_user

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/reconcile")
async def reconcile_positions(
    account_id: int = Query(..., description="账户 ID"),
    symbol: str = Query(..., description="交易品种，如 ETH-USDT-SWAP"),
    tolerance: float | None = Query(None, description="容差；不传时用默认 0.0001"),
    user: User = Depends(get_current_user),
):
    """虚拟仓位对账：聚合账户下所有交易该 symbol 的活跃策略实例虚拟持仓之和，
    与交易所真实持仓对比，返回差异与 matched 状态（SubTask 4.3）。

    差异超容差时由 PnlAccountingEngine 记录 position_mismatch 事件并触发通知。
    """
    from services.pnl_accounting_engine import pnl_accounting_engine

    result = await pnl_accounting_engine.reconcile_positions(
        account_id=account_id,
        symbol=symbol,
        client=None,
        tolerance=tolerance,
    )
    return result


@router.get("/position_conflicts")
async def get_position_conflicts(
    account_id: int = Query(..., description="账户 ID"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """扫描账户下所有活跃策略的仓位冲突情况（Task 7: 改代数和）。

    核心逻辑与 base_strategy.check_position_conflict 一致：多策略虚拟持仓代数叠加应等于
    真实持仓（"傅里叶叠加"原理），多空对冲（A=+5, B=-5, real=0）不应误报冲突。
    - others_occupied = 其他策略 net_position 的代数和（带符号，多正空负）
    - real_pos = 真实持仓（带符号，多头正空头负）
    - available = real_pos - others_occupied（代数运算）
    - 可用量 usable 按 real_pos 方向取值（三分支）
    - is_conflict = abs(net_position) > usable（策略无法独立平掉自己净持仓时才算冲突）

    对冲组：同 symbol 下既有净多头又有净空头策略时，标注为对冲组 G1/G2/...

    Returns:
        {"account_id", "conflicts": [...], "total": int}
    """
    from models.strategy import StrategyInstance
    from models.pnl import PnlRecord
    from services.pnl_accounting_engine import pnl_accounting_engine

    # 1. 查该账户所有活跃策略
    instances = (
        db.query(StrategyInstance)
        .filter(StrategyInstance.account_id == account_id)
        .filter(StrategyInstance.status.in_(["running", "paused"]))
        .all()
    )

    if not instances:
        return {"account_id": account_id, "conflicts": [], "total": 0}

    # 2. 按 symbol 分组
    symbol_groups: dict[str, list] = {}
    for inst in instances:
        symbol_groups.setdefault(inst.symbol, []).append(inst)

    # 3. 获取 OKX client（用第一个实例延迟创建）
    client = None
    try:
        client = await pnl_accounting_engine._get_client(instances[0].id)
    except Exception:
        client = None

    # 4. 对每个 symbol 查真实持仓（带符号，多头正空头负；与 base_strategy 一致）
    symbol_real_pos: dict[str, float] = {}
    for symbol in symbol_groups:
        real_pos = 0.0
        if client is not None:
            try:
                risk = await client.get_position_risk(symbol)
                if risk is not None:
                    pos_str = risk.get("pos")
                    if pos_str is not None and pos_str != "":
                        try:
                            real_pos = float(pos_str)  # 带符号
                        except (ValueError, TypeError):
                            real_pos = 0.0
            except Exception:
                real_pos = 0.0
        symbol_real_pos[symbol] = real_pos

    # 5. 对每个有持仓的策略计算冲突（代数和算法，与 base_strategy.check_position_conflict 一致）
    conflicts = []
    hedge_group_counter = 0
    for symbol, group in symbol_groups.items():
        real_pos = symbol_real_pos.get(symbol, 0.0)
        # 预读该 symbol 下所有策略的 net_position
        positions: dict[int, float] = {}
        for inst in group:
            latest = (
                db.query(PnlRecord)
                .filter(PnlRecord.strategy_instance_id == inst.id)
                .order_by(PnlRecord.recorded_at.desc())
                .first()
            )
            net = (
                float(latest.net_position or 0)
                if latest and latest.net_position is not None
                else 0.0
            )
            positions[inst.id] = net

        # 对冲组识别：同 symbol 下既有净多头又有净空头策略 → 标注为对冲组 G1/G2/...
        has_long = any(v > 0 for v in positions.values())
        has_short = any(v < 0 for v in positions.values())
        hedge_group_id = None
        if has_long and has_short:
            hedge_group_counter += 1
            hedge_group_id = f"G{hedge_group_counter}"

        for inst in group:
            net_position = positions[inst.id]
            if net_position == 0:
                continue  # 无持仓跳过
            # 其他策略虚拟持仓代数和（带符号，多正空负）
            others_occupied = sum(
                positions[other.id] for other in group if other.id != inst.id
            )
            # 代数运算：available = real_pos - others_occupied
            available = real_pos - others_occupied
            # 可用量 usable 按 real_pos 方向取值（与 base_strategy.check_position_conflict 一致）
            if real_pos > 0:
                usable = max(0.0, available)
            elif real_pos < 0:
                usable = max(0.0, -available)
            else:
                # 纯对冲（real_pos == 0）：双向可用 = abs(available)
                usable = abs(available)
            # 策略无法独立平掉自己净持仓时才算冲突
            is_conflict = abs(net_position) > usable
            conflicts.append({
                "strategy_instance_id": inst.id,
                "symbol": symbol,
                "real_pos": real_pos,
                "net_position": net_position,
                "others_occupied": others_occupied,
                "available": available,
                "usable": usable,
                "is_conflict": is_conflict,
                "hedge_group": hedge_group_id,
            })

    return {"account_id": account_id, "conflicts": conflicts, "total": len(conflicts)}


@router.get("/health")
async def get_health_metrics(
    account_id: int = Query(..., description="账户 ID"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """聚合账户下所有运行中策略的健康指标（Task 12）。

    返回各策略的延迟、资金、保证金、仓位隔离指标，以及超限告警。
    延迟仅 GridStrategy 有 get_latency_stats；其余策略返回 null。
    保证金仅合约策略（含 -SWAP）查询；按 symbol 去重避免重复 API 调用。
    """
    from services.strategy_engine import strategy_engine
    from services.pnl_accounting_engine import pnl_accounting_engine
    from models.strategy import StrategyInstance

    instances = (
        db.query(StrategyInstance)
        .filter(StrategyInstance.account_id == account_id)
        .filter(StrategyInstance.status.in_(["running", "paused"]))
        .all()
    )

    # 按 symbol 去重查询 reconcile（同 symbol 聚合结果相同）
    symbols = {(inst.params or {}).get("symbol", "") for inst in instances}
    symbols.discard("")
    isolation_map: dict[str, dict | None] = {}
    for symbol in symbols:
        try:
            recon = await pnl_accounting_engine.reconcile_positions(
                account_id=account_id, symbol=symbol, client=None,
            )
            isolation_map[symbol] = {"diff": recon["diff"], "matched": recon["matched"]}
        except Exception:
            isolation_map[symbol] = None

    margin_cache: dict[str, float | None] = {}
    strategies_result = []
    alerts = []

    for inst in instances:
        params = inst.params or {}
        symbol = params.get("symbol", "")
        entry = strategy_engine._tasks.get(inst.id)
        strategy = entry[1] if entry else None

        # 延迟：仅 GridStrategy 有 get_latency_stats
        latency = None
        if strategy is not None and hasattr(strategy, "get_latency_stats"):
            try:
                latency = strategy.get_latency_stats()
            except Exception:
                latency = None

        # 资金
        investment_amount = float(params.get("investment_amount", 0))
        lever = float(params.get("lever", 1))
        position_value = 0.0
        if strategy is not None:
            try:
                position_value = float(strategy._get_current_position_value(symbol))
            except Exception:
                position_value = 0.0
        cap = investment_amount * lever
        usage_rate = (position_value / cap) if cap > 0 else 0.0

        # 保证金（合约，按 symbol 缓存避免重复 API 调用）
        margin_ratio = None
        if symbol and "-SWAP" in symbol:
            if symbol in margin_cache:
                margin_ratio = margin_cache[symbol]
            elif strategy is not None and strategy.client is not None:
                try:
                    risk = await strategy.client.get_position_risk(symbol)
                    if risk is not None:
                        margin_ratio = float(risk.get("margin_ratio", 0.0))
                except Exception:
                    margin_ratio = None
                margin_cache[symbol] = margin_ratio

        isolation = isolation_map.get(symbol)

        strategies_result.append({
            "instance_id": inst.id,
            "symbol": symbol,
            "latency": latency,
            "capital": {
                "investment_amount": investment_amount,
                "position_value": position_value,
                "usage_rate": usage_rate,
            },
            "margin_ratio": margin_ratio,
            "isolation": isolation,
        })

        # 告警：聚合超限指标
        if latency and latency.get("p95", 0) > 2.0:
            alerts.append({
                "level": "warning",
                "type": "order_latency",
                "message": f"策略 #{inst.id} {symbol} 补单延迟 P95={latency['p95']:.2f}s 超过 2s",
            })
        if cap > 0 and usage_rate > 0.8:
            alerts.append({
                "level": "warning",
                "type": "capital_usage",
                "message": f"策略 #{inst.id} {symbol} 资金使用率 {usage_rate*100:.1f}% 超过 80%",
            })
        if margin_ratio is not None and margin_ratio > 0.8:
            level = "critical" if margin_ratio > 0.95 else "warning"
            alerts.append({
                "level": level,
                "type": "margin_warning",
                "message": f"策略 #{inst.id} {symbol} 保证金率 {margin_ratio*100:.1f}%{'（临界）' if level == 'critical' else ''}",
            })
        if isolation and not isolation.get("matched"):
            alerts.append({
                "level": "warning",
                "type": "position_conflict",
                "message": f"策略 #{inst.id} {symbol} 仓位差异 {isolation['diff']:.4f} 超容差",
            })

    return {"strategies": strategies_result, "alerts": alerts}


@router.get("/strategy/{strategy_id}/events")
def list_strategy_events(
    strategy_id: int,
    limit: int = Query(100, ge=1, le=1000),
    event_type: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(StrategyEvent).filter(
        StrategyEvent.strategy_instance_id == strategy_id
    )
    if event_type:
        query = query.filter(StrategyEvent.event_type == event_type)

    total = query.count()
    events = query.order_by(StrategyEvent.created_at.desc()).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": e.id,
                "strategy_instance_id": e.strategy_instance_id,
                "event_type": e.event_type,
                "message": e.message,
                "details": e.details,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


@router.delete("/strategy/{strategy_id}/events")
def delete_strategy_events(
    strategy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deleted = db.query(StrategyEvent).filter(
        StrategyEvent.strategy_instance_id == strategy_id
    ).delete(synchronize_session=False)
    db.commit()
    return {"message": f"已删除 {deleted} 条事件", "deleted": deleted}


@router.get("/strategy/{strategy_id}/events/export")
def export_strategy_events(
    strategy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    events = db.query(StrategyEvent).filter(
        StrategyEvent.strategy_instance_id == strategy_id
    ).order_by(StrategyEvent.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "event_type", "message", "details", "created_at"])
    for e in events:
        writer.writerow([
            e.id,
            e.event_type,
            e.message,
            e.details or "",
            e.created_at.isoformat() if e.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=strategy_{strategy_id}_events.csv"},
    )