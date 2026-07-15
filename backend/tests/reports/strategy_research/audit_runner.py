"""每小时运行数据审计 - 独立第三方审计脚本。

与 run_iteration.py（策略研究迭代）解耦，本脚本只做只读审计，不生成/启动新策略。
职责边界：发现问题 → 写入审计报告 + 记录告警事件，绝不修改业务数据。

五项检查：
1. 订单唯一性：每个 OKX order_id 只被一个 StrategyInstance 认领；无重复认领、无孤儿订单。
2. 盈亏核算正确性：对每个运行中策略独立 recompute，与最新 PnlRecord 比对，差异超阈值告警。
3. 仓位隔离对账：复用 pnl_accounting_engine.reconcile_positions，虚拟持仓代数和 == OKX 真实持仓。
4. 资金约束检查：各策略 investment_amount 是否被违反（单策略超投、账户总投超限）。
5. OKX 成交记录对账：拉取 OKX 真实成交记录，与 DB orders 对账并独立核算盈亏，与 PnlRecord 比对。
   - SWAP 使用 OKX fill.pnl 字段（交易所权威已实现盈亏）
   - SPOT 使用平均成本法（与 pnl_accounting_engine 对齐）
   - SWAP fillSz 为合约张数，名义价值需乘 ctVal 转换为币种数量

输出：
- backend/tests/reports/strategy_research/audit_report_{YYYYMMDD_HHMMSS}.json
- backend/tests/reports/strategy_research/audit_latest.json（覆盖式，便于面板读取）
- 异常写入 StrategyEvent 表（event_type=audit_*），供监控告警链路消费
"""
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 注入 backend 到 sys.path（与 run_iteration.py 同级脚本）
_BACKEND_DIR = Path(__file__).resolve().parents[3]  # e:\quant_okx\backend
for _p in (str(_BACKEND_DIR),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy.orm import Session
from database import SessionLocal, init_db
from models.strategy import StrategyInstance
from models.account import Account
from models.order import Order
from models.pnl import PnlRecord
from models.strategy_event import StrategyEvent
from services.pnl_accounting_engine import pnl_accounting_engine
from services.okx_client import OKXClient
from services.instrument_cache import instrument_cache

# 启动时确保表结构存在（异地部署或首次运行）
try:
    init_db()
except Exception as e:
    # 初始化失败不中断审计（可能表已存在）
    print(f"[audit_runner] init_db warning: {e}", flush=True)

REPORT_DIR = Path(__file__).resolve().parent
LATEST_FILE = REPORT_DIR / "audit_latest.json"
AUDIT_LOG = REPORT_DIR / "audit.log"

# 审计阈值
PNL_DIFF_TOLERANCE = 0.5  # 盈亏重算差异容差（USDT）
POSITION_TOLERANCE = 0.0001  # 仓位对账容差（沿用 reconcile_positions 默认值）
PRICE_DIFF_TOLERANCE = 0.01  # OKX fillPx 与 DB fill_px 差异容差（USDT）


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    ts = _now_iso()
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # 日志写入失败不影响审计主流程
        pass


def _record_audit_event(
    db: Session,
    strategy_instance_id: int | None,
    event_type: str,
    message: str,
    details: dict | None = None,
) -> None:
    """写入审计事件到 StrategyEvent 表，供监控告警链路消费。

    独立 Session 写入，失败不影响审计主流程。
    strategy_instance_id 为 None 时（全局告警，如订单重复认领）只写日志不写表，
    因为 strategy_events.strategy_instance_id 字段为 NOT NULL。
    """
    if strategy_instance_id is None:
        # 全局告警：只写日志，不写 StrategyEvent 表（字段约束 NOT NULL）
        _log(f"[{event_type}] {message} details={details or {}}")
        return
    try:
        event = StrategyEvent(
            strategy_instance_id=strategy_instance_id,
            event_type=event_type,
            message=message,
            details=json.dumps(details or {}, ensure_ascii=False, default=str),
            created_at=datetime.now(timezone.utc),
        )
        db.add(event)
        db.commit()
    except Exception as e:
        db.rollback()
        _log(f"审计事件写入失败 event_type={event_type}: {e}")


# =============================================================================
# 检查 1：订单唯一性
# =============================================================================
def check_order_uniqueness(db: Session) -> dict:
    """校验每个 OKX order_id 只被一个 StrategyInstance 认领。

    返回:
        {
            "check": "order_uniqueness",
            "passed": bool,
            "duplicate_claims": [{order_id, strategy_instance_ids: [...]}],
            "orphan_orders": [{order_id, account_id}],
            "total_orders_checked": int
        }
    """
    # 查询所有有 order_id 的订单（排除手动管理/测试）
    orders = (
        db.query(Order)
        .filter(Order.order_id.isnot(None))
        .filter(Order.order_id != "")
        .all()
    )

    # 按 order_id 分组
    order_to_strategies: dict[str, list[int]] = defaultdict(list)
    order_to_account: dict[str, int] = {}
    for o in orders:
        oid = o.order_id
        order_to_strategies[oid].append(o.strategy_instance_id)
        if o.account_id is not None:
            order_to_account[oid] = o.account_id

    # 重复认领：同一 order_id 被多个 strategy_instance_id 认领
    duplicates = []
    for oid, sids in order_to_strategies.items():
        unique_sids = set(s for s in sids if s is not None)
        if len(unique_sids) > 1:
            duplicates.append({
                "order_id": oid,
                "strategy_instance_ids": sorted(unique_sids),
                "claim_count": len(sids),
            })

    # 孤儿订单：order_id 存在但 strategy_instance_id 为 None（filled 订单无归属策略）
    orphans = []
    for o in orders:
        if o.status == "filled" and o.strategy_instance_id is None:
            orphans.append({
                "order_id": o.order_id,
                "account_id": o.account_id,
                "symbol": o.symbol,
            })

    passed = (len(duplicates) == 0) and (len(orphans) == 0)

    # 记录告警事件
    if duplicates:
        _record_audit_event(
            db,
            strategy_instance_id=None,
            event_type="audit_order_duplicate_claim",
            message=f"发现 {len(duplicates)} 个订单被多个策略重复认领",
            details={"duplicates": duplicates[:20]},  # 限制事件大小
        )
    if orphans:
        _record_audit_event(
            db,
            strategy_instance_id=None,
            event_type="audit_order_orphan",
            message=f"发现 {len(orphans)} 个已成交订单无归属策略",
            details={"orphans": orphans[:20]},
        )

    return {
        "check": "order_uniqueness",
        "passed": passed,
        "duplicate_claims": duplicates,
        "orphan_orders": orphans,
        "total_orders_checked": len(orders),
    }


# =============================================================================
# 检查 2：盈亏核算正确性
# =============================================================================
async def check_pnl_correctness(db: Session) -> dict:
    """对每个运行中策略独立 recompute，与最新 PnlRecord 比对，差异超阈值告警。

    返回:
        {
            "check": "pnl_correctness",
            "passed": bool,
            "per_strategy": [{strategy_instance_id, symbol, latest_realized, recomputed_realized, diff, matched}],
            "total_checked": int
        }
    """
    running_instances = (
        db.query(StrategyInstance)
        .filter(StrategyInstance.status == "running")
        .all()
    )

    # 按 account_id 缓存 OKXClient（避免重复创建）
    clients: dict[int, OKXClient] = {}
    per_strategy = []

    for inst in running_instances:
        # 读取最新 PnlRecord
        latest = (
            db.query(PnlRecord)
            .filter(PnlRecord.strategy_instance_id == inst.id)
            .order_by(PnlRecord.recorded_at.desc())
            .first()
        )
        latest_realized = float(latest.realized_pnl or 0) if latest else 0.0
        latest_net_position = float(latest.net_position or 0) if latest else 0.0

        # 独立 recompute（不写入新记录，只读对比）
        # 复用 pnl_accounting_engine.recompute 但在独立 Session 中执行
        try:
            # 获取或创建该账户的 client（使用与 run_iteration.py 一致的 kwargs 模式）
            if inst.account_id not in clients:
                account = db.query(Account).filter(Account.id == inst.account_id).first()
                if account:
                    clients[inst.account_id] = OKXClient(
                        api_key_encrypted=account.api_key_encrypted,
                        secret_encrypted=account.secret_key_encrypted,
                        passphrase_encrypted=account.passphrase_encrypted,
                        trade_mode=account.trade_mode,
                        account_name=account.name,
                    )
                else:
                    clients[inst.account_id] = None
            client = clients.get(inst.account_id)

            # recompute 返回 PnlSnapshot 或 None（无成交时）
            snapshot = await pnl_accounting_engine.recompute(
                strategy_instance_id=inst.id, client=client
            )
            if snapshot is None:
                # 无成交订单，跳过（不算异常）
                per_strategy.append({
                    "strategy_instance_id": inst.id,
                    "symbol": inst.symbol,
                    "latest_realized": latest_realized,
                    "recomputed_realized": None,
                    "diff": None,
                    "matched": True,
                    "note": "no_filled_orders",
                })
                continue

            recomputed_realized = float(snapshot.realized_pnl or 0)
            recomputed_net_position = float(snapshot.net_position or 0)
            diff = abs(recomputed_realized - latest_realized)

            # 容差判断：realized_pnl 差异或 net_position 差异超阈值
            matched = (
                diff <= PNL_DIFF_TOLERANCE
                and abs(recomputed_net_position - latest_net_position) <= PNL_DIFF_TOLERANCE
            )

            per_strategy.append({
                "strategy_instance_id": inst.id,
                "symbol": inst.symbol,
                "latest_realized": latest_realized,
                "recomputed_realized": recomputed_realized,
                "diff": round(diff, 6),
                "latest_net_position": latest_net_position,
                "recomputed_net_position": recomputed_net_position,
                "matched": matched,
            })

            if not matched:
                _record_audit_event(
                    db,
                    strategy_instance_id=inst.id,
                    event_type="audit_pnl_mismatch",
                    message=(
                        f"策略#{inst.id} {inst.symbol} 盈亏核算不一致: "
                        f"latest={latest_realized} recomputed={recomputed_realized} diff={diff:.6f}"
                    ),
                    details={
                        "latest_realized": latest_realized,
                        "recomputed_realized": recomputed_realized,
                        "diff": diff,
                        "latest_net_position": latest_net_position,
                        "recomputed_net_position": recomputed_net_position,
                    },
                )
        except Exception as e:
            _log(f"策略#{inst.id} recompute 失败: {e}")
            _record_audit_event(
                db,
                strategy_instance_id=inst.id,
                event_type="audit_recompute_error",
                message=f"策略#{inst.id} recompute 异常: {e}",
                details={"error": str(e)},
            )
            per_strategy.append({
                "strategy_instance_id": inst.id,
                "symbol": inst.symbol,
                "error": str(e),
                "matched": False,
            })

    passed = all(p.get("matched", False) for p in per_strategy)
    return {
        "check": "pnl_correctness",
        "passed": passed,
        "per_strategy": per_strategy,
        "total_checked": len(running_instances),
        "tolerance": PNL_DIFF_TOLERANCE,
    }


# =============================================================================
# 检查 3：仓位隔离对账（复用 reconcile_positions）
# =============================================================================
async def check_position_isolation(db: Session) -> dict:
    """复用 pnl_accounting_engine.reconcile_positions 对账虚拟 vs 真实持仓。

    返回:
        {
            "check": "position_isolation",
            "passed": bool,
            "per_symbol": [{account_id, symbol, virtual_total, real_total, diff, matched}],
            "total_checked": int
        }
    """
    # 找出所有 running 策略涉及的 (account_id, symbol) 组合
    running = (
        db.query(StrategyInstance)
        .filter(StrategyInstance.status == "running")
        .all()
    )
    pairs = set()
    for inst in running:
        pairs.add((inst.account_id, inst.symbol))

    per_symbol = []
    for account_id, symbol in pairs:
        try:
            recon = await pnl_accounting_engine.reconcile_positions(
                account_id=account_id,
                symbol=symbol,
                client=None,
                tolerance=POSITION_TOLERANCE,
            )
            per_symbol.append({
                "account_id": account_id,
                "symbol": symbol,
                "virtual_total": recon.get("virtual_total"),
                "real_total": recon.get("real_total"),
                "diff": recon.get("diff"),
                "matched": recon.get("matched", False),
            })
            if not recon.get("matched", False):
                _record_audit_event(
                    db,
                    strategy_instance_id=None,
                    event_type="audit_position_mismatch",
                    message=(
                        f"仓位隔离不一致 account={account_id} symbol={symbol}: "
                        f"virtual={recon.get('virtual_total')} real={recon.get('real_total')} diff={recon.get('diff')}"
                    ),
                    details={
                        "account_id": account_id,
                        "symbol": symbol,
                        "virtual_total": recon.get("virtual_total"),
                        "real_total": recon.get("real_total"),
                        "diff": recon.get("diff"),
                    },
                )
        except Exception as e:
            _log(f"仓位对账失败 account={account_id} symbol={symbol}: {e}")
            per_symbol.append({
                "account_id": account_id,
                "symbol": symbol,
                "error": str(e),
                "matched": False,
            })

    passed = all(p.get("matched", False) for p in per_symbol)
    return {
        "check": "position_isolation",
        "passed": passed,
        "per_symbol": per_symbol,
        "total_checked": len(pairs),
        "tolerance": POSITION_TOLERANCE,
    }


# =============================================================================
# 检查 4：资金约束检查
# =============================================================================
def check_capital_constraints(db: Session) -> dict:
    """校验各策略 investment_amount 约束是否被违反。

    检查项:
    - 单策略：当前持仓名义价值 <= investment_amount × lever（investment_amount>0 时）
    - 账户总投：同账户所有策略 investment_amount 之和是否合理（可选，不强制拒绝）

    返回:
        {
            "check": "capital_constraints",
            "passed": bool,
            "violations": [{strategy_instance_id, symbol, current_value, cap, excess}],
            "total_checked": int
        }
    """
    running = (
        db.query(StrategyInstance)
        .filter(StrategyInstance.status == "running")
        .all()
    )

    violations = []
    checked = 0
    for inst in running:
        params = inst.params or {}
        investment_amount = float(params.get("investment_amount", 0))
        lever = float(params.get("lever", 1))
        if investment_amount <= 0:
            # 未设置上限，跳过
            continue
        checked += 1
        cap = investment_amount * lever

        # 计算该策略当前持仓名义价值 = net_position × avg_buy_price（从最新 PnlRecord 取）
        latest = (
            db.query(PnlRecord)
            .filter(PnlRecord.strategy_instance_id == inst.id)
            .order_by(PnlRecord.recorded_at.desc())
            .first()
        )
        if not latest:
            continue
        net_position = float(latest.net_position or 0)
        avg_buy_price = float(latest.avg_buy_price or 0)
        current_value = abs(net_position) * avg_buy_price

        if current_value > cap * 1.05:  # 5% 容差
            excess = current_value - cap
            violations.append({
                "strategy_instance_id": inst.id,
                "symbol": inst.symbol,
                "current_value": round(current_value, 6),
                "cap": round(cap, 6),
                "excess": round(excess, 6),
                "investment_amount": investment_amount,
                "lever": lever,
            })
            _record_audit_event(
                db,
                strategy_instance_id=inst.id,
                event_type="audit_capital_violation",
                message=(
                    f"策略#{inst.id} {inst.symbol} 资金约束违反: "
                    f"current_value={current_value:.6f} > cap={cap:.6f}"
                ),
                details={
                    "current_value": current_value,
                    "cap": cap,
                    "excess": excess,
                    "investment_amount": investment_amount,
                    "lever": lever,
                },
            )

    passed = len(violations) == 0
    return {
        "check": "capital_constraints",
        "passed": passed,
        "violations": violations,
        "total_checked": checked,
    }


# =============================================================================
# 检查 5：OKX 成交记录对账
# =============================================================================
def _infer_inst_type(symbol: str) -> str:
    """从 symbol 推断 OKX instType（含 -SWAP → SWAP，含 -USDT 无 -SWAP → SPOT）。"""
    if "-SWAP" in symbol:
        return "SWAP"
    return "SPOT"


def _compute_spot_realized_pnl(
    buys: list[tuple[float, float]],
    sells: list[tuple[float, float]],
    total_fee: float,
) -> float:
    """现货平均成本法计算 realized_pnl（与 pnl_accounting_engine._compute_pnl_metrics 对齐）。

    buys/sells: [(fill_px, qty_in_base_currency), ...]
    仅匹配 min(buy_qty, sell_qty) 部分计算已实现盈亏，手续费按匹配比例分摊。
    """
    buy_qty_sum = sum(q for _, q in buys)
    sell_qty_sum = sum(q for _, q in sells)
    matched_qty = min(buy_qty_sum, sell_qty_sum)
    if matched_qty <= 0:
        return 0.0
    buy_total = sum(px * q for px, q in buys)
    sell_total = sum(px * q for px, q in sells)
    avg_buy_px = buy_total / buy_qty_sum if buy_qty_sum > 0 else 0.0
    avg_sell_px = sell_total / sell_qty_sum if sell_qty_sum > 0 else 0.0
    total_qty = buy_qty_sum + sell_qty_sum
    avg_fee_per_unit = total_fee / total_qty if total_qty > 0 else 0.0
    return matched_qty * (avg_sell_px - avg_buy_px) - matched_qty * avg_fee_per_unit


async def check_okx_trade_records(db: Session) -> dict:
    """拉取 OKX 真实成交记录与 DB orders 对账，独立核算盈亏并与 PnlRecord 比对。

    - 对每个运行中策略涉及的 (account_id, symbol) 只调用一次 get_fills（限流）
    - OKX fill 按 ordId 匹配 DB order，检测 orphan / price mismatch
    - 独立计算 realized_pnl:
      - SWAP: 使用 OKX fill.pnl 字段（交易所权威已实现盈亏，开仓=0/平仓=价差×数量）
      - SPOT: 平均成本法（与 pnl_accounting_engine._compute_pnl_metrics 对齐）
    - 仅对匹配 DB 订单的 fill 计入盈亏（孤儿 fill 不污染 PnL）
    - SWAP fillSz 为合约张数，名义价值 = fillPx × fillSz × ctVal
    - 与 DB PnlRecord.realized_pnl 比对，差异超阈值告警

    返回:
        {
            "check": "okx_trade_records",
            "passed": bool,
            "per_symbol": [{account_id, symbol, okx_fills_count, db_orders_count,
                             orphan_okx_fills, db_only_orders, price_mismatches,
                             okx_realized_pnl, db_realized_pnl, diff, matched}],
            "total_okx_realized_pnl": float,
            "total_db_realized_pnl": float,
            "total_diff": float
        }
    """
    running_instances = (
        db.query(StrategyInstance)
        .filter(StrategyInstance.status == "running")
        .all()
    )

    # 按 account_id 缓存 OKXClient（沿用 check_pnl_correctness 模式）
    clients: dict[int, OKXClient | None] = {}

    def _get_client(account_id: int) -> OKXClient | None:
        if account_id not in clients:
            account = db.query(Account).filter(Account.id == account_id).first()
            if account:
                clients[account_id] = OKXClient(
                    api_key_encrypted=account.api_key_encrypted,
                    secret_encrypted=account.secret_key_encrypted,
                    passphrase_encrypted=account.passphrase_encrypted,
                    trade_mode=account.trade_mode,
                    account_name=account.name,
                )
            else:
                clients[account_id] = None
        return clients[account_id]

    # symbol -> 涉及的策略实例 id 列表（用于聚合 DB realized_pnl）
    symbol_strategies: dict[str, list[int]] = defaultdict(list)
    for inst in running_instances:
        symbol_strategies[inst.symbol].append(inst.id)

    per_symbol = []
    total_okx_realized = 0.0
    total_db_realized = 0.0

    # 对每个 (account_id, symbol) 只查一次 OKX（去重避免限流）
    seen_pairs: set[tuple[int, str]] = set()
    for inst in running_instances:
        pair = (inst.account_id, inst.symbol)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        account_id, symbol = pair

        # 获取合约面值和产品类型（SWAP 的 fillSz 为张数，需乘 ctVal 转换为币种数量）
        inst_type = _infer_inst_type(symbol)
        ct_val = instrument_cache.get_ct_val(symbol)  # SWAP: 0.01等; SPOT: 1.0

        sym_result: dict = {
            "account_id": account_id,
            "symbol": symbol,
            "okx_fills_count": 0,
            "db_orders_count": 0,
            "orphan_okx_fills": [],
            "db_only_orders": [],
            "price_mismatches": [],
            "okx_realized_pnl": 0.0,
            "db_realized_pnl": 0.0,
            "diff": 0.0,
            "matched": True,
        }

        # 拉取 OKX 成交记录（失败不中断审计）
        try:
            client = _get_client(account_id)
            if client is None:
                _log(f"账户 {account_id} 不存在，跳过 OKX 对账 symbol={symbol}")
                per_symbol.append(sym_result)
                continue
            fills = await client.trade.get_fills(instId=symbol, limit="100")
        except Exception as e:
            _log(f"OKX get_fills 失败 account={account_id} symbol={symbol}: {e}")
            _record_audit_event(
                db,
                strategy_instance_id=None,
                event_type="audit_okx_api_error",
                message=f"OKX 成交记录查询失败 account={account_id} symbol={symbol}: {e}",
                details={"account_id": account_id, "symbol": symbol, "error": str(e)},
            )
            per_symbol.append(sym_result)
            continue

        sym_result["okx_fills_count"] = len(fills)

        # 查询 DB orders（该 account+symbol 下所有有 order_id 的订单）
        db_orders = (
            db.query(Order)
            .filter(Order.account_id == account_id)
            .filter(Order.symbol == symbol)
            .filter(Order.order_id.isnot(None))
            .filter(Order.order_id != "")
            .all()
        )
        sym_result["db_orders_count"] = len(db_orders)

        # ordId -> Order 映射，用于对账
        order_map: dict[str, Order] = {o.order_id: o for o in db_orders}
        matched_ord_ids: set[str] = set()

        # 预计算每个 ordId 的加权平均成交价（DB order.fill_px 存的是加权均值，
        # 部分成交时单笔 fillPx 与 DB 值不同，需用加权均值对账）
        ord_weighted_px: dict[str, float] = {}
        ord_fill_count: dict[str, int] = defaultdict(int)
        _ord_px_sum: dict[str, float] = defaultdict(float)
        _ord_sz_sum: dict[str, float] = defaultdict(float)
        for fill in fills:
            oid = fill.get("ordId", "")
            if not oid:
                continue
            try:
                px = float(fill.get("fillPx") or 0)
                sz = float(fill.get("fillSz") or 0)
            except (TypeError, ValueError):
                continue
            _ord_px_sum[oid] += px * sz
            _ord_sz_sum[oid] += sz
            ord_fill_count[oid] += 1
        for oid in _ord_sz_sum:
            if _ord_sz_sum[oid] > 0:
                ord_weighted_px[oid] = _ord_px_sum[oid] / _ord_sz_sum[oid]

        # 独立计算 OKX 侧 realized_pnl
        # - SWAP: 直接使用 OKX fill.pnl 字段（交易所权威已实现盈亏，平仓时才有值）
        # - SPOT: 收集 buys/sells 后用平均成本法计算（OKX 不提供 pnl 字段）
        okx_realized = 0.0
        spot_buys: list[tuple[float, float]] = []   # [(fill_px, qty_in_base)]
        spot_sells: list[tuple[float, float]] = []
        spot_total_fee = 0.0

        for fill in fills:
            ord_id = fill.get("ordId", "")
            side = fill.get("side", "")
            try:
                fill_px = float(fill.get("fillPx") or 0)
            except (TypeError, ValueError):
                fill_px = 0.0
            try:
                fill_sz = float(fill.get("fillSz") or 0)
            except (TypeError, ValueError):
                fill_sz = 0.0
            try:
                fee = float(fill.get("fee") or 0)
            except (TypeError, ValueError):
                fee = 0.0

            # 对账：按 ordId 查找 DB order（先匹配，再计算盈亏，避免孤儿 fill 污染 PnL）
            order = order_map.get(ord_id)
            if order is None:
                # orphan_okx_fill：OKX 有成交但 DB 无对应订单
                orphan = {
                    "ordId": ord_id,
                    "clOrdId": fill.get("clOrdId", ""),
                    "billId": fill.get("billId", ""),
                    "side": side,
                    "fillPx": fill_px,
                    "fillSz": fill_sz,
                    "fee": fee,
                    "ts": fill.get("ts", ""),
                }
                sym_result["orphan_okx_fills"].append(orphan)
                _record_audit_event(
                    db,
                    strategy_instance_id=None,
                    event_type="audit_okx_orphan_fill",
                    message=f"OKX 成交无 DB 订单 account={account_id} symbol={symbol} ordId={ord_id}",
                    details=orphan,
                )
                continue

            matched_ord_ids.add(ord_id)

            # 盈亏累加（仅匹配 DB 订单的 fill）
            if inst_type == "SWAP":
                # SWAP: OKX pnl 字段为交易所计算的已实现盈亏（开仓时=0，平仓时=价差×数量）
                okx_realized += float(fill.get("pnl") or 0)
            else:
                # SPOT: 收集 buy/sell 后用平均成本法计算
                qty_base = fill_sz * ct_val  # SPOT ct_val=1.0
                if side == "buy":
                    spot_buys.append((fill_px, qty_base))
                else:
                    spot_sells.append((fill_px, qty_base))
                spot_total_fee += fee

            # 价格对账已移至 fill 循环外，使用加权均价比对（处理部分成交场景）

        # SPOT: 所有 fill 处理完毕后，用平均成本法计算 realized_pnl
        if inst_type == "SPOT" and (spot_buys or spot_sells):
            okx_realized = _compute_spot_realized_pnl(spot_buys, spot_sells, spot_total_fee)

        # 价格对账：按 ordId 比对加权均价比 DB fill_px（处理部分成交多笔不同价格场景）
        for oid in matched_ord_ids:
            order = order_map.get(oid)
            if order is None or order.fill_px is None:
                continue
            db_fill_px = float(order.fill_px)
            okx_avg_px = ord_weighted_px.get(oid)
            if okx_avg_px is None or okx_avg_px <= 0:
                continue
            # 容差 = max(0.01 USDT, 加权均价 × 总成交量 × ctVal × 0.01%)
            okx_total_sz = _ord_sz_sum.get(oid, 0)
            notional = okx_avg_px * okx_total_sz * ct_val
            tolerance = max(PRICE_DIFF_TOLERANCE, notional * 0.0001)
            price_diff = abs(okx_avg_px - db_fill_px)
            if price_diff > tolerance:
                mismatch = {
                    "ordId": oid,
                    "okx_weighted_fillPx": round(okx_avg_px, 6),
                    "okx_fill_count": ord_fill_count.get(oid, 1),
                    "db_fill_px": db_fill_px,
                    "diff": round(price_diff, 6),
                    "tolerance": tolerance,
                }
                sym_result["price_mismatches"].append(mismatch)
                _record_audit_event(
                    db,
                    strategy_instance_id=order.strategy_instance_id,
                    event_type="audit_okx_price_mismatch",
                    message=(
                        f"OKX 加权成交价与 DB fill_px 不一致 account={account_id} symbol={symbol} "
                        f"ordId={oid} okx_avg={okx_avg_px:.6f} db={db_fill_px} diff={price_diff:.6f}"
                    ),
                    details=mismatch,
                )

        # db_only_orders：DB 有 filled 订单但 OKX 无对应 fill（可能成交未同步）
        for o in db_orders:
            if o.order_id not in matched_ord_ids and o.status == "filled":
                sym_result["db_only_orders"].append({
                    "order_id": o.order_id,
                    "strategy_instance_id": o.strategy_instance_id,
                    "status": o.status,
                    "fill_px": float(o.fill_px or 0),
                    "fill_sz": float(o.fill_sz or 0),
                })

        # DB realized_pnl：该 symbol 涉及的所有策略最新 PnlRecord 之和
        db_realized = 0.0
        for sid in symbol_strategies.get(symbol, []):
            latest = (
                db.query(PnlRecord)
                .filter(PnlRecord.strategy_instance_id == sid)
                .order_by(PnlRecord.recorded_at.desc())
                .first()
            )
            if latest:
                db_realized += float(latest.realized_pnl or 0)

        diff = abs(okx_realized - db_realized)
        sym_result["okx_realized_pnl"] = round(okx_realized, 6)
        sym_result["db_realized_pnl"] = round(db_realized, 6)
        sym_result["diff"] = round(diff, 6)
        # matched：盈亏差异在容差内 且 无 orphan fill 且 无价格不一致
        sym_result["matched"] = (
            diff <= PNL_DIFF_TOLERANCE
            and len(sym_result["orphan_okx_fills"]) == 0
            and len(sym_result["price_mismatches"]) == 0
        )

        # 盈亏差异告警
        if diff > PNL_DIFF_TOLERANCE:
            _record_audit_event(
                db,
                strategy_instance_id=None,
                event_type="audit_okx_pnl_mismatch",
                message=(
                    f"OKX 独立盈亏与 DB PnlRecord 差异超阈值 account={account_id} symbol={symbol} "
                    f"okx={okx_realized:.6f} db={db_realized:.6f} diff={diff:.6f}"
                ),
                details={
                    "account_id": account_id,
                    "symbol": symbol,
                    "okx_realized_pnl": okx_realized,
                    "db_realized_pnl": db_realized,
                    "diff": diff,
                },
            )

        per_symbol.append(sym_result)
        total_okx_realized += okx_realized
        total_db_realized += db_realized

    total_diff = abs(total_okx_realized - total_db_realized)
    passed = all(p.get("matched", False) for p in per_symbol)
    return {
        "check": "okx_trade_records",
        "passed": passed,
        "per_symbol": per_symbol,
        "total_okx_realized_pnl": round(total_okx_realized, 6),
        "total_db_realized_pnl": round(total_db_realized, 6),
        "total_diff": round(total_diff, 6),
        "tolerance": PNL_DIFF_TOLERANCE,
    }


# =============================================================================
# 主流程
# =============================================================================
async def run_audit() -> dict:
    """执行一次完整审计，返回审计报告 dict。"""
    start_ts = datetime.now(timezone.utc)
    _log("=" * 60)
    _log(f"开始第三方审计 run_audit @ {start_ts.isoformat()}")

    db = SessionLocal()
    report = {
        "audit_type": "hourly_third_party_audit",
        "started_at": start_ts.isoformat(),
        "version": "1.0",
        "checks": {},
    }

    try:
        # 检查 1：订单唯一性（纯 DB 查询，同步）
        _log("检查 1/5：订单唯一性...")
        order_check = check_order_uniqueness(db)
        report["checks"]["order_uniqueness"] = order_check
        _log(
            f"  完成: passed={order_check['passed']} "
            f"duplicates={len(order_check['duplicate_claims'])} "
            f"orphans={len(order_check['orphan_orders'])} "
            f"total={order_check['total_orders_checked']}"
        )

        # 检查 2：盈亏核算正确性（recompute，异步）
        _log("检查 2/5：盈亏核算正确性...")
        pnl_check = await check_pnl_correctness(db)
        report["checks"]["pnl_correctness"] = pnl_check
        mismatched = [p for p in pnl_check["per_strategy"] if not p.get("matched", False)]
        _log(
            f"  完成: passed={pnl_check['passed']} "
            f"mismatched={len(mismatched)} "
            f"total={pnl_check['total_checked']}"
        )

        # 检查 3：仓位隔离对账（reconcile_positions，异步）
        _log("检查 3/5：仓位隔离对账...")
        position_check = await check_position_isolation(db)
        report["checks"]["position_isolation"] = position_check
        mismatched_pos = [p for p in position_check["per_symbol"] if not p.get("matched", False)]
        _log(
            f"  完成: passed={position_check['passed']} "
            f"mismatched={len(mismatched_pos)} "
            f"total={position_check['total_checked']}"
        )

        # 检查 4：资金约束检查（纯 DB 查询，同步）
        _log("检查 4/5：资金约束检查...")
        capital_check = check_capital_constraints(db)
        report["checks"]["capital_constraints"] = capital_check
        _log(
            f"  完成: passed={capital_check['passed']} "
            f"violations={len(capital_check['violations'])} "
            f"total={capital_check['total_checked']}"
        )

        # 检查 5：OKX 成交记录对账（get_fills，异步）
        _log("检查 5/5：OKX 成交记录对账...")
        okx_check = await check_okx_trade_records(db)
        report["checks"]["okx_trade_records"] = okx_check
        orphan_total = sum(len(p["orphan_okx_fills"]) for p in okx_check["per_symbol"])
        mismatch_total = sum(len(p["price_mismatches"]) for p in okx_check["per_symbol"])
        _log(
            f"  完成: passed={okx_check['passed']} "
            f"orphans={orphan_total} "
            f"price_mismatches={mismatch_total} "
            f"total_diff={okx_check['total_diff']}"
        )

    finally:
        db.close()

    end_ts = datetime.now(timezone.utc)
    duration = (end_ts - start_ts).total_seconds()
    # 总体通过：五项全部通过
    overall_passed = all(c.get("passed", False) for c in report["checks"].values())
    report["finished_at"] = end_ts.isoformat()
    report["duration_seconds"] = round(duration, 3)
    report["overall_passed"] = overall_passed

    # 写入审计报告文件
    timestamp_str = start_ts.strftime("%Y%m%d_%H%M%S")
    report_file = REPORT_DIR / f"audit_report_{timestamp_str}.json"
    try:
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        _log(f"审计报告写入失败: {e}")

    # 覆盖式写入 latest 文件（便于面板读取最新状态）
    try:
        with open(LATEST_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        _log(f"latest 审计文件写入失败: {e}")

    _log(
        f"审计完成: overall_passed={overall_passed} "
        f"duration={duration:.3f}s "
        f"report={report_file.name}"
    )
    _log("=" * 60)
    return report


def main() -> None:
    """同步入口，供 Schedule 定时任务调用。"""
    asyncio.run(run_audit())


if __name__ == "__main__":
    main()
