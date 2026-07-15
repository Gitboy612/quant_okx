"""策略系统功能检测脚本：定时核验策略功能正确性。

与 audit_runner.py（数据审计）解耦，本脚本聚焦于策略算法层面的功能核验，
职责边界：发现问题 → 写入检测报告 + 记录告警事件，绝不修改业务数据
（异常写入 strategy_events 表除外）。

三项检查：
1. 理论挂单 vs 实际挂单：根据网格算法计算理论挂单档位，与 DB orders 表
   status='live' 订单对比，找出缺失/多余/价格不匹配的订单。
2. 策略检测问题排查：查询 strategy_events 表最近 1 小时 error 事件，
   按错误类型分类统计，给出修复建议。
3. 实际盈亏核验：从 OKX 拉取真实成交记录（get_fills），用 FIFO 配对
   独立计算 realized_pnl，与 DB PnlRecord.realized_pnl 比对。

输出：
- backend/tests/reports/strategy_research/function_check_report_{YYYYMMDD_HHMMSS}.json
- backend/tests/reports/strategy_research/function_check_latest.json（覆盖式）
- 异常写入 StrategyEvent 表（event_type=function_check_*），供监控告警链路消费

约束：
- 只读检测，不修改业务数据（例外见下）
- OKX API 调用失败不中断检查
- 中文注释

例外（矫正性回补，非业务数据修改）：
- 检查 3 会用 OKX fills 的 ts 回补 DB Order.update_time（仅当 update_time 为空时）。
  这是针对 uTime 传递修复前历史遗留数据的矫正动作，使 PnlAccountingEngine.recompute
  能用正确的成交时间排序，避免 okx_vs_db_fifo_diff 假阳性。
- 回补后触发 recompute 重新核算 PnlRecord，确保三方（OKX FIFO / DB FIFO / PnlRecord）一致。
"""
import asyncio
import json
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 注入 backend 到 sys.path
# 脚本路径: backend/tests/reports/strategy_research/function_checker.py
# parents[3] = backend
_BACKEND_DIR = Path(__file__).resolve().parents[3]
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
from services.okx_client import OKXClient
from services.instrument_cache import instrument_cache
from services.pnl_accounting_engine import pnl_accounting_engine

# 启动时确保表结构存在（异地部署或首次运行）
try:
    init_db()
except Exception as e:
    print(f"[function_checker] init_db warning: {e}", flush=True)

REPORT_DIR = Path(__file__).resolve().parent
LATEST_FILE = REPORT_DIR / "function_check_latest.json"
CHECK_LOG = REPORT_DIR / "function_check.log"

