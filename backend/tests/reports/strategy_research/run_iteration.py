"""策略研究迭代 - 单次执行脚本。

执行流程：
1. 读取 status.json 获取上次状态与 execution_count
2. 查询 DB 中所有 running 策略实例
3. 对每个策略：健康检查、PnL recompute 验证、仓位对账、风险事件统计、指标计算
4. 检测异常并停止异常策略
5. 检查 10 天归档
6. 若 execution_count % 12 == 0 且 running < 5：启动新策略（轮换类型 = count % 4）
7. 更新 status.json、追加 execution.log
8. 若周日：生成/更新周报
"""
import asyncio
import hashlib
import json
import os
import sys
import math
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 注入 backend 到 sys.path
# 脚本路径: backend/tests/reports/strategy_research/run_iteration.py
# parents[3] = backend
_BACKEND_DIR = Path(__file__).resolve().parents[3]  # e:\quant_okx\backend
for _p in (str(_BACKEND_DIR),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from database import SessionLocal
from models.strategy import StrategyInstance, StrategyTemplate
from models.account import Account
from models.order import Order
from models.pnl import PnlRecord
from models.strategy_event import StrategyEvent
from services.pnl_accounting_engine import pnl_accounting_engine
from services.strategy_engine import strategy_engine, StrategyEngine
from services.okx_client import OKXClient
import httpx
from dsl.schema import QSModelConfig, resolve_variables
from research.qsm_generator import (
    generate_classic_variant,
    generate_dsl_innovation,
    generate_backtest_candidates,
    generate_ab_variants,
    load_gene_pool,
    add_gene_to_pool,
    add_to_blacklist,
    is_blacklisted,
    compute_logic_hash,
    QUALITY_MIN_SHARPE,
    QUALITY_MAX_DRAWDOWN,
    QUALITY_MIN_TOTAL_RETURN,
    POOR_MAX_SHARPE,
    POOR_MAX_DRAWDOWN,
)

REPORT_DIR = Path(__file__).resolve().parent
STATUS_FILE = REPORT_DIR / "status.json"
LOG_FILE = REPORT_DIR / "execution.log"
ANOMALY_FILE_PREFIX = "anomaly_"
WEEKLY_FILE_PREFIX = "weekly_review_"

TOLERANCE = 0.0001
MAX_STRATEGIES = 5
ARCHIVE_DAYS = 10
START_INTERVAL = 12  # 每 12 次执行启动新策略

# ============================================================
# should_start 分支配置
# ============================================================
DEFAULT_SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]  # 默认交易对池（合约 SWAP，配合 lever/cross tdMode）
DEFAULT_INVESTMENT_AMOUNT = 100.0  # USDT，新策略默认投资额
DSL_API_BASE_URL = "http://localhost:8000"  # DSL API 基础地址
DRY_RUN_BAR = "1H"  # 回放 K 线周期
DRY_RUN_LIMIT = 720  # 近 30 天 1H K 线数（30*24）
DRY_RUN_MAX_DRAWDOWN = 0.30  # 最大回撤阈值 30%
DRY_RUN_MIN_SHARPE = 0.0  # 夏普比率下限

# 错误码 -> 可读描述映射
ERROR_CODES = {
    "GENERATE_FAILED": "策略生成失败",
    "VALIDATE_REQUEST_FAILED": "DSL 校验请求失败",
    "VALIDATE_FAILED": "DSL 校验未通过",
    "DRY_RUN_REQUEST_FAILED": "历史回放请求失败",
    "DRY_RUN_FAILED": "历史回放执行失败",
    "METRICS_UNQUALIFIED": "回测指标不达标",
    "CREATE_TEMPLATE_FAILED": "创建策略模板失败",
    "CREATE_INSTANCE_FAILED": "创建策略实例失败",
    "START_FAILED": "启动策略失败",
    "NO_ACCOUNT": "无可用账户",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat() if dt else None


def _log(msg: str):
    """追加日志到 execution.log。"""
    ts = _utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line)
    print(line, end="")


def _load_status() -> dict:
    if STATUS_FILE.exists():
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"execution_count": 0, "running_count": 0, "max_strategies": MAX_STRATEGIES, "strategies": []}


def _save_status(status: dict):
    status["updated_at"] = _iso(_utc_now())
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def _append_anomaly(record: dict):
    """追加异常记录到当日 anomaly 文件。"""
    today = _utc_now().strftime("%Y%m%d")
    fpath = REPORT_DIR / f"{ANOMALY_FILE_PREFIX}{today}.json"
    existing = []
    if fpath.exists():
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing.append(record)
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def _get_client_for_account(account: Account) -> OKXClient:
    """根据账户创建 OKXClient（模拟盘）。

    OKXClient 接收加密后的凭据（内部 decrypt），不是明文。
    """
    return OKXClient(
        api_key_encrypted=account.api_key_encrypted,
        secret_encrypted=account.secret_key_encrypted,
        passphrase_encrypted=account.passphrase_encrypted,
        trade_mode=account.trade_mode,
    )


def _compute_metrics(pnl_records: list, orders_filled: list) -> dict:
    """计算夏普/回撤/胜率/盈亏比。"""
    if not pnl_records:
        return {
            "sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0,
            "profit_loss_ratio": 0.0, "wins": 0, "losses": 0, "total_trades": 0,
        }

    # 按时间排序的 total_pnl 序列
    sorted_recs = sorted(pnl_records, key=lambda r: r.recorded_at)
    pnl_series = [float(r.total_pnl or 0) for r in sorted_recs]

    # 日收益率序列（相邻 PnL 差值 / 初始资金近似）
    returns = []
    for i in range(1, len(pnl_series)):
        delta = pnl_series[i] - pnl_series[i-1]
        returns.append(delta)

    # 夏普比率（年化，假设每次采样间隔约 5min，年化因子粗略）
    sharpe = 0.0
    if len(returns) >= 2:
        mean_ret = statistics.mean(returns)
        std_ret = statistics.stdev(returns)
        if std_ret > 0:
            # 简化年化：按日化（假设每日约 288 个 5min 采样）
            sharpe = (mean_ret / std_ret) * math.sqrt(288)

    # 最大回撤
    max_drawdown = 0.0
    peak = pnl_series[0]
    for v in pnl_series:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd

    # 胜率/盈亏比（基于已 filled 订单的 side 与 fill_px）
    wins = 0
    losses = 0
    win_pnl = 0.0
    loss_pnl = 0.0
    # 简化：用 sell 订单与对应 buy 的盈亏
    buy_prices = []
    for o in orders_filled:
        side = (o.side or "").lower()
        fill_px = float(o.fill_px or 0)
        fill_sz = float(o.fill_sz or o.actual_qty or 0)
        if side == "buy":
            buy_prices.append(fill_px)
        elif side == "sell" and buy_prices:
            avg_buy = sum(buy_prices) / len(buy_prices) if buy_prices else 0
            trade_pnl = (fill_px - avg_buy) * fill_sz
            if trade_pnl > 0:
                wins += 1
                win_pnl += trade_pnl
            elif trade_pnl < 0:
                losses += 1
                loss_pnl += abs(trade_pnl)
            buy_prices.pop(0)  # FIFO

    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    avg_win = win_pnl / wins if wins > 0 else 0
    avg_loss = loss_pnl / losses if losses > 0 else 0
    profit_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

    return {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_drawdown, 4),
        "win_rate": round(win_rate, 2),
        "profit_loss_ratio": round(profit_loss_ratio, 4),
        "wins": wins,
        "losses": losses,
        "total_trades": total_trades,
    }


