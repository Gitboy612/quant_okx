"""PnL 归因分析服务。

按币种 / 策略类型 / 时间段聚合盈亏，支持下钻查看订单明细。

数据来源说明（三维度统一基于 PnlRecord，避免口径打架）：
- by_symbol：查询 StrategyInstance（按 symbol 分组）+ 各实例时间窗口内最新 PnlRecord，
  聚合 realized_pnl / unrealized_pnl / net_position / total_fee / order_count；
  avg_buy_price 按 |net_position| 加权平均；时间过滤字段为 PnlRecord.recorded_at。
- by_strategy_type / by_period：同样以 PnlRecord 为 realized/unrealized 口径，
  额外查询 Order 仅用于交易次数 / 胜率 / 平均收益率等订单维度指标。
- PnlRecord.realized_pnl 为按策略实例累计值，三维度均取累计口径，保证一致。
- StrategyInstance 通过 template_id 关联 StrategyTemplate.strategy_type。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from models.order import Order
from models.pnl import PnlRecord
from models.strategy import StrategyInstance, StrategyTemplate


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """解析 ISO 8601 字符串为 datetime，兼容带 Z 结尾。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _order_qty(o: Order) -> float:
    """订单实际成交数量，优先 fill_sz，回退 filled_quantity。"""
    if o.fill_sz is not None:
        return float(o.fill_sz)
    return float(o.filled_quantity or 0)


def _order_px(o: Order) -> float:
    """订单成交价，优先 fill_px，回退委托价。"""
    if o.fill_px is not None:
        return float(o.fill_px)
    return float(o.price or 0)