# 检测阈值
PNL_DIFF_TOLERANCE = 0.5  # 盈亏重算差异容差（USDT）：DB FIFO vs PnlRecord
# OKX vs DB FIFO 差异容差（USDT）：超过说明 DB 与 OKX 真实成交不同步
# 注意：OKX FIFO 按单笔成交（partial fills）配对，DB FIFO 按订单聚合配对，
# 部分成交时两者存在固有差异（每笔 partial fill 价格不同，聚合后用加权均价）。
# 1984 单的 BTC-USDT 策略实测固有差异 ~6 USDT，容差设为 10 以适配大订单量策略。
OKX_DRIFT_TOLERANCE = 10.0
# OKX fills 覆盖率阈值：低于说明 DB 有大量未在 OKX 找到的成交记录
OKX_COVERAGE_THRESHOLD = 0.95
# 价格匹配容差倍数：理论档位 ± tick_size 内视为匹配
PRICE_TOLERANCE_TICKS = 1.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    ts = _now_iso()
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(CHECK_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # 日志写入失败不影响检测主流程
        pass


def _record_check_event(
    db: Session,
    strategy_instance_id: int | None,
    event_type: str,
    message: str,
    details: dict | None = None,
) -> None:
    """写入检测事件到 StrategyEvent 表，供监控告警链路消费。

    使用独立 Session 写入（避免与主读 Session 的未提交事务竞争锁），
    失败不影响检测主流程。
    strategy_instance_id 为 None 时（全局告警）只写日志不写表，
    因为 strategy_events.strategy_instance_id 字段为 NOT NULL。
    """
    if strategy_instance_id is None:
        # 全局告警：只写日志，不写 StrategyEvent 表（字段约束 NOT NULL）
        _log(f"[{event_type}] {message} details={details or {}}")
        return
    # 独立短命 Session 写入，避免与主读 Session 的锁竞争
    # SQLite database is locked 时重试 3 次（后端运行时常见锁竞争）
    for attempt in range(3):
        write_db = SessionLocal()
        try:
            event = StrategyEvent(
                strategy_instance_id=strategy_instance_id,
                event_type=event_type,
                message=message,
                details=json.dumps(details or {}, ensure_ascii=False, default=str),
                created_at=datetime.now(timezone.utc),
            )
            write_db.add(event)
            write_db.commit()
            return
        except Exception as e:
            write_db.rollback()
            if attempt < 2 and "locked" in str(e).lower():
                time.sleep(0.3 * (attempt + 1))
                continue
            _log(f"检测事件写入失败 event_type={event_type}: {e}")
            return
        finally:
            write_db.close()


def _get_tick_size(symbol: str) -> float:
    """根据 symbol 返回价格 tick_size（SWAP=0.1, 现货=0.01）。

    与 grid_strategy.py L512 对齐。
    """
    return 0.1 if "-SWAP" in symbol else 0.01


def _get_tick_decimals(symbol: str) -> int:
    """根据 symbol 返回价格小数位数（SWAP=1, 现货=2）。

    与 grid_strategy.py L513 对齐。
    """
    return 1 if "-SWAP" in symbol else 2


def _infer_inst_type(symbol: str) -> str:
    """从 symbol 推断 OKX instType（含 -SWAP → SWAP，否则 SPOT）。"""
    if "-SWAP" in symbol:
        return "SWAP"
    return "SPOT"


def _round_tick(px: float, symbol: str) -> float:
    """按 tick_size 取整价格（与 grid_strategy.py L334 一致）。"""
    tick_size = _get_tick_size(symbol)
    tick_decimals = _get_tick_decimals(symbol)
    return round(round(px / tick_size) * tick_size, tick_decimals)


# =============================================================================
# 检查 1：理论挂单 vs 实际挂单
# =============================================================================
async def check_theoretical_vs_actual_orders(db: Session) -> dict:
    """核验每个 running 策略的理论网格档位与 DB orders live 订单的一致性。

    对每个 running 策略：
    1. 从 params 读取 upper_price/lower_price/grid_count/order_qty/symbol
    2. 计算理论网格档位：step=(upper-lower)/(grid_count-1), levels=[lower+i*step]
    3. 取当前价（OKX get_ticker），当前价以下档位挂买单，以上挂卖单
    4. 查询 DB orders 表 status='live' 订单
    5. 对比：缺失/多余/价格不匹配（±tick_size 容差）

    Args:
        db: 数据库 Session

    Returns:
        {
            "check": "theoretical_vs_actual_orders",
            "passed": bool,
            "per_strategy": [{...}]
        }
    """
    running_instances = (
        db.query(StrategyInstance)
        .filter(StrategyInstance.status == "running")
        .all()
    )

    # 按 account_id 缓存 OKXClient（避免重复创建，与 audit_runner 模式一致）
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

    async def _fetch_price(symbol: str, account_id: int,
                           live_orders_for_symbol=None,
                           grid_center: float | None = None) -> float:
        """异步获取当前价（解决原 _fetch_price_sync 在 async 上下文无法调用 OKX REST 的问题）。

        优先级：
        1. market_data_service 缓存（与 grid_strategy.py L588 一致）
        2. OKX REST get_ticker（async，可在 event loop 中调用）
        3. 从 live 订单推断（最高买价 + 最低卖价的中点）
        4. grid_center 网格中心价（网格已校正到当前价附近）
        5. 返回 0.0（降级）
        """
        # 1. 优先用 market_data_service 缓存
        try:
            from services.market_data_service import market_data_service
            cached = market_data_service.get_latest_ticker(symbol)
            if cached and cached.get("last"):
                return float(cached["last"])
        except Exception:
            pass

        # 2. OKX REST get_ticker（async，解决原 sync 版本在 async 上下文失效的问题）
        # 10 秒超时防止 OKX 内部重试阻塞（与 EMA _fetch_closes 超时对齐）
        client = _get_client(account_id)
        if client is not None:
            try:
                ticker = await asyncio.wait_for(
                    client.get_ticker(symbol), timeout=10.0
                )
                if ticker:
                    return float(ticker[0]["last"])
            except asyncio.TimeoutError:
                _log(f"get_ticker 超时(10s) symbol={symbol}，降级到订单推断")
            except Exception as e:
                _log(f"get_ticker 失败 symbol={symbol}: {e}")

        # 3. 从 live 订单推断当前价（最高买价 + 最低卖价的中点）
        if live_orders_for_symbol:
            buy_prices = [float(o.price or 0) for o in live_orders_for_symbol if o.side == "buy" and o.price]
            sell_prices = [float(o.price or 0) for o in live_orders_for_symbol if o.side == "sell" and o.price]
            if buy_prices and sell_prices:
                return (max(buy_prices) + min(sell_prices)) / 2
            elif grid_center is not None:
                # 只有单边订单时，网格中心价更接近真实当前价（网格已校正）
                return grid_center
            elif buy_prices:
                return max(buy_prices)
            elif sell_prices:
                return min(sell_prices)

        # 4. grid_center 兜底
        if grid_center is not None:
            return grid_center
        return 0.0

    per_strategy = []

    for inst in running_instances:
        params = inst.params or {}
        symbol = params.get("symbol") or inst.symbol
        try:
            upper = float(params["upper_price"])
            lower = float(params["lower_price"])
            grid_count = int(params["grid_count"])
        except (KeyError, ValueError, TypeError) as e:
            _log(f"策略#{inst.id} {symbol} 参数缺失或非法: {e}")
            per_strategy.append({
                "strategy_instance_id": inst.id,
                "symbol": symbol,
                "error": f"参数缺失或非法: {e}",
                "matched": False,
            })
            _record_check_event(
                db,
                strategy_instance_id=inst.id,
                event_type="function_check_param_error",
                message=f"策略#{inst.id} {symbol} 网格参数缺失或非法: {e}",
                details={"error": str(e)},
            )
            continue

        # 计算理论网格档位（与 grid_strategy.py L469-470 一致）
        if grid_count <= 1:
            per_strategy.append({
                "strategy_instance_id": inst.id,
                "symbol": symbol,
                "error": f"grid_count<=1: {grid_count}",
                "matched": False,
            })
            continue
        step = (upper - lower) / (grid_count - 1)
        grid_levels = [lower + i * step for i in range(grid_count)]

        tick_size = _get_tick_size(symbol)

        # 先查询 DB live 订单（用于推断当前价和对比）
        live_orders = (
            db.query(Order)
            .filter(Order.strategy_instance_id == inst.id)
            .filter(Order.status == "live")
            .all()
        )

        # 取当前价（仅用于报告显示，不用于买卖单分类）
        grid_center = (upper + lower) / 2
        current_price = await _fetch_price(symbol, inst.account_id, live_orders, grid_center)

        # 理论网格档位：所有档位都应有挂单
        # 注意：网格成交后买单转卖单、卖单转买单是正常行为，不按方向分类
        theoretical_levels = [_round_tick(level, symbol) for level in grid_levels]

        # 按价格索引实际订单（不区分买卖方向）
        actual_prices = {float(o.price or 0): o for o in live_orders if o.price}

        # 价格匹配检查：每个 live 订单找最近的 grid_level
        price_mismatches: list[dict] = []
        for actual_px, order in actual_prices.items():
            if not theoretical_levels:
                price_mismatches.append({
                    "order_id": order.order_id,
                    "side": order.side,
                    "actual": actual_px,
                    "nearest_level": None,
                    "diff": None,
                })
                continue
            nearest = min(theoretical_levels, key=lambda x: abs(x - actual_px))
            diff = abs(actual_px - nearest)
            if diff > tick_size * PRICE_TOLERANCE_TICKS:
                price_mismatches.append({
                    "order_id": order.order_id,
                    "side": order.side,
                    "actual": actual_px,
                    "nearest_level": nearest,
                    "diff": round(diff, 6),
                })

        # 档位覆盖检查：每个 grid_level 是否有 live 订单（缺失 = 补单未完成）
        missing_levels: list[float] = []
        for level in theoretical_levels:
            found = any(abs(actual_px - level) <= tick_size * PRICE_TOLERANCE_TICKS
                        for actual_px in actual_prices)
            if not found:
                missing_levels.append(level)

        # 档位缺失比例超过 20% 视为异常（成交/补单延迟允许少量缺失）
        missing_ratio = len(missing_levels) / len(theoretical_levels) if theoretical_levels else 0
        matched = len(price_mismatches) == 0 and missing_ratio <= 0.2

        per_strategy.append({
            "strategy_instance_id": inst.id,
            "symbol": symbol,
            "current_price": current_price,
            "grid_levels": theoretical_levels,
            "actual_live_orders": len(live_orders),
            "missing_levels": missing_levels,
            "missing_ratio": round(missing_ratio, 3),
            "price_mismatches": price_mismatches,
            "matched": matched,
        })

        if not matched:
            _record_check_event(
                db,
                strategy_instance_id=inst.id,
                event_type="function_check_order_mismatch",
                message=(
                    f"策略#{inst.id} {symbol} 理论挂单与实际不一致: "
                    f"price_mismatch={len(price_mismatches)} "
                    f"missing_levels={len(missing_levels)}/{len(theoretical_levels)} "
                    f"(ratio={round(missing_ratio, 3)})"
                ),
                details={
                    "current_price": current_price,
                    "price_mismatches": price_mismatches[:20],
                    "missing_levels": missing_levels[:20],
                },
            )

    passed = all(p.get("matched", False) for p in per_strategy)
    return {
        "check": "theoretical_vs_actual_orders",
        "passed": passed,
        "per_strategy": per_strategy,
    }


# =============================================================================
# 检查 2：策略检测问题排查
# =============================================================================
# 错误类型 → 修复建议映射（关键字匹配）
_ERROR_SUGGESTIONS = [
    ("refresh_price timeout", "API 限流或网络波动，建议降低 REST 轮询频率（rest_poll_interval 参数）"),
    ("网络异常", "网络异常，建议检查代理/DNS 配置，或降低轮询频率"),
    ("position_mismatch", "仓位对账差异，检查虚拟仓位计算逻辑（pnl_accounting_engine.reconcile_positions）"),
    ("order_place_failed", "下单失败，检查订单参数（price/sz）或 API 权限"),
    ("order_failed", "下单失败，检查订单参数或 API 权限"),
    ("capital_limit_exceeded", "资金不足，检查 investment_amount 上限或追加资金"),
    ("post_only_rejected", "post_only 单被拒（会穿越盘口），策略已自动降级为 limit 重挂"),
    ("order_latency", "补单延迟超阈值，检查网络延迟或调高 latency_threshold"),
    ("margin_risk", "保证金占用率过高，建议降低杠杆或追加保证金"),
]


def _match_suggestion(message: str) -> str:
    """根据错误消息关键字匹配修复建议。"""
    msg_lower = (message or "").lower()
    for keyword, suggestion in _ERROR_SUGGESTIONS:
        if keyword.lower() in msg_lower:
            return suggestion
    return "未知错误类型，建议查看 strategy_events.details 字段定位问题"


def check_strategy_errors(db: Session) -> dict:
    """查询最近 1 小时 strategy_events 表中的 error 事件，分类统计并给修复建议。

    Args:
        db: 数据库 Session

    Returns:
        {
            "check": "strategy_errors",
            "passed": bool,  # 无 error 事件则 True
            "error_count": int,
            "errors_by_type": [{type, count, sample_message, suggestion}],
            "recent_errors": [{strategy_instance_id, message, created_at}]
        }
    """
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    error_events = (
        db.query(StrategyEvent)
        .filter(StrategyEvent.event_type == "error")
        .filter(StrategyEvent.created_at >= one_hour_ago)
        .order_by(StrategyEvent.created_at.desc())
        .all()
    )

    # 按错误类型分类（用消息前缀作为类型，截取冒号前部分）
    type_buckets: dict[str, list[StrategyEvent]] = defaultdict(list)
    for ev in error_events:
        msg = ev.message or ""
        # 取冒号或括号前部分作为类型
        for sep in (":", "（", "("):
            if sep in msg:
                msg = msg.split(sep, 1)[0]
                break
        msg = msg.strip()
        # 截断过长的类型名
        if len(msg) > 60:
            msg = msg[:60]
        type_buckets[msg].append(ev)

    errors_by_type = []
    for err_type, events in type_buckets.items():
        sample = events[0].message or ""
        errors_by_type.append({
            "type": err_type,
            "count": len(events),
            "sample_message": sample[:200],
            "suggestion": _match_suggestion(sample),
        })
    # 按出现次数降序
    errors_by_type.sort(key=lambda x: x["count"], reverse=True)

    recent_errors = [
        {
            "strategy_instance_id": ev.strategy_instance_id,
            "message": (ev.message or "")[:200],
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
        for ev in error_events[:50]  # 限制返回数量
    ]

    passed = len(error_events) == 0

    if not passed:
        # 汇总告警（按错误类型数汇总，避免事件过多）
        _record_check_event(
            db,
            strategy_instance_id=None,
            event_type="function_check_strategy_errors",
            message=f"最近 1 小时检测到 {len(error_events)} 个 error 事件，"
                    f"涉及 {len(errors_by_type)} 种错误类型",
            details={
                "error_count": len(error_events),
                "types": [t["type"] for t in errors_by_type[:10]],
            },
        )

    return {
        "check": "strategy_errors",
        "passed": passed,
        "error_count": len(error_events),
        "errors_by_type": errors_by_type,
        "recent_errors": recent_errors,
    }


# =============================================================================
# 检查 3：实际盈亏核验（OKX 成交记录独立计算）
# =============================================================================
def _compute_fifo_realized_pnl(
    fills: list[dict],
    inst_type: str,
    ct_val: float,
) -> tuple[float, int]:
    """用 FIFO 配对独立计算 realized_pnl。

    匹配 buy/sell 对（FIFO，先买先配）：
    realized = sum((sell_px - buy_px) * matched_qty - proportional_fees)

    Args:
        fills: OKX get_fills 返回的成交记录列表，按时间顺序
        inst_type: "SWAP" 或 "SPOT"
        ct_val: 合约面值（SWAP 才用，SPOT=1.0）

    Returns:
        (realized_pnl, trade_count)
    """
    if not fills:
        return 0.0, 0

    # 解析成交记录，按 ts（毫秒字符串）排序
    parsed = []
    for f in fills:
        try:
            ts = int(f.get("ts", "0"))
        except (TypeError, ValueError):
            ts = 0
        try:
            fill_px = float(f.get("fillPx") or 0)
        except (TypeError, ValueError):
            fill_px = 0.0
        try:
            fill_sz = float(f.get("fillSz") or 0)
        except (TypeError, ValueError):
            fill_sz = 0.0
        try:
            fee = float(f.get("fee") or 0)
        except (TypeError, ValueError):
            fee = 0.0
        # SWAP: fillSz 为合约张数，名义价值需乘 ctVal 转换为币种数量
        qty_base = fill_sz * ct_val if inst_type == "SWAP" else fill_sz
        parsed.append({
            "ts": ts,
            "side": f.get("side", ""),
            "px": fill_px,
            "qty": qty_base,
            "fee": fee,
            "ordId": f.get("ordId", ""),
        })
    parsed.sort(key=lambda x: x["ts"])

    # FIFO 配对
    buy_queue: deque = deque()  # [(remaining_qty, px, fee_per_unit)]
    realized = 0.0
    matched_count = 0

    for f in parsed:
        if f["side"] == "buy":
            if f["qty"] > 0:
                fee_per_unit = abs(f["fee"]) / f["qty"] if f["qty"] > 0 else 0.0
                buy_queue.append([f["qty"], f["px"], fee_per_unit])
        elif f["side"] == "sell":
            remaining = f["qty"]
            sell_px = f["px"]
            sell_fee_per_unit = abs(f["fee"]) / f["qty"] if f["qty"] > 0 else 0.0
            while remaining > 0 and buy_queue:
                buy = buy_queue[0]
                matched_qty = min(remaining, buy[0])
                # realized += (sell_px - buy_px) * matched_qty - 双方手续费
                realized += (sell_px - buy[1]) * matched_qty
                realized -= matched_qty * (buy[2] + sell_fee_per_unit)
                buy[0] -= matched_qty
                remaining -= matched_qty
                matched_count += 1
                if buy[0] <= 1e-12:
                    buy_queue.popleft()

    return round(realized, 6), matched_count


def _compute_db_fifo_realized_pnl(
    orders: list,
    inst_type: str,
    ct_val: float,
    okx_fill_ts_map: dict[str, int] | None = None,
) -> tuple[float, int]:
    """基于 DB Order 表独立计算 realized_pnl（FIFO 配对）。

    与 _compute_fifo_realized_pnl 对称，但数据源是 DB orders 表而非 OKX fills。
    用于数据一致性校验：OKX FIFO vs DB FIFO（不受时序影响，因为两边都是
    同一批已成交订单的快照）。

    排序键优先级：
    1. update_time（OKX uTime 毫秒字符串）— 与 pnl_accounting_engine.py 一致
    2. okx_fill_ts_map[ordId]（OKX fills 的最早 ts 毫秒）— 当 update_time 为空时回补
    3. created_at（下单时间）— 最后兜底

    okx_fill_ts_map 用于回补历史遗留的空 update_time（修复 uTime 传递前落库的订单），
    使 DB FIFO 排序与 OKX fills 真实成交时间顺序一致，避免 okx_vs_db_fifo_diff 假阳性。

    Args:
        orders: DB Order 对象列表（status='filled'）
        inst_type: "SWAP" 或 "SPOT"
        ct_val: 合约面值（SWAP 才用，SPOT=1.0）
        okx_fill_ts_map: ordId → 最早 fill ts（毫秒），用于回补空 update_time

    Returns:
        (realized_pnl, trade_count)
    """
    if not orders:
        return 0.0, 0

    # 解析 DB Order，按成交时间排序
    parsed = []
    for o in orders:
        # 排序键：优先 update_time（OKX uTime 毫秒字符串），
        # 回退 okx_fill_ts_map[ordId]（OKX fills 最早 ts），
        # 再回退 created_at（下单时间）
        sort_key = None
        try:
            if o.update_time and str(o.update_time).isdigit():
                sort_key = (0, int(o.update_time))
        except (ValueError, TypeError):
            pass

        if sort_key is None and okx_fill_ts_map:
            ts_val = okx_fill_ts_map.get(o.order_id or "")
            if ts_val and ts_val > 0:
                sort_key = (0, int(ts_val))

        if sort_key is None:
            sort_key = (1, o.created_at if o.created_at else "")

        # 价格：优先 fill_px（实际成交价），回退 price（挂单价）
        px = float(o.fill_px or 0) if o.fill_px else float(o.price or 0)

        # 数量：优先 actual_qty（= fill_sz × ct_val），回退 fill_sz × ct_val，再回退 quantity
        if o.actual_qty and float(o.actual_qty) > 0:
            qty_base = float(o.actual_qty)
        elif o.fill_sz and float(o.fill_sz) > 0:
            qty_base = float(o.fill_sz) * ct_val if inst_type == "SWAP" else float(o.fill_sz)
        else:
            qty_base = float(o.quantity or 0)

        try:
            fee = float(o.fee or 0)
        except (TypeError, ValueError):
            fee = 0.0

        parsed.append({
            "sort_key": sort_key,
            "side": (o.side or "").lower(),
            "px": px,
            "qty": qty_base,
            "fee": fee,
            "order_id": o.order_id or "",
        })
    parsed.sort(key=lambda x: x["sort_key"])

    # FIFO 配对（与 _compute_fifo_realized_pnl 算法一致）
    buy_queue: deque = deque()  # [(remaining_qty, px, fee_per_unit)]
    realized = 0.0
    matched_count = 0

    for f in parsed:
        if f["side"] == "buy":
            if f["qty"] > 0:
                fee_per_unit = abs(f["fee"]) / f["qty"] if f["qty"] > 0 else 0.0
                buy_queue.append([f["qty"], f["px"], fee_per_unit])
        elif f["side"] == "sell":
            remaining = f["qty"]
            sell_px = f["px"]
            sell_fee_per_unit = abs(f["fee"]) / f["qty"] if f["qty"] > 0 else 0.0
            while remaining > 0 and buy_queue:
                buy = buy_queue[0]
                matched_qty = min(remaining, buy[0])
                realized += (sell_px - buy[1]) * matched_qty
                realized -= matched_qty * (buy[2] + sell_fee_per_unit)
                buy[0] -= matched_qty
                remaining -= matched_qty
                matched_count += 1
                if buy[0] <= 1e-12:
                    buy_queue.popleft()

    return round(realized, 6), matched_count


async def _fetch_all_fills(client: OKXClient, symbol: str, max_pages: int = 100) -> list[dict]:
    """分页拉取 OKX 全部成交记录（近3天 get_fills + 更早 get_fills_history）。

    OKX 分页：记录按 billId 降序返回（最新在前），用 after=最老的 billId 翻页。
    两个端点合并去重（按 billId），保证不遗漏不重复。

    Args:
        client: OKXClient 实例
        symbol: 交易品种
        max_pages: 每个端点最多翻页数（默认 100 页 × 100 = 10000 条）
                   活跃网格策略 12 小时可产生 ~2000 笔成交，3 天 ~12000 笔，
                   20 页（2000 条）会触碰上限导致覆盖率误判，提升到 100 页。

    Returns:
        合并去重后的全部 fills 列表
    """
    inst_type = _infer_inst_type(symbol)
    seen_bill_ids: set[str] = set()
    all_fills: list[dict] = []
    fetch_error = False  # 跟踪是否有 API 调用失败

    # 1. 拉取近 3 天成交（get_fills）
    after_cursor = None
    for _ in range(max_pages):
        try:
            page = await client.trade.get_fills(
                instId=symbol, after=after_cursor, limit="100"
            )
        except Exception as e:
            _log(f"get_fills 分页拉取失败 symbol={symbol} after={after_cursor}: {e}")
            fetch_error = True
            break
        if not page:
            break
        for f in page:
            bill_id = f.get("billId") or f"{f.get('ordId','')}_{f.get('ts','')}_{f.get('fillPx','')}"
            if bill_id not in seen_bill_ids:
                seen_bill_ids.add(bill_id)
                all_fills.append(f)
        # 翻页：用本页最老（最后一条）的 billId 作为 after
        after_cursor = page[-1].get("billId")
        # 不足一页说明已到底
        if len(page) < 100 or not after_cursor:
            break

    # 2. 拉取更早的成交（get_fills_history，最多7天）
    after_cursor = None
    for _ in range(max_pages):
        try:
            page = await client.trade.get_fills_history(
                instType=inst_type, instId=symbol, after=after_cursor, limit="100"
            )
        except Exception as e:
            _log(f"get_fills_history 分页拉取失败 symbol={symbol} after={after_cursor}: {e}")
            fetch_error = True
            break
        if not page:
            break
        for f in page:
            bill_id = f.get("billId") or f"{f.get('ordId','')}_{f.get('ts','')}_{f.get('fillPx','')}"
            if bill_id not in seen_bill_ids:
                seen_bill_ids.add(bill_id)
                all_fills.append(f)
        after_cursor = page[-1].get("billId")
        if len(page) < 100 or not after_cursor:
            break

    # 全部 API 调用失败且无数据时抛出，让调用方记录 function_check_okx_api_error 事件
    if fetch_error and not all_fills:
        raise RuntimeError(f"OKX API 拉取成交记录全部失败 symbol={symbol}")

    return all_fills


async def check_actual_pnl(db: Session) -> dict:
    """从 OKX 拉取真实成交记录，独立计算 realized_pnl 并与 DB 比对。

    对每个 running 策略：
    1. 从 OKX API 分页拉取全部真实成交记录（get_fills + get_fills_history）
    2. 独立计算 OKX FIFO realized_pnl：FIFO 配对 buy/sell（单笔成交粒度）
    3. 基于 DB orders 表独立计算 DB FIFO realized_pnl（聚合订单粒度）
    4. 主判定 1：DB FIFO vs PnlRecord（核算引擎正确性，容差 PNL_DIFF_TOLERANCE）
    5. 主判定 2：OKX FIFO vs DB FIFO（DB 与 OKX 数据同步，容差 OKX_DRIFT_TOLERANCE）
    6. 主判定 3：fills_coverage（OKX 覆盖 DB 已成交订单比例，阈值 OKX_COVERAGE_THRESHOLD）
    7. 计算总盈亏（所有策略之和）

    三层主判定逻辑（全部通过才算 matched）：
    - accounting_diff：DB FIFO vs PnlRecord。两者数据源相同（DB orders），
      算法相同（FIFO），若一致则核算引擎正确。不受时序影响。
    - okx_vs_db_fifo_diff：OKX FIFO vs DB FIFO。验证 DB orders 与 OKX 真实成交一致。
      部分成交聚合有少量天然差异，但大幅偏离说明 DB 与 OKX 不同步。
    - fills_coverage：OKX fills 覆盖 DB filled orders 的比例。低于阈值说明
      DB 有大量未在 OKX 找到的成交记录（幽灵订单或 API 分页丢失）。

    OKX 拉取失败时跳过主判定 2/3（已有 function_check_okx_api_error 事件告警）。

    Args:
        db: 数据库 Session

    Returns:
        {
            "check": "actual_pnl",
            "passed": bool,
            "per_strategy": [{
                "strategy_instance_id": int,
                "symbol": str,
                "okx_realized_pnl": float,         # OKX fills FIFO（单笔粒度）
                "db_fifo_realized_pnl": float,     # DB orders FIFO（聚合粒度）
                "db_realized_pnl": float,          # PnlRecord（核算引擎输出）
                "accounting_diff": float,          # 主判定 1：DB FIFO vs PnlRecord
                "okx_vs_db_fifo_diff": float,      # 主判定 2：OKX vs DB FIFO
                "pnl_record_diff": float,          # 信息项：OKX vs PnlRecord
                "diff": float,                     # 最严重差异（向后兼容）
                "okx_drift_match": bool,           # 主判定 2 结果
                "coverage_match": bool,            # 主判定 3 结果
                "okx_fetch_succeeded": bool,       # OKX 拉取是否成功
                "matched": bool,
                "trade_count": int,
                "fills_coverage": float
            }],
            "total_okx_pnl": float,
            "total_db_fifo_pnl": float,
            "total_db_pnl": float,
            "total_diff": float                    # OKX vs DB PnlRecord 真实差距
        }
    """
    running_instances = (
        db.query(StrategyInstance)
        .filter(StrategyInstance.status == "running")
        .all()
    )

    # 按 account_id 缓存 OKXClient
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

    # (account_id, symbol) -> 拉取过的 fills（去重避免限流）
    cached_fills: dict[tuple[int, str], list[dict]] = {}
    # (account_id, symbol) -> OKX 拉取是否成功（失败时跳过外部核验）
    fetch_succeeded: dict[tuple[int, str], bool] = {}

    per_strategy = []
    total_okx_pnl = 0.0
    total_db_fifo_pnl = 0.0
    total_db_pnl = 0.0

    for inst in running_instances:
        symbol = inst.params.get("symbol") if inst.params else None
        symbol = symbol or inst.symbol

        # 拉取 OKX 全部成交记录（按 account+symbol 去重）
        pair = (inst.account_id, symbol)
        if pair not in cached_fills:
            try:
                client = _get_client(inst.account_id)
                if client is None:
                    _log(f"账户 {inst.account_id} 不存在，跳过 PnL 核验 symbol={symbol}")
                    cached_fills[pair] = []
                    fetch_succeeded[pair] = False
                else:
                    # 60 秒超时防止 OKX API 阻塞（分页拉取数千条 fills 正常 20-40s）
                    try:
                        fills = await asyncio.wait_for(
                            _fetch_all_fills(client, symbol), timeout=60.0
                        )
                    except asyncio.TimeoutError:
                        raise RuntimeError(
                            f"OKX fills 拉取超时(60s) symbol={symbol}，"
                            f"可能 API 限流或代理阻塞"
                        )
                    cached_fills[pair] = fills or []
                    fetch_succeeded[pair] = True
                    _log(f"OKX fills 拉取完成 account={inst.account_id} symbol={symbol} count={len(fills)}")
            except Exception as e:
                _log(f"OKX fills 拉取失败 account={inst.account_id} symbol={symbol}: {e}")
                _record_check_event(
                    db,
                    strategy_instance_id=inst.id,
                    event_type="function_check_okx_api_error",
                    message=f"OKX 成交记录查询失败 symbol={symbol}: {e}",
                    details={"error": str(e)},
                )
                cached_fills[pair] = []
                fetch_succeeded[pair] = False

        fills = cached_fills[pair]

        # 匹配 ordId 到 DB order，过滤出属于本策略的 fills
        strategy_order_ids: set[str] = set()
        db_orders = (
            db.query(Order)
            .filter(Order.strategy_instance_id == inst.id)
            .filter(Order.order_id.isnot(None))
            .filter(Order.order_id != "")
            .all()
        )
        for o in db_orders:
            strategy_order_ids.add(o.order_id)

        strategy_fills = [
            f for f in fills
            if f.get("ordId") in strategy_order_ids
        ]

        # 构建 ordId → 最早 fill ts 映射，用于回补 DB 空 update_time
        # 背景：uTime 传递修复前落库的订单 update_time 全为空字符串，导致 DB FIFO
        # 排序回退到 created_at（下单时间），与 OKX fills 真实成交时间顺序不一致，
        # 产生 okx_vs_db_fifo_diff 假阳性。用 OKX fills ts 回补使排序一致。
        okx_fill_ts_map: dict[str, int] = {}
        for f in strategy_fills:
            ord_id = f.get("ordId", "")
            try:
                ts_val = int(f.get("ts", "0"))
            except (TypeError, ValueError):
                continue
            if not ord_id or ts_val <= 0:
                continue
            # 同一 ordId 可能有多次部分成交，取最早的 ts 作为成交时间
            prev = okx_fill_ts_map.get(ord_id)
            if prev is None or ts_val < prev:
                okx_fill_ts_map[ord_id] = ts_val

        # 矫正性回补：用 OKX fills ts 回填 DB Order.update_time（仅当 update_time 为空时）
        # 这是针对 uTime 传递修复前历史遗留数据的矫正动作，非业务数据修改。
        # 回补后 PnlAccountingEngine.recompute 能用正确的成交时间排序，使 PnlRecord
        # 与 OKX FIFO / DB FIFO 三方一致。
        backfill_count = 0
        if okx_fill_ts_map:
            try:
                for o in db_orders:
                    if o.status != "filled":
                        continue
                    # update_time 为空或非数字时回补
                    cur = o.update_time
                    if cur and str(cur).isdigit():
                        continue
                    ts_val = okx_fill_ts_map.get(o.order_id or "")
                    if ts_val and ts_val > 0:
                        o.update_time = str(ts_val)
                        backfill_count += 1
                if backfill_count > 0:
                    db.commit()
                    _log(
                        f"update_time 矫正回补 inst={inst.id} symbol={symbol} "
                        f"count={backfill_count}"
                    )
            except Exception as e:
                db.rollback()
                _log(f"update_time 回补失败 inst={inst.id}: {e}")

        # 触发全量 recompute（非 incremental_update），确保 PnlRecord 用矫正后的
        # update_time 重新核算。incremental_update 只处理 pnl_accounted=False 的新订单，
        # 不会重算历史订单；recompute 扫描所有 filled 订单重新计算。
        try:
            client = _get_client(inst.account_id)
            await pnl_accounting_engine.recompute(inst.id, client)
        except Exception as e:
            _log(f"recompute 失败 inst={inst.id}: {e}")

        # 读取 DB 最新 PnlRecord（recompute 后为最新）
        latest = (
            db.query(PnlRecord)
            .filter(PnlRecord.strategy_instance_id == inst.id)
            .order_by(PnlRecord.recorded_at.desc())
            .first()
        )
        db_realized = float(latest.realized_pnl or 0) if latest else 0.0

        # 用 FIFO 独立计算 realized_pnl（OKX fills 口径）
        inst_type = _infer_inst_type(symbol)
        ct_val = instrument_cache.get_ct_val(symbol)
        okx_realized, trade_count = _compute_fifo_realized_pnl(
            strategy_fills, inst_type, ct_val,
        )

        # 基于 DB orders 表独立计算 realized_pnl（DB FIFO 口径）
        # 数据一致性校验：OKX FIFO vs DB FIFO（不受时序影响，两边是同一批已成交订单快照）
        # 重新查询 filled orders：backfill commit + recompute 后 db_orders 对象已过期，
        # 重新查询获取矫正后的 update_time，避免 N+1 lazy reload
        db_filled_orders = (
            db.query(Order)
            .filter(Order.strategy_instance_id == inst.id)
            .filter(Order.status == "filled")
            .filter(Order.order_id.isnot(None))
            .filter(Order.order_id != "")
            .all()
        )
        db_fifo_realized, db_trade_count = _compute_db_fifo_realized_pnl(
            db_filled_orders, inst_type, ct_val, okx_fill_ts_map,
        )

        # 覆盖率：OKX fills 覆盖的 DB 订单比例
        db_filled_count = len(db_filled_orders)
        okx_covered_count = len(set(f.get("ordId") for f in strategy_fills))
        fills_coverage = okx_covered_count / db_filled_count if db_filled_count > 0 else 1.0

        # 主判定 1：DB FIFO vs PnlRecord（核算引擎正确性）
        # DB FIFO 用同一批 DB orders 独立计算 realized_pnl，与 PnlAccountingEngine 的输出比对。
        # 若一致，说明核算引擎正确地从 DB orders 计算了盈亏。
        accounting_diff = abs(db_fifo_realized - db_realized)
        accounting_match = accounting_diff <= PNL_DIFF_TOLERANCE

        # 主判定 2：OKX FIFO vs DB FIFO（DB 与 OKX 数据同步校验）
        # OKX fills 按单笔成交记录计算，DB orders 按聚合订单（加权均价）计算，
        # 部分成交时有少量天然差异，但大幅偏离说明 DB 与 OKX 真实成交不同步。
        okx_vs_db_fifo_diff = abs(okx_realized - db_fifo_realized)

        # 信息项：OKX FIFO vs PnlRecord（受时序 + 部分成交聚合双重影响）
        pnl_record_diff = abs(okx_realized - db_realized)

        # 主判定 3：fills_coverage（OKX 覆盖 DB 已成交订单比例）
        # 低于阈值说明 DB 有大量未在 OKX 找到的成交记录（幽灵订单或 API 分页丢失）

        # OKX 拉取成功且有 DB 成交时才执行外部核验（主判定 2/3）
        okx_fetched = fetch_succeeded.get(pair, True)
        if okx_fetched and db_filled_count > 0:
            okx_drift_match = okx_vs_db_fifo_diff <= OKX_DRIFT_TOLERANCE
            coverage_match = fills_coverage >= OKX_COVERAGE_THRESHOLD
        else:
            # OKX 拉取失败或无 DB 成交 → 跳过外部核验
            # （API 失败已记录 function_check_okx_api_error 事件，不重复告警）
            okx_drift_match = True
            coverage_match = True

        # 三层主判定全部通过才算 matched
        matched = accounting_match and okx_drift_match and coverage_match

        # diff = 最严重差异（向后兼容 + 反映真实问题）
        worst_diff = max(accounting_diff, okx_vs_db_fifo_diff if okx_fetched else 0.0)

        # 收集失败原因
        fail_reasons = []
        if not accounting_match:
            fail_reasons.append(
                f"核算引擎校验失败(db_fifo={db_fifo_realized} pnl_record={db_realized} "
                f"diff={accounting_diff:.6f})"
            )
        if not okx_drift_match:
            fail_reasons.append(
                f"OKX数据不同步(okx_fifo={okx_realized} db_fifo={db_fifo_realized} "
                f"drift={okx_vs_db_fifo_diff:.6f})"
            )
        if not coverage_match:
            fail_reasons.append(
                f"覆盖率过低(coverage={fills_coverage:.3f} okx_fills={okx_covered_count} "
                f"db_filled={db_filled_count})"
            )

        per_strategy.append({
            "strategy_instance_id": inst.id,
            "symbol": symbol,
            "okx_realized_pnl": okx_realized,
            "db_fifo_realized_pnl": db_fifo_realized,
            "db_realized_pnl": round(db_realized, 6),  # PnlRecord 口径
            "accounting_diff": round(accounting_diff, 6),  # 主判定 1：DB FIFO vs PnlRecord
            "okx_vs_db_fifo_diff": round(okx_vs_db_fifo_diff, 6),  # 主判定 2：OKX vs DB FIFO
            "pnl_record_diff": round(pnl_record_diff, 6),  # 信息项：OKX vs PnlRecord
            "diff": round(worst_diff, 6),  # 最严重差异（向后兼容）
            "okx_drift_match": okx_drift_match,
            "coverage_match": coverage_match,
            "okx_fetch_succeeded": okx_fetched,
            "okx_verification_skipped": not okx_fetched,
            "warning": "OKX fills 拉取失败,外部核验(OKX vs DB)已跳过,仅通过内部核算一致性判定" if not okx_fetched else None,
            "matched": matched,
            "trade_count": trade_count,
            "db_trade_count": db_trade_count,
            "fills_coverage": round(fills_coverage, 3),
            "okx_fills_count": okx_covered_count,
            "db_filled_count": db_filled_count,
        })

        if not matched:
            _record_check_event(
                db,
                strategy_instance_id=inst.id,
                event_type="function_check_pnl_mismatch",
                message=(
                    f"策略#{inst.id} {symbol} 盈亏核验失败: " + "; ".join(fail_reasons)
                ),
                details={
                    "okx_realized_pnl": okx_realized,
                    "db_fifo_realized_pnl": db_fifo_realized,
                    "db_realized_pnl": db_realized,
                    "accounting_diff": accounting_diff,
                    "okx_vs_db_fifo_diff": okx_vs_db_fifo_diff,
                    "pnl_record_diff": pnl_record_diff,
                    "fills_coverage": fills_coverage,
                    "okx_drift_match": okx_drift_match,
                    "coverage_match": coverage_match,
                    "okx_fetch_succeeded": okx_fetched,
                    "trade_count": trade_count,
                    "db_trade_count": db_trade_count,
                    "fail_reasons": fail_reasons,
                },
            )

        total_okx_pnl += okx_realized
        total_db_fifo_pnl += db_fifo_realized
        total_db_pnl += db_realized

    # total_diff = OKX vs DB PnlRecord 真实差距（反映 DB 与 OKX 的整体偏差）
    total_diff = abs(total_okx_pnl - total_db_pnl)
    passed = all(p.get("matched", False) for p in per_strategy)
    # 检查是否有策略跳过了 OKX 外部核验
    skipped_strategies = [p["strategy_instance_id"] for p in per_strategy if p.get("okx_verification_skipped")]
    warning = None
    if skipped_strategies:
        warning = f"策略 {skipped_strategies} 的 OKX fills 拉取失败,外部核验已跳过,actual_pnl 通过仅基于内部核算一致性"

    return {
        "check": "actual_pnl",
        "passed": passed,
        "per_strategy": per_strategy,
        "total_okx_pnl": round(total_okx_pnl, 6),
        "total_db_fifo_pnl": round(total_db_fifo_pnl, 6),
        "total_db_pnl": round(total_db_pnl, 6),  # PnlRecord 口径
        "total_diff": round(total_diff, 6),  # OKX vs DB PnlRecord
        "tolerance": PNL_DIFF_TOLERANCE,
        "okx_drift_tolerance": OKX_DRIFT_TOLERANCE,
        "okx_coverage_threshold": OKX_COVERAGE_THRESHOLD,
        "warning": warning,
    }


# =============================================================================
# 主流程
# =============================================================================
async def run_function_check() -> dict:
    """执行一次完整的功能检测，返回检测报告 dict。

    步骤：
    1. 执行三项检查（理论挂单 / 错误事件 / 实际盈亏）
    2. 生成报告到 function_check_report_{timestamp}.json 和 function_check_latest.json
    3. 异常写入 strategy_events 表（event_type=function_check_*）
    4. 返回报告
    """
    start_ts = datetime.now(timezone.utc)
    _log("=" * 60)
    _log(f"开始功能检测 run_function_check @ {start_ts.isoformat()}")

    db = SessionLocal()
    report = {
        "check_type": "scheduled_function_check",
        "started_at": start_ts.isoformat(),
        "version": "1.0",
        "checks": {},
    }

    try:
        # 检查 1：理论挂单 vs 实际挂单（async，可直接调用 OKX get_ticker）
        _log("检查 1/3：理论挂单 vs 实际挂单...")
        try:
            order_check = await check_theoretical_vs_actual_orders(db)
        except Exception as e:
            _log(f"检查 1 异常: {e}")
            order_check = {
                "check": "theoretical_vs_actual_orders",
                "passed": False,
                "error": str(e),
                "per_strategy": [],
            }
            _record_check_event(
                db,
                strategy_instance_id=None,
                event_type="function_check_error",
                message=f"理论挂单检查异常: {e}",
                details={"check": "theoretical_vs_actual_orders", "error": str(e)},
            )
        report["checks"]["theoretical_vs_actual_orders"] = order_check
        _log(
            f"  完成: passed={order_check['passed']} "
            f"strategies={len(order_check.get('per_strategy', []))}"
        )

        # 检查 2：策略检测问题排查（同步）
        _log("检查 2/3：策略检测问题排查...")
        try:
            error_check = check_strategy_errors(db)
        except Exception as e:
            _log(f"检查 2 异常: {e}")
            error_check = {
                "check": "strategy_errors",
                "passed": False,
                "error": str(e),
                "error_count": 0,
                "errors_by_type": [],
                "recent_errors": [],
            }
        report["checks"]["strategy_errors"] = error_check
        _log(
            f"  完成: passed={error_check['passed']} "
            f"errors={error_check['error_count']}"
        )

        # 检查 3：实际盈亏核验（异步，调用 OKX get_fills）
        _log("检查 3/3：实际盈亏核验...")
        try:
            pnl_check = await check_actual_pnl(db)
        except Exception as e:
            _log(f"检查 3 异常: {e}")
            pnl_check = {
                "check": "actual_pnl",
                "passed": False,
                "error": str(e),
                "per_strategy": [],
                "total_okx_pnl": 0.0,
                "total_db_pnl": 0.0,
                "total_diff": 0.0,
            }
            _record_check_event(
                db,
                strategy_instance_id=None,
                event_type="function_check_error",
                message=f"实际盈亏检查异常: {e}",
                details={"check": "actual_pnl", "error": str(e)},
            )
        report["checks"]["actual_pnl"] = pnl_check
        _log(
            f"  完成: passed={pnl_check['passed']} "
            f"total_okx_pnl={pnl_check.get('total_okx_pnl', 0)} "
            f"total_db_pnl={pnl_check.get('total_db_pnl', 0)} "
            f"total_diff={pnl_check.get('total_diff', 0)}"
        )

    finally:
        db.close()

    end_ts = datetime.now(timezone.utc)
    duration = (end_ts - start_ts).total_seconds()
    # 总体通过：三项全部通过
    overall_passed = all(c.get("passed", False) for c in report["checks"].values())
    report["finished_at"] = end_ts.isoformat()
    report["duration_seconds"] = round(duration, 3)
    report["overall_passed"] = overall_passed

    # 写入检测报告文件
    timestamp_str = start_ts.strftime("%Y%m%d_%H%M%S")
    report_file = REPORT_DIR / f"function_check_report_{timestamp_str}.json"
    try:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        _log(f"检测报告写入失败: {e}")

    # 覆盖式写入 latest 文件（便于面板读取最新状态）
    try:
        with open(LATEST_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        _log(f"latest 检测文件写入失败: {e}")

    _log(
        f"功能检测完成: overall_passed={overall_passed} "
        f"duration={duration:.3f}s "
        f"report={report_file.name}"
    )
    _log("=" * 60)
    return report


def main() -> None:
    """同步入口，供 Schedule 定时任务调用。"""
    asyncio.run(run_function_check())


if __name__ == "__main__":
    main()