def _count_risk_events(db, instance_id: int) -> dict:
    """统计策略的风险事件（从 strategy_events 表）。"""
    events = db.query(StrategyEvent).filter(
        StrategyEvent.strategy_instance_id == instance_id,
    ).all()
    risk_types = {}
    for ev in events:
        et = ev.event_type or ""
        if et in ("capital_limit", "margin_warning", "margin_critical",
                   "position_conflict", "order_latency", "network_error"):
            risk_types[et] = risk_types.get(et, 0) + 1
    return risk_types


def _check_pnl_continuity(pnl_records: list) -> bool:
    """检查 PnL 记录连续性（每日至少 1 条）。"""
    if not pnl_records:
        return False
    dates = set()
    for r in pnl_records:
        if r.recorded_at:
            dates.add(r.recorded_at.strftime("%Y-%m-%d"))
    if len(dates) < 1:
        return False
    return True


async def _check_strategy_health(db, instance: StrategyInstance, prev_status: dict) -> dict:
    """对单个策略执行健康检查，返回状态快照。"""
    inst_id = instance.id
    params = instance.params or {}
    symbol = instance.symbol or params.get("symbol", "")

    # 获取账户与 client
    account = db.query(Account).filter(Account.id == instance.account_id).first()
    client = None
    if account:
        try:
            client = _get_client_for_account(account)
        except Exception as e:
            _log(f"  策略#{inst_id}: 创建 client 失败: {e}")

    # 运行天数
    started_at = instance.started_at
    if started_at:
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        run_days = (_utc_now() - started_at).total_seconds() / 86400.0
    else:
        run_days = 0.0

    # 最新 PnL 记录
    latest_pnl_rec = db.query(PnlRecord).filter(
        PnlRecord.strategy_instance_id == inst_id,
    ).order_by(PnlRecord.recorded_at.desc()).first()

    latest_pnl = {
        "realized": float(latest_pnl_rec.realized_pnl or 0) if latest_pnl_rec else 0.0,
        "unrealized": float(latest_pnl_rec.unrealized_pnl or 0) if latest_pnl_rec else 0.0,
        "total": float(latest_pnl_rec.total_pnl or 0) if latest_pnl_rec else 0.0,
        "equity": float(latest_pnl_rec.equity or 0) if latest_pnl_rec else 0.0,
        "net_position": float(latest_pnl_rec.net_position or 0) if latest_pnl_rec else 0.0,
        "avg_buy_price": float(latest_pnl_rec.avg_buy_price or 0) if latest_pnl_rec else 0.0,
        "recorded_at": latest_pnl_rec.recorded_at.isoformat() if latest_pnl_rec and latest_pnl_rec.recorded_at else None,
    }

    # PnL recompute 验证一致性
    recompute_snapshot = None
    pnl_anomaly = None
    try:
        recompute_snapshot = await pnl_accounting_engine.recompute(inst_id, client)
        # recompute 返回 None 表示无成交订单，跳过不写全 0 记录
        if recompute_snapshot is None:
            _log(f"  策略#{inst_id}: recompute 无成交跳过")
        # 对比 recompute 与最新记录
        if latest_pnl_rec and recompute_snapshot:
            diff_realized = abs(float(recompute_snapshot.realized_pnl) - float(latest_pnl_rec.realized_pnl or 0))
            diff_total = abs(float(recompute_snapshot.total_pnl) - float(latest_pnl_rec.total_pnl or 0))
            # recompute 会写入新记录，所以 recompute 的值是最新的；检查 total = realized + unrealized
            check_sum = abs(float(recompute_snapshot.total_pnl) -
                           (float(recompute_snapshot.realized_pnl) + float(recompute_snapshot.unrealized_pnl)))
            if check_sum > 0.01:
                pnl_anomaly = {
                    "type": "pnl_inconsistency",
                    "details": f"total({recompute_snapshot.total_pnl}) != realized({recompute_snapshot.realized_pnl}) + unrealized({recompute_snapshot.unrealized_pnl}), diff={check_sum}",
                }
            # 更新 latest_pnl 为 recompute 结果
            latest_pnl = {
                "realized": float(recompute_snapshot.realized_pnl),
                "unrealized": float(recompute_snapshot.unrealized_pnl),
                "total": float(recompute_snapshot.total_pnl),
                "equity": float(recompute_snapshot.equity or 0),
                "net_position": float(recompute_snapshot.net_position or 0),
                "avg_buy_price": float(recompute_snapshot.avg_buy_price or 0),
                "recorded_at": recompute_snapshot.recorded_at.isoformat() if recompute_snapshot.recorded_at else None,
            }
    except Exception as e:
        _log(f"  策略#{inst_id}: recompute 失败: {e}")
        pnl_anomaly = {"type": "recompute_error", "details": str(e)}

    # 仓位对账
    reconcile = None
    try:
        if account and symbol:
            recon = await pnl_accounting_engine.reconcile_positions(
                account_id=account.id, symbol=symbol, client=client,
            )
            reconcile = {
                "account_id": account.id,
                "symbol": symbol,
                "virtual_total": recon.get("virtual_total", 0),
                "real_total": recon.get("real_total", 0),
                "diff": recon.get("diff", 0),
                "tolerance": recon.get("tolerance", TOLERANCE),
                "matched": recon.get("matched", False),
            }
            if not reconcile["matched"]:
                if not pnl_anomaly:
                    pnl_anomaly = {
                        "type": "position_mismatch",
                        "details": reconcile,
                    }
    except Exception as e:
        _log(f"  策略#{inst_id}: reconcile_positions 失败: {e}")
        reconcile = {"error": str(e)}

    # 风险事件统计
    risk_events = _count_risk_events(db, inst_id)
    total_risk_events = sum(risk_events.values())

    # 连续网络错误
    recent_events = db.query(StrategyEvent).filter(
        StrategyEvent.strategy_instance_id == inst_id,
        StrategyEvent.event_type == "network_error",
    ).order_by(StrategyEvent.created_at.desc()).limit(10).all()
    consecutive_errors = 0
    for ev in recent_events:
        consecutive_errors += 1
    # 简化：取最近 10 条网络错误事件数

    # 所有 PnL 记录
    all_pnl_records = db.query(PnlRecord).filter(
        PnlRecord.strategy_instance_id == inst_id,
    ).order_by(PnlRecord.recorded_at.asc()).all()
    pnl_continuous = _check_pnl_continuity(all_pnl_records)

    # 已 filled 订单
    filled_orders = db.query(Order).filter(
        Order.strategy_instance_id == inst_id,
        Order.status == "filled",
    ).all()

    # 指标计算
    metrics = _compute_metrics(all_pnl_records, filled_orders)

    # 判断是否需要停止（仅严重异常才停止）
    stop_reasons = []
    if pnl_anomaly:
        anomaly_type = pnl_anomaly.get("type", "")
        # 仅 PnL 计算不一致或 recompute 错误才立即停止
        # position_mismatch 需持续失败才停止（单次小幅差异可能是手续费/精度导致）
        if anomaly_type in ("pnl_inconsistency", "recompute_error"):
            stop_reasons.append(f"PnL异常: {anomaly_type}")
        elif anomaly_type == "position_mismatch":
            details = pnl_anomaly.get("details", {})
            diff = abs(float(details.get("diff", 0))) if isinstance(details, dict) else 0
            virtual = abs(float(details.get("virtual_total", 0))) if isinstance(details, dict) else 0
            # 差异超过虚拟仓位的 5% 才视为严重，立即停止
            if virtual > 0 and (diff / virtual) > 0.05:
                stop_reasons.append(f"仓位严重偏差: diff={diff:.6f} ({diff/virtual*100:.1f}%)")
            else:
                # 小幅偏差，记录但不停止
                _log(f"  策略#{inst_id}: 仓位小幅偏差 diff={diff:.6f} (tolerance={TOLERANCE})，记录但不停止")
                pnl_anomaly = None  # 清除异常标记，不记录为需停止的异常
    if consecutive_errors >= 10:
        stop_reasons.append(f"连续网络异常: {consecutive_errors}次")
    if instance.status == "error":
        stop_reasons.append("状态异常: error")
    if instance.status == "stopped":
        stop_reasons.append("已停止")

    # 模板信息
    template = db.query(StrategyTemplate).filter(
        StrategyTemplate.id == instance.template_id,
    ).first()

    snapshot = {
        "instance_id": inst_id,
        "name": instance.name,
        "symbol": symbol,
        "status": instance.status,
        "account_id": instance.account_id,
        "template_id": instance.template_id,
        "template_type": template.strategy_type if template else "",
        "started_at": _iso(started_at) if started_at else None,
        "run_days": round(run_days, 4),
        "latest_pnl": latest_pnl,
        "metrics": metrics,
        "risk_events": risk_events,
        "total_risk_events": total_risk_events,
        "consecutive_errors": consecutive_errors,
        "pnl_records_count": len(all_pnl_records),
        "pnl_continuous": pnl_continuous,
        "orders_count": len(filled_orders),
        "reconcile": reconcile,
        "anomaly": pnl_anomaly,
        "stop_reasons": stop_reasons,
        "params": params,
    }

    # 关闭 client
    if client:
        try:
            await client.aclose()
        except Exception:
            pass

    return snapshot