class AttributionService:
    """PnL 归因分析服务。所有方法接收外部注入的 db: Session。"""

    def get_attribution_by_symbol(
        self,
        db: Session,
        account_id: int,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """按币种聚合盈亏（基于 PnlRecord，与 by_strategy_type / by_period 口径一致）。

        流程：
        1. 查询 StrategyInstance（account_id + status in [running, paused, stopped]）。
        2. 按 symbol 分组策略实例。
        3. 查询时间窗口内的 PnlRecord（按 recorded_at 过滤），每个实例取最新一条。
        4. 聚合各实例 latest PnlRecord：
           - realized_pnl / unrealized_pnl / net_position / total_fee / order_count 求和；
           - avg_buy_price 按 |net_position| 加权平均（全 0 时取简单平均或 0）。
        5. realized_pnl 取累计口径（latest.realized_pnl 求和），与 by_strategy_type 一致。
        """
        start_dt = _parse_dt(start_date)
        end_dt = _parse_dt(end_date)

        # 1. 查询该账户下所有活跃/已停止的策略实例
        instances = (
            db.query(StrategyInstance)
            .filter(StrategyInstance.account_id == account_id)
            .filter(StrategyInstance.status.in_(["running", "paused", "stopped"]))
            .all()
        )
        if not instances:
            return []

        # 2. 查询时间窗口内的 PnlRecord（按 recorded_at 过滤，与 by_strategy_type 一致）
        pnl_q = db.query(PnlRecord).filter(PnlRecord.account_id == account_id)
        if start_dt:
            pnl_q = pnl_q.filter(PnlRecord.recorded_at >= start_dt)
        if end_dt:
            pnl_q = pnl_q.filter(PnlRecord.recorded_at <= end_dt)
        pnl_records = pnl_q.all()

        # 3. 每个策略实例在时间窗口内的最新 PnL 快照（与 by_strategy_type 同算法）
        series_by_inst: dict[int, list[PnlRecord]] = defaultdict(list)
        for r in pnl_records:
            sid = r.strategy_instance_id
            if sid is None:
                continue
            series_by_inst[sid].append(r)
        latest_by_inst: dict[int, PnlRecord] = {}
        for sid, recs in series_by_inst.items():
            recs.sort(key=lambda x: x.recorded_at)
            latest_by_inst[sid] = recs[-1]

        # 4. 按 symbol 分组策略实例
        instances_by_symbol: dict[str, list[StrategyInstance]] = defaultdict(list)
        for inst in instances:
            instances_by_symbol[inst.symbol].append(inst)

        # 5. 对每个 symbol 聚合各实例的 latest PnlRecord
        rows: list[dict] = []
        total_abs_pnl = 0.0
        for symbol, insts in instances_by_symbol.items():
            realized = 0.0
            unrealized = 0.0
            net_position = 0.0
            total_fee = 0.0
            order_count = 0
            # avg_buy_price 加权平均用
            weighted_price_sum = 0.0
            weight_sum = 0.0
            simple_price_sum = 0.0
            price_count = 0
            has_pnl = False

            for inst in insts:
                latest = latest_by_inst.get(inst.id)
                if not latest:
                    continue
                has_pnl = True
                realized += float(latest.realized_pnl or 0)
                unrealized += float(latest.unrealized_pnl or 0)
                net_position += float(latest.net_position or 0)
                total_fee += float(latest.total_fee or 0)
                order_count += int(latest.order_count or 0)

                price = float(latest.avg_buy_price or 0)
                weight = abs(float(latest.net_position or 0))
                weighted_price_sum += price * weight
                weight_sum += weight
                simple_price_sum += price
                price_count += 1

            # 该 symbol 下无任何 PnL 记录则跳过
            if not has_pnl:
                continue

            # avg_buy_price 按 |net_position| 加权平均；全 0 时取简单平均或 0
            if weight_sum > 0:
                avg_buy_price = weighted_price_sum / weight_sum
            elif price_count > 0:
                avg_buy_price = simple_price_sum / price_count
            else:
                avg_buy_price = 0.0

            rows.append({
                "symbol": symbol,
                "realized_pnl": round(realized, 4),
                "unrealized_pnl": round(unrealized, 4),
                "net_position": round(net_position, 6),
                "avg_buy_price": round(avg_buy_price, 6),
                "total_fee": round(total_fee, 6),
                "order_count": order_count,
            })
            total_abs_pnl += abs(realized)

        # 各 symbol 盈亏占比（相对总绝对盈亏归一化）
        for row in rows:
            row["pnl_share"] = (
                round(abs(row["realized_pnl"]) / total_abs_pnl * 100, 4)
                if total_abs_pnl
                else 0.0
            )

        rows.sort(key=lambda x: x["realized_pnl"], reverse=True)
        return rows

    def get_attribution_by_strategy_type(
        self,
        db: Session,
        account_id: int,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """按策略类型聚合盈亏。

        关联 strategy_instances -> strategy_templates 获取 strategy_type，
        按 strategy_type 分组计算 realized_pnl / unrealized_pnl / 交易次数 / 胜率 /
        平均收益率 / 最大回撤。
        """
        start_dt = _parse_dt(start_date)
        end_dt = _parse_dt(end_date)

        instances = (
            db.query(StrategyInstance)
            .filter(StrategyInstance.account_id == account_id)
            .all()
        )
        if not instances:
            return []

        template_ids = {i.template_id for i in instances}
        templates = (
            db.query(StrategyTemplate)
            .filter(StrategyTemplate.id.in_(template_ids))
            .all()
        )
        type_map = {t.id: (t.strategy_type or "unknown") for t in templates}
        inst_type_map = {i.id: type_map.get(i.template_id, "unknown") for i in instances}

        # PnL 记录（用于 realized/unrealized/max_drawdown）
        pnl_q = db.query(PnlRecord).filter(PnlRecord.account_id == account_id)
        if start_dt:
            pnl_q = pnl_q.filter(PnlRecord.recorded_at >= start_dt)
        if end_dt:
            pnl_q = pnl_q.filter(PnlRecord.recorded_at <= end_dt)
        pnl_records = pnl_q.all()

        # 每个策略实例在时间范围内的最新 PnL 快照
        latest_by_inst: dict[int, PnlRecord] = {}
        series_by_inst: dict[int, list[PnlRecord]] = defaultdict(list)
        for r in pnl_records:
            sid = r.strategy_instance_id
            if sid is None:
                continue
            series_by_inst[sid].append(r)
        for sid, recs in series_by_inst.items():
            recs.sort(key=lambda x: x.recorded_at)
            latest_by_inst[sid] = recs[-1]

        # 订单（用于交易次数 / 胜率 / 平均收益率）
        order_q = db.query(Order).filter(Order.account_id == account_id)
        if start_dt:
            order_q = order_q.filter(Order.created_at >= start_dt)
        if end_dt:
            order_q = order_q.filter(Order.created_at <= end_dt)
        orders = order_q.all()
        orders_by_inst: dict[int, list[Order]] = defaultdict(list)
        for o in orders:
            if o.strategy_instance_id is not None:
                orders_by_inst[o.strategy_instance_id].append(o)

        # 按策略类型聚合
        agg: dict[str, dict] = defaultdict(lambda: {
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "trade_count": 0,
            "win_trades": 0,
            "sell_trades": 0,
            "total_notional": 0.0,
            "max_drawdown": 0.0,
        })

        for inst in instances:
            stype = inst_type_map.get(inst.id, "unknown")
            bucket = agg[stype]

            latest = latest_by_inst.get(inst.id)
            if latest:
                bucket["realized_pnl"] += float(latest.realized_pnl or 0)
                bucket["unrealized_pnl"] += float(latest.unrealized_pnl or 0)

            # 最大回撤（基于该实例 realized_pnl 累计曲线）
            recs = series_by_inst.get(inst.id, [])
            if recs:
                inst_mdd = _max_drawdown([float(r.realized_pnl or 0) for r in recs])
                if inst_mdd > bucket["max_drawdown"]:
                    bucket["max_drawdown"] = inst_mdd

            inst_orders = orders_by_inst.get(inst.id, [])
            filled = [o for o in inst_orders if (o.status or "") == "filled"]
            buys = [o for o in filled if (o.side or "").lower() == "buy"]
            sells = [o for o in filled if (o.side or "").lower() == "sell"]
            total_buy_qty = sum(_order_qty(o) for o in buys)
            total_buy_notional = sum(_order_px(o) * _order_qty(o) for o in buys)
            avg_buy_price = (total_buy_notional / total_buy_qty) if total_buy_qty else 0.0
            wins = 0
            for s in sells:
                if avg_buy_price > 0 and _order_px(s) > avg_buy_price:
                    wins += 1
            bucket["trade_count"] += len(filled)
            bucket["win_trades"] += wins
            bucket["sell_trades"] += len(sells)
            bucket["total_notional"] += total_buy_notional

        result = []
        for stype, b in agg.items():
            win_rate = (b["win_trades"] / b["sell_trades"]) if b["sell_trades"] else 0.0
            avg_return = (b["realized_pnl"] / b["total_notional"] * 100) if b["total_notional"] else 0.0
            result.append({
                "strategy_type": stype,
                "realized_pnl": round(b["realized_pnl"], 4),
                "unrealized_pnl": round(b["unrealized_pnl"], 4),
                "trade_count": b["trade_count"],
                "win_rate": round(win_rate, 4),
                "avg_return": round(avg_return, 4),
                "max_drawdown": round(b["max_drawdown"], 4),
            })
        result.sort(key=lambda x: x["realized_pnl"], reverse=True)
        return result

    def get_attribution_by_period(
        self,
        db: Session,
        account_id: int,
        start_date: str,
        end_date: str,
        period: str = "daily",
    ) -> list[dict]:
        """按时间段聚合盈亏。

        period: "daily" | "weekly" | "monthly"
        返回每个周期桶的 realized_pnl（区间增量）/ unrealized_pnl（期末值）/
        total_pnl / trade_count。
        """
        start_dt = _parse_dt(start_date)
        end_dt = _parse_dt(end_date)
        if period not in ("daily", "weekly", "monthly"):
            period = "daily"

        pnl_q = db.query(PnlRecord).filter(PnlRecord.account_id == account_id)
        if start_dt:
            pnl_q = pnl_q.filter(PnlRecord.recorded_at >= start_dt)
        if end_dt:
            pnl_q = pnl_q.filter(PnlRecord.recorded_at <= end_dt)
        pnl_records = pnl_q.all()

        order_q = db.query(Order).filter(Order.account_id == account_id)
        if start_dt:
            order_q = order_q.filter(Order.created_at >= start_dt)
        if end_dt:
            order_q = order_q.filter(Order.created_at <= end_dt)
        orders = order_q.all()

        # 按策略实例分组 PnL 记录并按时间排序
        series_by_inst: dict[int, list[PnlRecord]] = defaultdict(list)
        for r in pnl_records:
            if r.strategy_instance_id is not None:
                series_by_inst[r.strategy_instance_id].append(r)
        for sid in series_by_inst:
            series_by_inst[sid].sort(key=lambda x: x.recorded_at)

        # 周期桶
        buckets: dict[str, dict] = defaultdict(lambda: {
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "trade_count": 0,
            "_period_start": None,
        })

        def _bucket_key(dt: datetime) -> tuple[str, datetime]:
            if period == "daily":
                start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
                return start.strftime("%Y-%m-%d"), start
            if period == "weekly":
                # 周一作为周起点
                start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
                start = start - timedelta(days=start.weekday())
                return start.strftime("%Y-%m-%d"), start
            # monthly
            start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return start.strftime("%Y-%m"), start

        # 每个实例按时间排序，逐条计算 realized 增量并归入对应周期桶。
        # 第一条记录作为基线（增量 0），后续记录增量 = cur - prev。
        # 每个桶的 unrealized 取该实例在该桶最后一条记录的 unrealized，跨实例求和。
        for sid, recs in series_by_inst.items():
            recs.sort(key=lambda x: x.recorded_at)
            prev_realized: float | None = None
            last_unrealized_by_bucket: dict[str, float] = {}
            for r in recs:
                key, pstart = _bucket_key(r.recorded_at)
                cur_realized = float(r.realized_pnl or 0)
                increment = 0.0 if prev_realized is None else cur_realized - prev_realized
                buckets[key]["realized_pnl"] += increment
                last_unrealized_by_bucket[key] = float(r.unrealized_pnl or 0)
                prev_realized = cur_realized
                if buckets[key]["_period_start"] is None or pstart < buckets[key]["_period_start"]:
                    buckets[key]["_period_start"] = pstart
            for key, u in last_unrealized_by_bucket.items():
                buckets[key]["unrealized_pnl"] += u

        # 订单交易次数按周期桶统计
        for o in orders:
            if not o.created_at:
                continue
            key, _ = _bucket_key(o.created_at)
            buckets[key]["trade_count"] += 1
            _, pstart = _bucket_key(o.created_at)
            if buckets[key]["_period_start"] is None or pstart < buckets[key]["_period_start"]:
                buckets[key]["_period_start"] = pstart

        result = []
        for key, b in buckets.items():
            realized = b["realized_pnl"]
            unrealized = b["unrealized_pnl"]
            result.append({
                "period_start": b["_period_start"].isoformat() if b["_period_start"] else key,
                "realized_pnl": round(realized, 4),
                "unrealized_pnl": round(unrealized, 4),
                "total_pnl": round(realized + unrealized, 4),
                "trade_count": b["trade_count"],
            })
        result.sort(key=lambda x: x["period_start"])
        return result

    def get_drill_down(
        self,
        db: Session,
        start_date: str,
        end_date: str,
        symbol: Optional[str] = None,
        strategy_type: Optional[str] = None,
        account_id: Optional[int] = None,
    ) -> list[dict]:
        """下钻查看订单明细。

        支持按 symbol / strategy_type 过滤，返回符合筛选条件的订单列表。
        """
        start_dt = _parse_dt(start_date)
        end_dt = _parse_dt(end_date)

        query = db.query(Order)
        if account_id is not None:
            query = query.filter(Order.account_id == account_id)
        if symbol:
            query = query.filter(Order.symbol == symbol)
        if start_dt:
            query = query.filter(Order.created_at >= start_dt)
        if end_dt:
            query = query.filter(Order.created_at <= end_dt)

        if strategy_type:
            # 关联 strategy_instances -> strategy_templates 过滤
            query = (
                query.join(StrategyInstance, Order.strategy_instance_id == StrategyInstance.id)
                .join(StrategyTemplate, StrategyInstance.template_id == StrategyTemplate.id)
                .filter(StrategyTemplate.strategy_type == strategy_type)
            )

        orders = query.order_by(Order.created_at.desc()).limit(1000).all()
        return [
            {
                "id": o.id,
                "strategy_instance_id": o.strategy_instance_id,
                "account_id": o.account_id,
                "symbol": o.symbol,
                "side": o.side,
                "order_type": o.order_type,
                "price": o.price,
                "fill_px": o.fill_px,
                "fill_sz": o.fill_sz,
                "filled_quantity": o.filled_quantity,
                "fee": o.fee,
                "status": o.status,
                "state": o.state,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "updated_at": o.updated_at.isoformat() if o.updated_at else None,
            }
            for o in orders
        ]


def _max_drawdown(series: list[float]) -> float:
    """计算累计值序列的最大回撤（peak-to-trough）。"""
    if not series:
        return 0.0
    peak = series[0]
    max_dd = 0.0
    for v in series:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
    return max_dd


attribution_service = AttributionService()
