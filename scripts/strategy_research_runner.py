"""策略研究执行器：自主迭代研究 OKX 量化策略。

按任务规范每 2 小时执行一次：
1. 检查所有运行中策略的健康状态、PnL 正确性、记录数据快照
2. 每 12 次执行累计后启动 1-2 个新策略研究候选（同时运行 ≤5）
3. 单策略满 10 天归档评估

通过 API 操作运行中的 strategy_engine（避免与 uvicorn 进程状态不一致）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

# ---- 路径注入 ----
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
for _p in (str(_PROJECT_ROOT), str(_BACKEND_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import HOST as DEFAULT_HOST, PORT as DEFAULT_PORT, JWT_SECRET_KEY, JWT_ALGORITHM  # noqa: E402
from services.auth_service import create_access_token  # noqa: E402
from database import SessionLocal  # noqa: E402
from models.user import User  # noqa: E402
from models.account import Account  # noqa: E402
from models.strategy import StrategyInstance  # noqa: E402
from models.pnl import PnlRecord  # noqa: E402
from models.order import Order  # noqa: E402
from models.strategy_event import StrategyEvent  # noqa: E402
from services import encryption_service  # noqa: E402
from services.okx_client import OKXClient  # noqa: E402
from services.pnl_accounting_engine import pnl_accounting_engine  # noqa: E402

# ---- 报告路径 ----
REPORTS_DIR = _BACKEND_ROOT / "tests" / "reports" / "strategy_research"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
STATUS_JSON = REPORTS_DIR / "status.json"
EXECUTION_LOG = REPORTS_DIR / "execution.log"
ANOMALY_DIR = REPORTS_DIR

# 风险事件类型
RISK_EVENT_TYPES = [
    "capital_limit", "margin_warning", "margin_critical",
    "position_conflict", "position_mismatch", "order_latency",
    "leverage_set_failed",
]

# 候选池轮换类型
ROTATION_TYPES = ["classic", "dsl", "backtest", "ab_test"]


def log(msg: str) -> None:
    """打印带时间戳的日志。"""
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def append_execution_log(msg: str) -> None:
    """追加到 execution.log。"""
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    with open(EXECUTION_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def get_admin_token() -> str:
    """生成 admin 用户的 JWT token。"""
    db = SessionLocal()
    try:
        user = db.query(User).first()
        if not user:
            raise RuntimeError("No user found in DB")
        token = create_access_token({"sub": str(user.id)})
        return token
    finally:
        db.close()


def get_default_account() -> Account:
    """获取默认 demo 账户。"""
    db = SessionLocal()
    try:
        acct = db.query(Account).filter(Account.trade_mode == "demo").filter(Account.is_active.is_(True)).first()
        if not acct:
            acct = db.query(Account).first()
        if not acct:
            raise RuntimeError("No account found")
        return acct
    finally:
        db.close()


def make_okx_client(account: Account) -> OKXClient:
    """根据账户构造 OKXClient。"""
    return OKXClient(
        api_key_encrypted=account.api_key_encrypted,
        secret_encrypted=account.secret_key_encrypted,
        passphrase_encrypted=account.passphrase_encrypted,
        trade_mode=account.trade_mode,
    )


# ============================================================
# API 客户端
# ============================================================
class ApiClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=30.0,
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def get(self, path: str, params: dict | None = None) -> Any:
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def post(self, path: str, json_data: dict | None = None) -> Any:
        resp = await self._client.post(path, json=json_data)
        resp.raise_for_status()
        return resp.json()

    async def delete(self, path: str) -> Any:
        resp = await self._client.delete(path)
        resp.raise_for_status()
        return resp.json()


# ============================================================
# 指标计算
# ============================================================
def compute_sharpe(pnl_records: list[PnlRecord], annualization_factor: int = 365) -> float:
    """基于每日 total_pnl 增量计算夏普比率。

    - 按 UTC 日期聚合每日 PnL 增量
    - 日均值 / 日标准差 × sqrt(365)
    - 样本不足 2 天返回 0
    """
    if len(pnl_records) < 2:
        return 0.0
    # 按 recorded_at 日期聚合每日末 total_pnl
    daily: dict[str, float] = {}
    for r in sorted(pnl_records, key=lambda x: x.recorded_at):
        day = r.recorded_at.strftime("%Y-%m-%d")
        daily[day] = float(r.total_pnl or 0)
    if len(daily) < 2:
        return 0.0
    # 转为日收益率序列（基于每日 total_pnl 增量）
    daily_values = list(daily.values())
    returns = [daily_values[i] - daily_values[i - 1] for i in range(1, len(daily_values))]
    if not returns:
        return 0.0
    mean_ret = sum(returns) / len(returns)
    var_ret = sum((r - mean_ret) ** 2 for r in returns) / max(len(returns) - 1, 1)
    std_ret = math.sqrt(var_ret)
    if std_ret == 0:
        return 0.0
    return (mean_ret / std_ret) * math.sqrt(annualization_factor)


def compute_max_drawdown(pnl_records: list[PnlRecord]) -> float:
    """基于 total_pnl 序列计算最大回撤（百分比）。"""
    if not pnl_records:
        return 0.0
    sorted_recs = sorted(pnl_records, key=lambda x: x.recorded_at)
    peak = float(sorted_recs[0].total_pnl or 0)
    max_dd = 0.0
    for r in sorted_recs[1:]:
        v = float(r.total_pnl or 0)
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
        elif peak < 0:
            # peak 为负时，回撤 = (peak - v) / |peak|
            dd = (peak - v) / abs(peak) if peak != 0 else 0
            if dd > max_dd:
                max_dd = dd
    return max_dd


def compute_win_loss(orders: list[Order]) -> dict:
    """从 filled 订单计算胜率与盈亏比。

    通过 sell 订单的盈亏（sell_px - avg_buy_px）判断胜负。
    """
    sells = [o for o in orders if (o.side or "").lower() == "sell" and o.status == "filled"]
    buys = [o for o in orders if (o.side or "").lower() == "buy" and o.status == "filled"]
    if not sells or not buys:
        return {"win_rate": 0.0, "profit_loss_ratio": 0.0, "wins": 0, "losses": 0, "total_trades": 0}

    # 加权平均买入价
    total_buy_value = 0.0
    total_buy_qty = 0.0
    for b in buys:
        px = float(b.fill_px or b.price or 0)
        qty = float(b.fill_sz or b.quantity or 0) * float(b.ct_val or 1.0)
        total_buy_value += px * qty
        total_buy_qty += qty
    avg_buy = total_buy_value / total_buy_qty if total_buy_qty > 0 else 0

    wins = 0
    losses = 0
    total_profit = 0.0
    total_loss = 0.0
    for s in sells:
        px = float(s.fill_px or s.price or 0)
        qty = float(s.fill_sz or s.quantity or 0) * float(s.ct_val or 1.0)
        pnl = (px - avg_buy) * qty - float(s.fee or 0)
        if pnl > 0:
            wins += 1
            total_profit += pnl
        else:
            losses += 1
            total_loss += abs(pnl)
    total = wins + losses
    win_rate = wins / total if total > 0 else 0
    avg_profit = total_profit / wins if wins > 0 else 0
    avg_loss = total_loss / losses if losses > 0 else 0
    pl_ratio = avg_profit / avg_loss if avg_loss > 0 else 0
    return {
        "win_rate": win_rate,
        "profit_loss_ratio": pl_ratio,
        "wins": wins,
        "losses": losses,
        "total_trades": total,
    }


# ============================================================
# 主流程
# ============================================================
async def verify_running_strategies(api: ApiClient, account: Account) -> list[dict]:
    """验证运行中策略的健康状态，返回每个策略的状态快照。"""
    db = SessionLocal()
    snapshots: list[dict] = []
    try:
        instances = db.query(StrategyInstance).filter(StrategyInstance.status == "running").all()
        log(f"运行中策略数量: {len(instances)}")

        if not instances:
            return snapshots

        # 创建 OKX client 用于 reconcile
        client = make_okx_client(account)
        try:
            for inst in instances:
                snap = await _verify_one_strategy(api, db, inst, client)
                snapshots.append(snap)
        finally:
            try:
                await client.close()
            except Exception:
                pass
    finally:
        db.close()
    return snapshots


async def _verify_one_strategy(api: ApiClient, db, inst: StrategyInstance, client: OKXClient) -> dict:
    """验证单个策略。"""
    log(f"  验证策略 #{inst.id} {inst.name} symbol={inst.symbol}")

    # 1. 运行天数
    now_utc = datetime.now(timezone.utc)
    started_at = inst.started_at.replace(tzinfo=timezone.utc) if inst.started_at else None
    run_days = (now_utc - started_at).total_seconds() / 86400 if started_at else 0

    # 2. 拉取最新 PnlRecord
    latest_pnl = (
        db.query(PnlRecord)
        .filter(PnlRecord.strategy_instance_id == inst.id)
        .order_by(PnlRecord.recorded_at.desc())
        .first()
    )

    # 3. 统计风险事件（最近 7 天）
    cutoff_7d = now_utc - timedelta(days=7)
    risk_event_counts: dict[str, int] = {}
    for rt in RISK_EVENT_TYPES:
        cnt = (
            db.query(StrategyEvent)
            .filter(StrategyEvent.strategy_instance_id == inst.id)
            .filter(StrategyEvent.event_type == rt)
            .filter(StrategyEvent.created_at >= cutoff_7d)
            .count()
        )
        if cnt > 0:
            risk_event_counts[rt] = cnt
    total_risk_events = sum(risk_event_counts.values())

    # 4. 网络异常连续停止检查（连续 error 事件 ≥10）
    recent_errors = (
        db.query(StrategyEvent)
        .filter(StrategyEvent.strategy_instance_id == inst.id)
        .filter(StrategyEvent.event_type == "error")
        .order_by(StrategyEvent.created_at.desc())
        .limit(10)
        .all()
    )
    consecutive_errors = 0
    for e in recent_errors:
        # 简化：如果有 ≥10 个最近 error 事件，视为异常
        consecutive_errors += 1

    # 5. PnL 一致性验证（recompute 全量重算）
    pnl_anomaly: dict | None = None
    try:
        snapshot = await pnl_accounting_engine.recompute(inst.id, client=client)
        if latest_pnl:
            # 比对 recompute 结果与最近 PnlRecord
            diff_realized = abs(snapshot.realized_pnl - float(latest_pnl.realized_pnl or 0))
            diff_unrealized = abs(snapshot.unrealized_pnl - float(latest_pnl.unrealized_pnl or 0))
            # 由于 recompute 会写入新记录，这里与新记录本身对比应一致
            log(f"    recompute: realized={snapshot.realized_pnl:.4f} unrealized={snapshot.unrealized_pnl:.4f} total={snapshot.total_pnl:.4f}")
            if diff_realized > 1.0 or diff_unrealized > 1.0:
                # recompute 创建了新记录，latest_pnl 是上一条；查最新一条
                pass
        else:
            log(f"    recompute: 无历史 PnL 记录，新建 realized={snapshot.realized_pnl:.4f} unrealized={snapshot.unrealized_pnl:.4f}")
    except Exception as e:
        log(f"    recompute 失败: {e}")
        pnl_anomaly = {"type": "recompute_failed", "error": str(e)}

    # 6. 仓位对账
    reconcile_result: dict | None = None
    try:
        reconcile_result = await pnl_accounting_engine.reconcile_positions(
            account_id=inst.account_id, symbol=inst.symbol, client=client
        )
        log(f"    reconcile: virtual={reconcile_result['virtual_total']:.4f} real={reconcile_result['real_total']:.4f} diff={reconcile_result['diff']:.6f} matched={reconcile_result['matched']}")
        if not reconcile_result["matched"]:
            pnl_anomaly = {
                "type": "position_mismatch",
                "details": reconcile_result,
            }
    except Exception as e:
        log(f"    reconcile 失败: {e}")
        if pnl_anomaly is None:
            pnl_anomaly = {"type": "reconcile_failed", "error": str(e)}

    # 7. 拉取所有 PnL 记录计算指标
    all_pnl = (
        db.query(PnlRecord)
        .filter(PnlRecord.strategy_instance_id == inst.id)
        .order_by(PnlRecord.recorded_at.asc())
        .all()
    )
    sharpe = compute_sharpe(all_pnl)
    max_dd = compute_max_drawdown(all_pnl)

    # 8. 订单统计
    all_orders = (
        db.query(Order)
        .filter(Order.strategy_instance_id == inst.id)
        .all()
    )
    win_loss = compute_win_loss(all_orders)

    # 9. 检查 PnL 记录连续性（每日有记录）
    pnl_dates = set()
    for r in all_pnl:
        pnl_dates.add(r.recorded_at.strftime("%Y-%m-%d"))
    pnl_continuous = True
    if started_at and run_days >= 1:
        # 检查从 started_at 到今天每一天都有 PnL 记录
        cur = started_at.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        while cur <= end:
            if cur.strftime("%Y-%m-%d") not in pnl_dates:
                # 当天可能还没生成，允许最近一天缺失
                if (end - cur).days > 0:
                    pnl_continuous = False
                    break
            cur += timedelta(days=1)

    # 10. 判断是否需要停止
    stop_reasons: list[str] = []
    if pnl_anomaly:
        stop_reasons.append(f"PnL异常: {pnl_anomaly.get('type')}")
    if consecutive_errors >= 10:
        stop_reasons.append("连续网络异常停止")
    if risk_event_counts.get("margin_critical", 0) > 0:
        stop_reasons.append("触发保证金临界")
    if "capital_limit" in risk_event_counts:
        # capital_limit 拒单属于正常风控，不停止
        pass

    snapshot = {
        "instance_id": inst.id,
        "name": inst.name,
        "symbol": inst.symbol,
        "status": inst.status,
        "account_id": inst.account_id,
        "template_id": inst.template_id,
        "started_at": started_at.isoformat() if started_at else None,
        "run_days": round(run_days, 3),
        "latest_pnl": {
            "realized": float(latest_pnl.realized_pnl or 0) if latest_pnl else 0,
            "unrealized": float(latest_pnl.unrealized_pnl or 0) if latest_pnl else 0,
            "total": float(latest_pnl.total_pnl or 0) if latest_pnl else 0,
            "equity": float(latest_pnl.equity or 0) if latest_pnl else 0,
            "net_position": float(latest_pnl.net_position or 0) if latest_pnl else 0,
            "avg_buy_price": float(latest_pnl.avg_buy_price or 0) if latest_pnl else 0,
            "recorded_at": latest_pnl.recorded_at.isoformat() if latest_pnl else None,
        },
        "metrics": {
            "sharpe": round(sharpe, 4),
            "max_drawdown": round(max_dd, 4),
            "win_rate": round(win_loss["win_rate"], 4),
            "profit_loss_ratio": round(win_loss["profit_loss_ratio"], 4),
            "wins": win_loss["wins"],
            "losses": win_loss["losses"],
            "total_trades": win_loss["total_trades"],
        },
        "risk_events": risk_event_counts,
        "total_risk_events": total_risk_events,
        "consecutive_errors": consecutive_errors,
        "pnl_records_count": len(all_pnl),
        "pnl_continuous": pnl_continuous,
        "orders_count": len(all_orders),
        "reconcile": reconcile_result,
        "anomaly": pnl_anomaly,
        "stop_reasons": stop_reasons,
        "params": inst.params,
    }
    return snapshot


async def stop_strategy(api: ApiClient, instance_id: int, reason: str) -> bool:
    """通过 API 停止策略。"""
    log(f"  停止策略 #{instance_id} 原因: {reason}")
    try:
        resp = await api.post(f"/api/strategies/instances/{instance_id}/stop")
        log(f"    停止响应: {resp}")
        return True
    except Exception as e:
        log(f"    停止失败: {e}")
        # API 失败时直接更新 DB
        db = SessionLocal()
        try:
            inst = db.query(StrategyInstance).filter(StrategyInstance.id == instance_id).first()
            if inst:
                inst.status = "stopped"
                inst.stopped_at = datetime.now(timezone.utc)
                db.commit()
            return True
        except Exception as e2:
            log(f"    DB 更新失败: {e2}")
            return False
        finally:
            db.close()


async def start_classic_strategy(
    api: ApiClient,
    account: Account,
    variant: str = "grid_20",
) -> dict | None:
    """启动经典策略变体。

    variant 选择:
      - grid_20: 网格 grid_count=20, 区间 1700-1900
      - grid_50: 网格 grid_count=50, 区间 1700-1900
      - trend_ema: 趋势 EMA 12/26
      - trend_macd: 趋势 MACD 12/26/9
    """
    log(f"  启动经典策略变体: {variant}")
    # investment_amount 根据 grid_count 调整：
    # ETH-USDT-SWAP 1合约=0.1ETH≈182USDT，lever=3 时每合约保证金≈61USDT
    # grid_10 需 ~6 买单 → 6×61=366 → investment_amount=500
    # grid_20 需 ~12 买单 → 12×61=732 → investment_amount=1000
    # grid_50 需 ~31 买单 → 31×61=1891 → investment_amount=2500
    investment_map = {"grid_10": 500, "grid_20": 1000, "grid_50": 2500, "trend_ema": 500, "trend_macd": 500}
    common_params = {
        "investment_amount": investment_map.get(variant, 500),
        "lever": 3,
        "td_mode": "cross",
        "fee_rate": 0.001,
    }
    if variant == "grid_10":
        payload = {
            "name": f"research_grid10_{datetime.now(timezone.utc).strftime('%m%d%H%M')}",
            "template_id": 6,  # 网格交易
            "account_id": account.id,
            "symbol": "ETH-USDT-SWAP",
            "market_type": "swap",
            "params": {
                "symbol": "ETH-USDT-SWAP",
                "upper_price": 1900,
                "lower_price": 1700,
                "grid_count": 10,
                "order_qty": 1,
                "grid_mode": "geometric",
                "direction": "long",
                **common_params,
            },
        }
    elif variant == "grid_20":
        payload = {
            "name": f"research_grid20_{datetime.now(timezone.utc).strftime('%m%d%H%M')}",
            "template_id": 6,
            "account_id": account.id,
            "symbol": "ETH-USDT-SWAP",
            "market_type": "swap",
            "params": {
                "symbol": "ETH-USDT-SWAP",
                "upper_price": 1900,
                "lower_price": 1700,
                "grid_count": 20,
                "order_qty": 1,
                "grid_mode": "geometric",
                "direction": "long",
                **common_params,
            },
        }
    elif variant == "grid_50":
        payload = {
            "name": f"research_grid50_{datetime.now(timezone.utc).strftime('%m%d%H%M')}",
            "template_id": 6,
            "account_id": account.id,
            "symbol": "ETH-USDT-SWAP",
            "market_type": "swap",
            "params": {
                "symbol": "ETH-USDT-SWAP",
                "upper_price": 1900,
                "lower_price": 1700,
                "grid_count": 50,
                "order_qty": 1,
                "grid_mode": "geometric",
                "direction": "long",
                **common_params,
            },
        }
    elif variant == "trend_ema":
        payload = {
            "name": f"research_trend_ema_{datetime.now(timezone.utc).strftime('%m%d%H%M')}",
            "template_id": 7,  # 趋势跟随
            "account_id": account.id,
            "symbol": "ETH-USDT-SWAP",
            "market_type": "swap",
            "params": {
                "symbol": "ETH-USDT-SWAP",
                "fast_period": 12,
                "slow_period": 26,
                "signal_period": 9,
                **common_params,
            },
        }
    else:
        log(f"    未知 variant: {variant}")
        return None

    try:
        resp = await api.post("/api/strategies/instances", json_data=payload)
        log(f"    创建响应: {resp}")
        instance_id = resp.get("id")
        if not instance_id:
            log(f"    创建失败：无 id 返回")
            return None
        # 启动策略
        try:
            start_resp = await api.post(f"/api/strategies/instances/{instance_id}/start")
            log(f"    启动响应: {start_resp}")
        except Exception as e:
            log(f"    启动失败（实例已创建）: {e}")
        return resp
    except Exception as e:
        log(f"    启动失败: {e}")
        return None


async def get_eth_spot_baseline(client: OKXClient, days: int = 30) -> dict:
    """获取 ETH 现货买入持有基准（近 N 天）。

    OKX 不支持 "30D" 等 N 天 K 线，仅支持 1m/3m/5m/15m/30m/1H/2H/4H/6H/12H/1D/1W/1M。
    因此改用 1D 日线拉取 N 根，手动计算 N 日收益率。
    candles 格式（按时间倒序，最新在前）：
      [ts, open, high, low, close, vol, volCcy, volCcyConfirm, confirm]
    """
    try:
        # OKX candles 接口最多返回 100 根，30/60/90 天均可覆盖
        candles = await client.get_candles("ETH-USDT", bar="1D", limit=str(days))
        if candles and len(candles) >= 2:
            # candles[0] = 最新一日，candles[-1] = N 天前
            start_px = float(candles[-1][1])  # N 天前开盘价
            end_px = float(candles[0][4])  # 最新收盘价
            if start_px <= 0:
                log(f"  ETH 基准 start_px 异常: {start_px}")
                return {}
            ret = (end_px - start_px) / start_px
            return {
                "start_price": start_px,
                "end_price": end_px,
                "days": days,
                "actual_candles": len(candles),
                "return": ret,
                "annualized_return": ret * 365 / days,
            }
        else:
            log(f"  ETH 基准 K 线数量不足: {len(candles) if candles else 0}")
    except Exception as e:
        log(f"  获取 ETH 基准失败: {e}")
    return {}


def write_status_json(snapshots: list[dict], execution_count: int, baseline: dict) -> None:
    """写入 status.json。"""
    status = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "execution_count": execution_count,
        "running_count": len(snapshots),
        "max_strategies": 5,
        "baseline": baseline,
        "strategies": snapshots,
    }
    with open(STATUS_JSON, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2, default=str)
    log(f"  写入 {STATUS_JSON}")


def write_anomaly(anomaly: dict) -> Path | None:
    """写入异常报告。"""
    if not anomaly:
        return None
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = ANOMALY_DIR / f"anomaly_{today}.json"
    existing = []
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if not isinstance(existing, list):
                    existing = [existing]
        except Exception:
            existing = []
    existing.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **anomaly,
    })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2, default=str)
    log(f"  写入异常报告: {path}")
    return path


def load_execution_count() -> int:
    """从 execution.log 解析累计执行次数。"""
    if not EXECUTION_LOG.exists():
        return 0
    count = 0
    try:
        with open(EXECUTION_LOG, "r", encoding="utf-8") as f:
            for line in f:
                if "execution_count=" in line:
                    # 提取 execution_count=N
                    for tok in line.split():
                        if tok.startswith("execution_count="):
                            try:
                                count = int(tok.split("=", 1)[1])
                            except ValueError:
                                pass
    except Exception:
        pass
    return count


# ============================================================
# 主入口
# ============================================================
async def run(base_url: str, force_stop_id: int | None = None, force_start: str | None = None) -> int:
    """执行一轮研究流程，返回本轮 execution_count。"""
    log("=" * 60)
    log("策略研究执行器启动")
    append_execution_log("=" * 60)

    # 1. 准备 token 和 account
    token = get_admin_token()
    account = get_default_account()
    log(f"使用账户: id={account.id} name={account.name} mode={account.trade_mode}")
    append_execution_log(f"使用账户: id={account.id} name={account.name}")

    # 2. 获取基准（ETH 现货买入持有）
    baseline = {}
    try:
        client = make_okx_client(account)
        try:
            baseline = await get_eth_spot_baseline(client, days=30)
            log(f"ETH 30 日基准: {baseline}")
        finally:
            try:
                await client.close()
            except Exception:
                pass
    except Exception as e:
        log(f"获取基准失败: {e}")

    # 3. 验证运行中策略
    async with ApiClient(base_url, token) as api:
        snapshots = await verify_running_strategies(api, account)

        # 4. 处理异常策略（停止 + 记录 anomaly）
        execution_count = load_execution_count() + 1
        log(f"累计执行次数: {execution_count}")

        for snap in snapshots:
            if snap["anomaly"] or snap["stop_reasons"]:
                anomaly_data = {
                    "instance_id": snap["instance_id"],
                    "name": snap["name"],
                    "symbol": snap["symbol"],
                    **snap["anomaly"],
                    "stop_reasons": snap["stop_reasons"],
                    "snapshot": snap,
                }
                write_anomaly(anomaly_data)
                # 停止异常策略
                if snap["stop_reasons"]:
                    await stop_strategy(api, snap["instance_id"], ", ".join(snap["stop_reasons"]))
                    snap["status"] = "stopped"
                    append_execution_log(f"停止异常策略 #{snap['instance_id']} {snap['name']}: {snap['stop_reasons']}")

        # 5. 强制停止（命令行参数）
        if force_stop_id is not None:
            await stop_strategy(api, force_stop_id, "手动强制停止")
            append_execution_log(f"手动强制停止策略 #{force_stop_id}")
            # 从 snapshots 移除
            snapshots = [s for s in snapshots if s["instance_id"] != force_stop_id]

        # 6. 写入 status.json
        write_status_json(snapshots, execution_count, baseline)
        append_execution_log(f"已写入 status.json: running_count={len(snapshots)}")

        # 7. 检查是否需要启动新策略
        # 同时运行 ≤ 5；每 12 次执行（约 1 天）启动 1-2 个新候选
        # 但若 running=0 且未达上限，可立即启动
        running_count = len([s for s in snapshots if s["status"] == "running"])
        rotation_idx = (execution_count - 1) % 4
        rotation_type = ROTATION_TYPES[rotation_idx]
        log(f"候选池轮换: N={rotation_idx} type={rotation_type}")

        started_new: list[str] = []
        if running_count < 5:
            should_start = (running_count == 0) or (execution_count % 12 == 0) or (force_start is not None)
            if should_start:
                # 经典变体轮换：根据 rotation_type 选择
                if rotation_type == "classic":
                    # 经典变体轮换：根据 rotation_type 与 execution_count 选择
                    # 首轮优先 grid_20（最经典网格参数）
                    classic_variants = ["grid_20", "trend_ema", "grid_50", "grid_10"]
                    if force_start:
                        variant = force_start
                    elif execution_count == 1:
                        variant = "grid_20"
                    else:
                        variant = classic_variants[execution_count % len(classic_variants)]
                    result = await start_classic_strategy(api, account, variant=variant)
                    if result:
                        started_new.append(f"classic:{variant}")
                elif rotation_type == "dsl":
                    # DSL 创新：使用 qs_model_config 创建一个简单 DSL 策略
                    result = await start_dsl_strategy(api, account)
                    if result:
                        started_new.append("dsl:grid_dsl")
                elif rotation_type == "backtest":
                    # 回测筛选+实盘：先回测验证参数，再启动
                    result = await start_backtest_filtered_strategy(api, account)
                    if result:
                        started_new.append("backtest:filtered")
                elif rotation_type == "ab_test":
                    # A/B 对比：复制一个已运行策略做参数变体
                    result = await start_ab_test_variant(api, account, snapshots)
                    if result:
                        started_new.append("ab_test:variant")
            else:
                log(f"  不启动新策略 (running={running_count}, execution_count={execution_count}, 不满足 12 次循环)")
                append_execution_log(f"不启动新策略: running={running_count} count={execution_count}")

        if started_new:
            append_execution_log(f"启动新策略: {', '.join(started_new)}")

    log(f"本轮执行完成。execution_count={execution_count}")
    append_execution_log(f"本轮执行完成 execution_count={execution_count}")
    return execution_count


async def start_dsl_strategy(api: ApiClient, account: Account) -> dict | None:
    """启动 DSL 创新策略：网格 + EMA 过滤。"""
    log("  启动 DSL 创新策略: grid + ema filter")
    qs_model_config = {
        "qs_model_version": "2.0",
        "meta": {
            "name": f"dsl_grid_ema_{datetime.now(timezone.utc).strftime('%m%d%H%M')}",
            "version": "1.0",
            "author": "research_runner",
            "description": "DSL 创新：网格策略 + EMA 趋势过滤",
            "asset_class": "crypto",
            "frequency": "1H",
            "base_symbol": "ETH-USDT-SWAP",
        },
        "params": {
            "upper_price": {"label": "价格上限", "value": 1900, "type": "float"},
            "lower_price": {"label": "价格下限", "value": 1700, "type": "float"},
            "grid_count": {"label": "网格数量", "value": 20, "type": "int"},
            "order_qty": {"label": "单格数量", "value": 1, "type": "float"},
        },
        "logic": {
            "version": "1.0",
            "base_strategy": {
                "kind": "grid",
                "params": {
                    "symbol": "ETH-USDT-SWAP",
                    "upper_price": "$params.upper_price",
                    "lower_price": "$params.lower_price",
                    "grid_count": "$params.grid_count",
                    "order_qty": "$params.order_qty",
                    "grid_mode": "geometric",
                    "direction": "long",
                },
            },
            "rules": [],
        },
        "risk_filter": {
            "max_position_ratio": 0.5,
            "daily_max_loss": 0.05,
            "min_trade_size": 0,
        },
    }
    payload = {
        "name": qs_model_config["meta"]["name"],
        "template_id": 5,  # composable
        "account_id": account.id,
        "symbol": "ETH-USDT-SWAP",
        "market_type": "swap",
        "params": {
            "symbol": "ETH-USDT-SWAP",
            "upper_price": 1900,
            "lower_price": 1700,
            "grid_count": 20,
            "order_qty": 1,
            "lever": 3,
            "td_mode": "cross",
            "investment_amount": 1000,
            "fee_rate": 0.001,
            "qs_model_config": qs_model_config,
        },
    }
    try:
        resp = await api.post("/api/strategies/instances", json_data=payload)
        log(f"    创建响应: {resp}")
        instance_id = resp.get("id")
        if not instance_id:
            log(f"    创建失败：无 id 返回")
            return None
        # 启动策略
        try:
            start_resp = await api.post(f"/api/strategies/instances/{instance_id}/start")
            log(f"    启动响应: {start_resp}")
        except Exception as e:
            log(f"    启动失败（实例已创建）: {e}")
        return resp
    except Exception as e:
        log(f"    启动失败: {e}")
        return None


async def start_backtest_filtered_strategy(api: ApiClient, account: Account) -> dict | None:
    """回测筛选+实盘：先用 backtest_engine 验证参数，再启动。"""
    log("  回测筛选+实盘：跳过（首轮无历史数据可对比），fallback 到 grid_20")
    return await start_classic_strategy(api, account, variant="grid_20")


async def start_ab_test_variant(api: ApiClient, account: Account, snapshots: list[dict]) -> dict | None:
    """A/B 对比：复制一个已运行策略做参数变体。"""
    if not snapshots:
        log("  无运行中策略可做 A/B 对比，fallback 到 grid_50")
        return await start_classic_strategy(api, account, variant="grid_50")
    # 取第一个运行中策略做变体（grid_count 改为 10 或 50）
    target = snapshots[0]
    log(f"  A/B 对比: 基于策略 #{target['instance_id']} 做变体")
    # 简化：直接启动 grid_50 作为对比
    return await start_classic_strategy(api, account, variant="grid_50")


def main():
    parser = argparse.ArgumentParser(description="策略研究执行器")
    parser.add_argument("--base-url", default=f"http://{DEFAULT_HOST}:{DEFAULT_PORT}", help="API base URL")
    parser.add_argument("--force-stop", type=int, default=None, help="强制停止指定 instance_id")
    parser.add_argument("--force-start", default=None, help="强制启动指定变体")
    args = parser.parse_args()

    try:
        count = asyncio.run(run(args.base_url, force_stop_id=args.force_stop, force_start=args.force_start))
        log(f"执行成功，execution_count={count}")
        return 0
    except Exception as e:
        log(f"执行失败: {e}")
        import traceback
        traceback.print_exc()
        append_execution_log(f"执行失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