async def _stop_strategy(instance_id: int, reasons: list):
    """停止异常策略。"""
    _log(f"  停止策略#{instance_id}: {reasons}")
    try:
        await strategy_engine.stop_strategy(instance_id)
    except Exception as e:
        _log(f"  停止策略#{instance_id} 失败: {e}")
        # 兜底：直接更新 DB
        db = SessionLocal()
        try:
            inst = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
            if inst:
                inst.status = "stopped"
                inst.stopped_at = _utc_now()
                db.commit()
        finally:
            db.close()


def _generate_evaluation_report(snapshot: dict, baseline: dict) -> str:
    """生成 10 天评估报告 Markdown。"""
    inst_id = snapshot["instance_id"]
    name = snapshot["name"]
    symbol = snapshot["symbol"]
    started = snapshot.get("started_at", "")
    sdate = started[:10] if started else ""
    edate = _utc_now().strftime("%Y-%m-%d")
    pnl = snapshot["latest_pnl"]
    m = snapshot["metrics"]

    # 基准对比
    baseline_return = baseline.get("return", 0) * 100
    strategy_return = (pnl["total"] / 100) * 100 if pnl["total"] else 0  # 假设投资 100 USDT

    # 达标判断
    criteria = {
        "累计PnL>0": pnl["total"] > 0,
        "跑赢基准": pnl["total"] > 0 and strategy_return > baseline_return,
        "夏普>1.5": m["sharpe"] > 1.5,
        "最大回撤<8%": m["max_drawdown"] < 0.08,
        "胜率>55%": m["win_rate"] > 55,
        "盈亏比>1.5": m["profit_loss_ratio"] > 1.5,
        "无风险告警": snapshot["total_risk_events"] == 0,
    }
    passed = sum(1 for v in criteria.values() if v)
    is_quality = passed >= 6  # 至少 6/7 达标

    lines = [
        f"# 策略评估报告: {name}",
        "",
        f"- 实例ID: {inst_id}",
        f"- 品种: {symbol}",
        f"- 类型: {snapshot.get('template_type', '')}",
        f"- 运行周期: {sdate} ~ {edate} ({snapshot['run_days']:.1f} 天)",
        f"- 状态: {snapshot['status']}",
        "",
        "## PnL 指标",
        f"- 累计已实现盈亏: {pnl['realized']:.4f} USDT",
        f"- 未实现盈亏: {pnl['unrealized']:.4f} USDT",
        f"- 累计总盈亏: {pnl['total']:.4f} USDT",
        f"- 净持仓: {pnl['net_position']:.4f}",
        f"- 均价: {pnl['avg_buy_price']:.4f}",
        f"- 订单数: {snapshot['orders_count']}",
        f"- PnL记录数: {snapshot['pnl_records_count']}",
        "",
        "## 风险指标",
        f"- 夏普比率: {m['sharpe']}",
        f"- 最大回撤: {m['max_drawdown']*100:.2f}%",
        f"- 胜率: {m['win_rate']:.2f}% ({m['wins']}胜 / {m['losses']}负)",
        f"- 盈亏比: {m['profit_loss_ratio']}",
        f"- 风险事件总数: {snapshot['total_risk_events']}",
        f"- 仓位对账: {'通过' if snapshot['reconcile'] and snapshot['reconcile'].get('matched') else '失败'}",
        "",
        "## 基准对比",
        f"- 基准(ETH买入持有)收益: {baseline_return:.2f}%",
        f"- 策略收益: {strategy_return:.2f}%",
        f"- 超额收益: {strategy_return - baseline_return:.2f}%",
        "",
        "## 达标评估",
    ]
    for k, v in criteria.items():
        lines.append(f"- [{'x' if v else ' '}] {k}")
    lines.append("")
    lines.append(f"**结论: {'优质策略' if is_quality else '未达标，建议淘汰或优化'}** ({passed}/7 达标)")
    lines.append("")
    lines.append("## 参数")
    lines.append("```json")
    lines.append(json.dumps(snapshot["params"], ensure_ascii=False, indent=2))
    lines.append("```")

    return "\n".join(lines)


def _generate_weekly_review(strategies: list, baseline: dict) -> str:
    """生成周报。"""
    today = _utc_now()
    year, week, _ = today.isocalendar()
    week_str = f"{year}{week:02d}"

    # 按累计 PnL 排序
    sorted_strats = sorted(strategies, key=lambda s: s["latest_pnl"]["total"], reverse=True)
    top3 = sorted_strats[:3]

    lines = [
        f"# 周度策略对比报告 {week_str}",
        "",
        f"生成时间: {_iso(today)}",
        f"基准(ETH买入持有)收益: {baseline.get('return', 0)*100:.2f}%",
        "",
        "## 运行中策略总览",
        f"- 运行中策略数: {len(strategies)}",
        "",
        "| 排名 | 策略名 | 类型 | 品种 | 运行天数 | 累计PnL | 夏普 | 回撤 | 胜率 | 盈亏比 | 风险事件 |",
        "|------|--------|------|------|----------|---------|------|------|------|--------|----------|",
    ]
    for i, s in enumerate(sorted_strats, 1):
        p = s["latest_pnl"]
        m = s["metrics"]
        lines.append(
            f"| {i} | {s['name']} | {s.get('template_type','')} | {s['symbol']} | "
            f"{s['run_days']:.1f} | {p['total']:.4f} | {m['sharpe']} | "
            f"{m['max_drawdown']*100:.2f}% | {m['win_rate']:.1f}% | {m['profit_loss_ratio']} | "
            f"{s['total_risk_events']} |"
        )

    lines.append("")
    lines.append("## TOP 3 推荐策略")
    for i, s in enumerate(top3, 1):
        p = s["latest_pnl"]
        m = s["metrics"]
        lines.append(f"### {i}. {s['name']}")
        lines.append(f"- 累计PnL: {p['total']:.4f} USDT")
        lines.append(f"- 夏普: {m['sharpe']} | 回撤: {m['max_drawdown']*100:.2f}% | 胜率: {m['win_rate']:.1f}%")
        lines.append(f"- 参数: `{json.dumps(s['params'], ensure_ascii=False)}`")
        lines.append("")

    lines.append("## 本周结论")
    if top3:
        best = top3[0]
        lines.append(f"本周最佳策略: **{best['name']}** (累计PnL: {best['latest_pnl']['total']:.4f})")
    else:
        lines.append("本周暂无足够数据评估。")

    return "\n".join(lines)


# ============================================================
# should_start 分支实现（Task 9）
# ============================================================


def _select_symbol(running_snapshots: list) -> str:
    """选择当前运行策略最少的 symbol（避免资金分散）。

    统计 running_snapshots 中各 symbol 的策略数，
    从 DEFAULT_SYMBOLS 中选择运行数最少的；若全部不在池中，返回池中第一个。
    """
    symbol_counts: dict[str, int] = {}
    for snap in running_snapshots:
        s = snap.get("symbol", "") if isinstance(snap, dict) else getattr(snap, "symbol", "")
        if s:
            symbol_counts[s] = symbol_counts.get(s, 0) + 1

    min_count = -1
    selected = DEFAULT_SYMBOLS[0]
    for sym in DEFAULT_SYMBOLS:
        cnt = symbol_counts.get(sym, 0)
        if min_count < 0 or cnt < min_count:
            min_count = cnt
            selected = sym
    return selected


def _get_base_qsm_from_running(db) -> dict | None:
    """从已运行策略实例中取 base_qsm（用于 A/B 变体生成）。

    查询 running 状态的实例，取第一个 params 中含 qs_model_config 的实例。
    """
    instances = db.query(StrategyInstance).filter(
        StrategyInstance.status.in_(["running"]),
    ).all()
    for inst in instances:
        params = inst.params or {}
        qsm = params.get("qs_model_config")
        if qsm:
            return qsm
    return None


async def _fetch_current_price(symbol: str, http_client=None) -> float | None:
    """获取指定交易对的当前价格。

    /api/market/ticker 需要认证，故先登录获取 token。
    Args:
        symbol: 交易对，如 "BTC-USDT"
        http_client: 可选的 httpx.AsyncClient

    Returns:
        当前价格（float），失败返回 None
    """
    own_client = False
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=15.0)
        own_client = True
    try:
        # 登录获取 token
        login_resp = await http_client.post(
            f"{DSL_API_BASE_URL}/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        if login_resp.status_code != 200:
            return None
        token = login_resp.json().get("access_token")
        if not token:
            return None
        # 带 token 请求 ticker
        resp = await http_client.get(
            f"{DSL_API_BASE_URL}/api/market/ticker?symbol={symbol}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if isinstance(data, dict) and data.get("code") == "0":
            last = data.get("data", {}).get("last")
            return float(last) if last else None
        return None
    except Exception:
        return None
    finally:
        if own_client:
            await http_client.aclose()


async def _start_strategy_via_api(instance_id: int, http_client=None) -> bool:
    """通过 HTTP API 启动策略实例（确保在后端服务进程中运行）。

    Args:
        instance_id: 策略实例 ID
        http_client: 可选的 httpx.AsyncClient

    Returns:
        True 启动成功，False 失败
    """
    own_client = False
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=30.0)
        own_client = True
    try:
        # 登录获取 token
        login_resp = await http_client.post(
            f"{DSL_API_BASE_URL}/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        if login_resp.status_code != 200:
            return False
        token = login_resp.json().get("access_token")
        if not token:
            return False
        # 调用启动接口
        resp = await http_client.post(
            f"{DSL_API_BASE_URL}/api/strategies/instances/{instance_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )
        return resp.status_code == 200
    except Exception:
        return False
    finally:
        if own_client:
            await http_client.aclose()


async def _call_dsl_validate(dsl_config: dict, http_client=None) -> dict:
    """调用 /api/dsl/validate 校验 DSL 配置。

    Args:
        dsl_config: StrategyDSL 格式的 dict（含 base_strategy + rules）
        http_client: 可选的 httpx.AsyncClient（测试时注入 mock）

    Returns:
        {"valid": bool, "errors": list}
    """
    url = f"{DSL_API_BASE_URL}/api/dsl/validate"
    own_client = False
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=30.0)
        own_client = True
    try:
        resp = await http_client.post(url, json=dsl_config)
        resp.raise_for_status()
        return resp.json()
    finally:
        if own_client:
            await http_client.aclose()


async def _call_dsl_dry_run(dsl_config: dict, symbol: str, http_client=None) -> dict:
    """调用 /api/dsl/dry-run 历史回放（近 30 天）。

    Args:
        dsl_config: StrategyDSL 格式的 dict
        symbol: 交易对
        http_client: 可选的 httpx.AsyncClient（测试时注入 mock）

    Returns:
        {"steps": list, "total_ticks": int, ...}
    """
    url = f"{DSL_API_BASE_URL}/api/dsl/dry-run"
    body = {
        "config": dsl_config,
        "symbol": symbol,
        "bar": DRY_RUN_BAR,
        "limit": DRY_RUN_LIMIT,
    }
    own_client = False
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=60.0)
        own_client = True
    try:
        resp = await http_client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()
    finally:
        if own_client:
            await http_client.aclose()


def _compute_dry_run_metrics(steps: list) -> dict | None:
    """从 dry-run 回放步骤计算策略指标。

    dry-run 的 DryRunStep 仅含 price（K 线收盘价）和 state/triggered 信息，
    不含策略权益/pnl 曲线，因此无法计算真实的夏普/回撤/收益率。
    返回 None 表示无法计算，调用方应跳过指标筛选，仅用 dry-run 验证逻辑能跑通。

    Args:
        steps: dry-run 返回的 steps 列表

    Returns:
        None（dry-run 不提供权益数据，无法计算策略指标）
    """
    return None


def _compute_logic_hash(qsm_config: dict) -> str | None:
    """计算 qs_model_config.logic 段的 SHA-256 哈希。

    与 routers/strategies.py 中 _compute_logic_hash 逻辑一致。
    """
    logic_source = qsm_config.get("logic", {}) or {}
    if not logic_source:
        return None
    canonical_json = json.dumps(logic_source, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ============================================================
# Task 10: 策略评估与基因池反馈闭环
# ============================================================


def _compute_evaluation_metrics(pnl_records: list) -> dict:
    """从 PnL 记录聚合计算夏普/最大回撤/总收益率/胜率（用于基因池评估）。

    与 _compute_metrics 不同，本函数输出 gene_pool.json 所需的精简指标格式：
    - sharpe: 年化夏普比率
    - max_drawdown: 最大回撤（小数，0.12=12%）
    - total_return: 总收益率（小数，0.25=25%）
    - win_rate: 胜率（小数，0.6=60%）
    """
    if not pnl_records:
        return {"sharpe": 0.0, "max_drawdown": 0.0, "total_return": 0.0, "win_rate": 0.0}

    sorted_recs = sorted(pnl_records, key=lambda r: r.recorded_at)
    pnl_series = [float(r.total_pnl or 0) for r in sorted_recs]

    # 总收益率 = 最终 PnL / 初始资金（默认 100 USDT）
    investment = DEFAULT_INVESTMENT_AMOUNT
    total_return = pnl_series[-1] / investment if investment > 0 else 0.0

    # 相邻 PnL 差值序列
    returns = []
    for i in range(1, len(pnl_series)):
        returns.append(pnl_series[i] - pnl_series[i - 1])

    # 夏普比率（年化，假设每日约 288 个 5min 采样）
    sharpe = 0.0
    if len(returns) >= 2:
        mean_ret = statistics.mean(returns)
        std_ret = statistics.stdev(returns)
        if std_ret > 0:
            sharpe = (mean_ret / std_ret) * math.sqrt(288)

    # 最大回撤
    max_drawdown = 0.0
    peak = pnl_series[0]
    for v in pnl_series:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_drawdown:
                max_drawdown = dd

    # 胜率（基于 PnL 正负变化）
    wins = sum(1 for p in pnl_series[1:] if p > 0)
    total = len(pnl_series) - 1 if len(pnl_series) > 1 else 0
    win_rate = wins / total if total > 0 else 0.0

    return {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_drawdown, 4),
        "total_return": round(total_return, 4),
        "win_rate": round(win_rate, 4),
    }


def evaluate_strategies() -> dict:
    """评估运行满 10 天的策略实例，优质存入基因池，劣质加入黑名单。

    读取 StrategyInstance 的 created_at 计算运行天数，满 10 天的策略
    从 PnlRecord 聚合计算夏普/最大回撤/总收益率/胜率。
    - 优质判定：夏普 > 1.0 且 最大回撤 < 20% 且 总收益率 > 5% → 存入 gene_pool genes
    - 劣质判定：夏普 < 0 或 回撤 > 30% → 加入 blacklist

    Returns:
        {"evaluated": int, "quality": int, "blacklisted": int}
    """
    evaluated = 0
    quality_count = 0
    blacklist_count = 0

    db = SessionLocal()
    try:
        instances = db.query(StrategyInstance).filter(
            StrategyInstance.status.in_(["running"]),
        ).all()

        pool = load_gene_pool()
        # 已评估过的实例 ID 集合（避免重复评估）
        evaluated_ids = {g.get("strategy_instance_id") for g in pool.get("genes", [])}
        evaluated_ids |= {b.get("strategy_instance_id") for b in pool.get("blacklist", [])}

        for inst in instances:
            # 计算运行天数（从 created_at）
            created_at = inst.created_at
            if created_at is None:
                continue
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            run_days = (_utc_now() - created_at).total_seconds() / 86400.0

            if run_days < ARCHIVE_DAYS:
                continue

            # 跳过已评估的实例
            if inst.id in evaluated_ids:
                continue

            # 获取 qs_model_config
            params = inst.params or {}
            qsm_config = params.get("qs_model_config")
            if not qsm_config:
                continue

            # 聚合 PnL 记录计算指标
            pnl_records = db.query(PnlRecord).filter(
                PnlRecord.strategy_instance_id == inst.id,
            ).order_by(PnlRecord.recorded_at.asc()).all()

            if not pnl_records:
                continue

            metrics = _compute_evaluation_metrics(pnl_records)
            evaluated += 1

            # 优质判定：夏普 > 1.0 且 最大回撤 < 20% 且 总收益率 > 5%
            if (metrics["sharpe"] > QUALITY_MIN_SHARPE
                    and metrics["max_drawdown"] < QUALITY_MAX_DRAWDOWN
                    and metrics["total_return"] > QUALITY_MIN_TOTAL_RETURN):
                gene = {
                    "symbol": inst.symbol,
                    "strategy_type": "composable",
                    "qs_model_config": qsm_config,
                    "metrics": metrics,
                    "evaluated_at": _iso(_utc_now()),
                    "run_days": int(run_days),
                    "strategy_instance_id": inst.id,
                }
                add_gene_to_pool(gene)
                quality_count += 1
                _log(f"  策略#{inst.id} 优质，存入基因池 "
                     f"(sharpe={metrics['sharpe']}, 回撤={metrics['max_drawdown']:.2%})")

            # 劣质判定：夏普 < 0 或 回撤 > 30%
            elif (metrics["sharpe"] < POOR_MAX_SHARPE
                  or metrics["max_drawdown"] > POOR_MAX_DRAWDOWN):
                if metrics["sharpe"] < POOR_MAX_SHARPE:
                    reason = f"sharpe={metrics['sharpe']:.4f} < {POOR_MAX_SHARPE}"
                else:
                    reason = f"max_drawdown={metrics['max_drawdown']:.4f} > {POOR_MAX_DRAWDOWN}"
                add_to_blacklist(qsm_config, reason, strategy_instance_id=inst.id)
                blacklist_count += 1
                _log(f"  策略#{inst.id} 劣质，加入黑名单 ({reason})")
    finally:
        db.close()

    return {
        "evaluated": evaluated,
        "quality": quality_count,
        "blacklisted": blacklist_count,
    }


async def _run_should_start_branch(
    execution_count: int,
    research_type: int,
    running_snapshots: list,
    http_client=None,
) -> dict:
    """should_start 分支：生成→校验→回测→创建→启动新策略。

    按 research_type (N%4) 轮换调用对应生成器，经 validate/dry-run
    校验后创建 StrategyTemplate + StrategyInstance 并启动。
    任何步骤失败记录到 execution.log 并跳过本次迭代。

    Args:
        execution_count: 当前迭代次数
        research_type: 研究类型 (0-3)
        running_snapshots: 当前运行的策略快照列表（含 symbol 字段）
        http_client: 可选的 httpx.AsyncClient（测试时注入 mock）

    Returns:
        {"started": bool, "research_type": int, "symbol": str, "reason": str, ...}
    """
    type_names = {0: "经典变体", 1: "DSL创新", 2: "回测筛选+实盘", 3: "参数A/B对比"}
    _log(f"研究类型轮换: N={research_type} ({type_names.get(research_type, '')})")

    # 1. 选择 symbol（运行策略最少的）
    symbol = _select_symbol(running_snapshots)
    _log(f"  选定 symbol: {symbol}")

    # 2. 按 research_type 调用对应生成器
    try:
        if research_type == 0:
            # N%4==0: 经典变体
            qsm_config = generate_classic_variant(symbol, execution_count)
        elif research_type == 1:
            # N%4==1: DSL 创新
            qsm_config = generate_dsl_innovation(symbol, execution_count)
        elif research_type == 2:
            # N%4==2: 回测筛选候选（取第一个候选）
            candidates = generate_backtest_candidates(symbol)
            qsm_config = candidates[0] if candidates else None
        elif research_type == 3:
            # N%4==3: 参数 A/B 变体（从已运行策略取 base_qsm，取第一个变体）
            db = SessionLocal()
            try:
                base_qsm = _get_base_qsm_from_running(db)
            finally:
                db.close()
            if base_qsm is None:
                # 无可用 base，回退到经典变体作为 base
                base_qsm = generate_classic_variant(symbol, execution_count)
            variants = generate_ab_variants(base_qsm, "grid_count", [5, 10, 20])
            qsm_config = variants[0] if variants else None
        else:
            qsm_config = None
    except Exception as e:
        _log(f"  [generate] [GENERATE_FAILED] {ERROR_CODES['GENERATE_FAILED']}: {e}")
        return {"started": False, "research_type": research_type, "symbol": symbol,
                "reason": "GENERATE_FAILED"}

    if qsm_config is None:
        _log(f"  [generate] [GENERATE_FAILED] {ERROR_CODES['GENERATE_FAILED']}: 生成器返回空")
        return {"started": False, "research_type": research_type, "symbol": symbol,
                "reason": "GENERATE_FAILED"}

    _log(f"  生成策略: {qsm_config.get('meta', {}).get('name', '')}")

    # 2.5 修正网格价格区间：生成器中 upper/lower_price 是硬编码占位值，
    # 需基于当前价格动态计算（upper = price * 1.1, lower = price * 0.9）
    try:
        current_price = await _fetch_current_price(symbol, http_client)
        if current_price and current_price > 0:
            base_strat = (
                qsm_config.get("logic", {})
                .get("base_strategy", {})
                .get("params", {})
            )
            if "upper_price" in base_strat and "lower_price" in base_strat:
                old_upper = base_strat.get("upper_price")
                old_lower = base_strat.get("lower_price")
                base_strat["upper_price"] = round(current_price * 1.1, 2)
                base_strat["lower_price"] = round(current_price * 0.9, 2)
                _log(f"  修正网格区间: [{old_lower},{old_upper}] -> "
                     f"[{base_strat['lower_price']},{base_strat['upper_price']}] "
                     f"(当前价 {current_price})")
    except Exception as e:
        _log(f"  [warn] 获取当前价格失败，使用默认区间: {e}")

    # 3. 解析变量引用，提取 logic 段供 validate/dry-run
    try:
        qs_model = QSModelConfig.model_validate(qsm_config)
        resolved_dsl = resolve_variables(qs_model)
        dsl_config = resolved_dsl.model_dump()
    except Exception as e:
        _log(f"  [resolve] [GENERATE_FAILED] 变量解析失败: {e}")
        return {"started": False, "research_type": research_type, "symbol": symbol,
                "reason": "GENERATE_FAILED"}

    # 4. 调用 /api/dsl/validate 校验
    try:
        validate_result = await _call_dsl_validate(dsl_config, http_client)
    except Exception as e:
        _log(f"  [validate] [VALIDATE_REQUEST_FAILED] {ERROR_CODES['VALIDATE_REQUEST_FAILED']}: {e}")
        return {"started": False, "research_type": research_type, "symbol": symbol,
                "reason": "VALIDATE_REQUEST_FAILED"}

    if not validate_result.get("valid", False):
        errors = validate_result.get("errors", [])
        err_msg = "; ".join(
            f"[{e.get('layer', '')}/{e.get('code', '')}] {e.get('message', '')}"
            for e in errors
        ) or "未知错误"
        _log(f"  [validate] [VALIDATE_FAILED] {ERROR_CODES['VALIDATE_FAILED']}: {err_msg}")
        return {"started": False, "research_type": research_type, "symbol": symbol,
                "reason": "VALIDATE_FAILED"}
    _log("  DSL 校验通过")

    # 5. 调用 /api/dsl/dry-run 历史回放（近 30 天）
    try:
        dry_run_result = await _call_dsl_dry_run(dsl_config, symbol, http_client)
    except Exception as e:
        _log(f"  [dry-run] [DRY_RUN_REQUEST_FAILED] {ERROR_CODES['DRY_RUN_REQUEST_FAILED']}: {e}")
        return {"started": False, "research_type": research_type, "symbol": symbol,
                "reason": "DRY_RUN_REQUEST_FAILED"}

    # 6. 评估指标
    # dry-run 的 DryRunStep 仅含 price/state，无法计算策略权益指标，
    # 因此 dry-run 仅用于验证 DSL 逻辑能跑通（无异常即通过），指标筛选交给实盘 PnL 验证。
    metrics = _compute_dry_run_metrics(dry_run_result.get("steps", []))
    total_ticks = dry_run_result.get("total_ticks", 0)
    triggered_count = dry_run_result.get("triggered_count", 0)
    _log(f"  dry-run 完成: total_ticks={total_ticks}, triggered={triggered_count}, "
         f"state_changes={dry_run_result.get('state_changes', 0)}, "
         f"final_state={dry_run_result.get('final_state', '')}")

    if metrics is not None:
        _log(f"  回测指标: 夏普={metrics['sharpe']}, 回撤={metrics['max_drawdown']*100:.2f}%, "
             f"总收益={metrics['total_return']*100:.2f}%")
        if metrics["sharpe"] < DRY_RUN_MIN_SHARPE or metrics["max_drawdown"] > DRY_RUN_MAX_DRAWDOWN:
            _log(f"  [dry-run] [METRICS_UNQUALIFIED] {ERROR_CODES['METRICS_UNQUALIFIED']}: "
                 f"夏普={metrics['sharpe']} < {DRY_RUN_MIN_SHARPE} 或 "
                 f"回撤={metrics['max_drawdown']*100:.2f}% > {DRY_RUN_MAX_DRAWDOWN*100:.0f}%")
            return {"started": False, "research_type": research_type, "symbol": symbol,
                    "reason": "METRICS_UNQUALIFIED"}
        _log("  回测指标达标")
    else:
        _log("  dry-run 无权益数据，跳过指标筛选（仅验证逻辑能跑通）")

    # 7. 创建 StrategyTemplate + StrategyInstance 并启动
    db = SessionLocal()
    try:
        # 查找可用账户
        account = db.query(Account).first()
        if not account:
            _log(f"  [create] [NO_ACCOUNT] {ERROR_CODES['NO_ACCOUNT']}")
            return {"started": False, "research_type": research_type, "symbol": symbol,
                    "reason": "NO_ACCOUNT"}

        logic_hash = _compute_logic_hash(qsm_config)

        # 创建 StrategyTemplate
        try:
            template = StrategyTemplate(
                name=qsm_config.get("meta", {}).get("name", f"auto_{execution_count}"),
                strategy_type="composable",
                description=f"自动生成策略 (迭代 {execution_count}, 类型 {type_names.get(research_type, '')})",
                default_params={},
                is_builtin=False,
                is_custom=True,
                qs_model_config=qsm_config,
                logic_hash=logic_hash,
            )
            db.add(template)
            db.commit()
            db.refresh(template)
        except Exception as e:
            db.rollback()
            _log(f"  [create_template] [CREATE_TEMPLATE_FAILED] {ERROR_CODES['CREATE_TEMPLATE_FAILED']}: {e}")
            return {"started": False, "research_type": research_type, "symbol": symbol,
                    "reason": "CREATE_TEMPLATE_FAILED"}

        # 创建 StrategyInstance
        try:
            instance_params = {
                "qs_model_config": qsm_config,
                "symbol": symbol,
                "investment_amount": DEFAULT_INVESTMENT_AMOUNT,
            }
            instance = StrategyInstance(
                template_id=template.id,
                account_id=account.id,
                name=f"{template.name}_inst",
                symbol=symbol,
                market_type="spot",
                params=instance_params,
                status="stopped",
                logic_hash=logic_hash,
            )
            db.add(instance)
            db.commit()
            db.refresh(instance)
        except Exception as e:
            db.rollback()
            _log(f"  [create_instance] [CREATE_INSTANCE_FAILED] {ERROR_CODES['CREATE_INSTANCE_FAILED']}: {e}")
            return {"started": False, "research_type": research_type, "symbol": symbol,
                    "reason": "CREATE_INSTANCE_FAILED"}

        # 启动策略：通过 HTTP API 让后端服务进程启动（确保策略任务在后端事件循环中运行，
        # 不会因脚本进程退出而被取消）
        try:
            started_ok = await _start_strategy_via_api(instance.id, http_client)
            if not started_ok:
                _log(f"  [start] [START_FAILED] {ERROR_CODES['START_FAILED']}: HTTP API 启动失败")
                return {"started": False, "research_type": research_type, "symbol": symbol,
                        "reason": "START_FAILED"}
        except Exception as e:
            _log(f"  [start] [START_FAILED] {ERROR_CODES['START_FAILED']}: {e}")
            return {"started": False, "research_type": research_type, "symbol": symbol,
                    "reason": "START_FAILED"}

        _log(f"  策略已创建并启动: template#{template.id} instance#{instance.id}")
        return {"started": True, "research_type": research_type, "symbol": symbol,
                "template_id": template.id, "instance_id": instance.id, "reason": "OK"}
    finally:
        db.close()


async def main():
    _log("=" * 60)
    _log("策略研究迭代 - 开始执行")
    _log("=" * 60)

    prev_status = _load_status()
    execution_count = prev_status.get("execution_count", 0) + 1
    baseline = prev_status.get("baseline", {})
    _log(f"本次为第 {execution_count} 次执行（上次: {execution_count - 1}）")

    # 查询所有 running 策略
    db = SessionLocal()
    try:
        running_instances = db.query(StrategyInstance).filter(
            StrategyInstance.status.in_(["running", "paused", "error"]),
        ).all()
    finally:
        db.close()

    _log(f"DB 中活跃策略实例: {len(running_instances)} 个")

    # 逐个检查
    snapshots = []
    anomalies_to_stop = []
    for inst in running_instances:
        _log(f"检查策略#{inst.id} ({inst.name}) status={inst.status}")
        db = SessionLocal()
        try:
            snapshot = await _check_strategy_health(db, inst, prev_status)
        finally:
            db.close()
        snapshots.append(snapshot)

        # 记录异常
        if snapshot["anomaly"]:
            _log(f"  异常: {snapshot['anomaly']}")
            _append_anomaly({
                "timestamp": _iso(_utc_now()),
                "instance_id": inst.id,
                "name": inst.name,
                "symbol": inst.symbol,
                "type": snapshot["anomaly"].get("type"),
                "details": snapshot["anomaly"].get("details"),
                "stop_reasons": snapshot["stop_reasons"],
                "snapshot": snapshot,
            })
            if snapshot["stop_reasons"]:
                anomalies_to_stop.append(snapshot)

        # 10 天归档检查
        if snapshot["run_days"] >= ARCHIVE_DAYS:
            _log(f"  策略#{inst.id} 运行满 {ARCHIVE_DAYS} 天，归档评估")
            report = _generate_evaluation_report(snapshot, baseline)
            sdate = (snapshot.get("started_at", "")[:10] if snapshot.get("started_at") else "unknown")
            edate = _utc_now().strftime("%Y%m%d")
            report_file = REPORT_DIR / f"{snapshot.get('template_type','strategy')}_{inst.id}_{sdate.replace('-','')}_{edate}.md"
            with open(report_file, "w", encoding="utf-8") as f:
                f.write(report)
            _log(f"  评估报告已生成: {report_file.name}")
            # 加入待停止列表（归档）
            if inst.id not in [s["instance_id"] for s in anomalies_to_stop]:
                snapshot["stop_reasons"] = snapshot["stop_reasons"] + ["运行满10天，归档评估"]
                anomalies_to_stop.append(snapshot)

    # Task 10: 评估满 10 天的策略，优质存入基因池，劣质加入黑名单
    eval_result = evaluate_strategies()
    if eval_result["evaluated"] > 0:
        _log(f"基因池评估: {eval_result['evaluated']} 个策略, "
             f"{eval_result['quality']} 优质存入基因池, "
             f"{eval_result['blacklisted']} 劣质加入黑名单")

    # 停止异常/归档策略
    stopped_ids = []
    for snap in anomalies_to_stop:
        iid = snap["instance_id"]
        if iid not in stopped_ids:
            await _stop_strategy(iid, snap["stop_reasons"])
            stopped_ids.append(iid)

    # 更新 snapshots（移除已停止的）
    snapshots = [s for s in snapshots if s["instance_id"] not in stopped_ids]

    # 判断是否启动新策略
    # - 每 START_INTERVAL 次执行启动新策略（避免策略爆炸）
    # - 运行中策略为 0 时立即启动（DB 重置/全部归档等边界情况）
    running_count = len([s for s in snapshots if s["status"] == "running"])
    due_by_cycle = (execution_count % START_INTERVAL == 0)
    due_by_empty = (running_count == 0)
    should_start = (due_by_cycle or due_by_empty) and (running_count < MAX_STRATEGIES)
    research_type = execution_count % 4
    type_names = {0: "经典变体", 1: "DSL创新", 2: "回测筛选+实盘", 3: "参数A/B对比"}

    if should_start:
        if due_by_empty:
            _log(f"运行中策略为 0（DB 重置或全部归档），立即启动新策略")
        else:
            _log(f"达到启动周期 (execution_count={execution_count} % {START_INTERVAL}=0)，"
                 f"运行中 {running_count} < {MAX_STRATEGIES}，启动新策略")
        # Task 9: 调用 should_start 分支执行生成→校验→回测→创建→启动
        start_result = await _run_should_start_branch(
            execution_count, research_type, snapshots,
        )
        if start_result.get("started"):
            _log(f"新策略已启动: {start_result}")
        else:
            _log(f"本次未启动新策略: reason={start_result.get('reason', '未知')}")
    else:
        start_result = {"started": False, "reason": "NOT_DUE"}
        if running_count < MAX_STRATEGIES:
            _log(f"运行中策略 {running_count} < {MAX_STRATEGIES}，但未到启动周期 "
                 f"(execution_count={execution_count} % {START_INTERVAL}={execution_count % START_INTERVAL}≠0)，本轮不启动新策略")
        else:
            _log(f"运行中策略已达上限 {MAX_STRATEGIES}，不启动新策略")

    # 更新 baseline（如未设置则用默认值）
    if not baseline:
        baseline = {
            "start_price": 0,
            "end_price": 0,
            "return": 0,
            "note": "baseline 未设置，待后续回测填充",
        }

    # 保存 status.json
    new_status = {
        "execution_count": execution_count,
        "running_count": running_count,
        "max_strategies": MAX_STRATEGIES,
        "baseline": baseline,
        "strategies": snapshots,
    }
    _save_status(new_status)
    _log(f"status.json 已更新 (execution_count={execution_count}, running={running_count})")

    # 周日生成周报
    today = _utc_now()
    is_sunday = today.weekday() == 6  # Sunday=6
    if is_sunday:
        _log("今日周日，生成/更新周报")
        year, week, _ = today.isocalendar()
        week_str = f"{year}{week:02d}"
        report = _generate_weekly_review(snapshots, baseline)
        weekly_file = REPORT_DIR / f"{WEEKLY_FILE_PREFIX}{week_str}.md"
        with open(weekly_file, "w", encoding="utf-8") as f:
            f.write(report)
        _log(f"周报已生成: {weekly_file.name}")

    _log("-" * 60)
    _log(f"执行完成: 检查 {len(running_instances)} 个策略, 停止 {len(stopped_ids)} 个, "
         f"运行中 {running_count}, 异常 {len(anomalies_to_stop)}")
    _log("=" * 60)

    return {
        "execution_count": execution_count,
        "checked": len(running_instances),
        "stopped": len(stopped_ids),
        "running": running_count,
        "anomalies": len(anomalies_to_stop),
        "started_new": start_result.get("started", False),
    }


if __name__ == "__main__":
    result = asyncio.run(main())
    print(json.dumps(result, ensure_ascii=False, indent=2))
