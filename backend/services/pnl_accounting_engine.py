"""PnL 核算引擎（掌柜算法）。

实现 recompute 全量核算与 incremental_update 增量核算：
- recompute 使用累计成交量重放双向 FIFO，包含部分成交和撤单前的成交。
- incremental_update 和 heartbeat_snapshot 使用同一重算入口，避免基准漂移。

两者均写入 PnlRecord 并标记订单已核算。
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from database import SessionLocal
from models.order import Order
from models.pnl import PnlRecord
from models.strategy import StrategyInstance
from services.okx_client import OKXClient

logger = logging.getLogger(__name__)


@dataclass
class PnlSnapshot:
    strategy_instance_id: int
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    equity: float
    net_position: float
    avg_buy_price: float
    total_fee: float
    order_count: int
    recorded_at: datetime


def compose_total_pnl(realized_pnl: float, unrealized_pnl: float) -> float:
    """统一 total_pnl 入口：始终为 realized + unrealized，禁止独立累计第三套总值。"""
    return float(realized_pnl or 0) + float(unrealized_pnl or 0)


class PnlAccountingEngine:
    """PnL 全量核算引擎（单例）。

    依赖 SessionLocal 进行数据库操作；OKXClient 可选，用于获取当前价做 equity 兜底。
    """

    _instance = None
    _client_map: dict[int, OKXClient] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client_map = {}
        return cls._instance

    async def recompute(self, strategy_instance_id: int, client: OKXClient | None = None) -> PnlSnapshot | None:
        """全量核算（掌柜算法）。

        扫描该策略实例下已有成交的订单，按双向 FIFO 计算盈亏指标，
        写入一条 PnlRecord，并批量标记这些订单的 pnl_accounted=True。

        Args:
            strategy_instance_id: 策略实例 ID
            client: 可选 OKXClient，用于获取当前价做 equity 兜底；为 None 时跳过。

        Returns:
            PnlSnapshot | None: 有 filled 订单时返回核算结果快照；无成交时返回 None（不写全 0 记录）。
        """
        db = SessionLocal()
        try:
            # 策略实例信息（取 account_id 与 symbol）
            instance = (
                db.query(StrategyInstance)
                .filter(StrategyInstance.id == strategy_instance_id)
                .first()
            )
            account_id = instance.account_id if instance else None
            symbol = instance.symbol if instance else None
            if instance is None:
                return None

            # Include executed quantities even after an order is canceled.
            orders = (
                db.query(Order)
                .filter(Order.strategy_instance_id == strategy_instance_id)
                .filter((Order.status == "filled") | (Order.fill_sz > 0) | (Order.filled_quantity > 0))
                .all()
            )

            # 无成交订单时不写全 0 记录，直接返回 None
            if not orders:
                return None
            if any(not math.isfinite(self._qty(o)) or self._qty(o) < 0 for o in orders):
                raise ValueError("PnL unavailable: invalid execution quantity")
            orders = [o for o in orders if self._qty(o) > 0]
            if not orders:
                return None
            if any(getattr(o, "ct_type", None) == "inverse" for o in orders):
                raise ValueError("PnL unavailable: inverse contracts require settlement-currency accounting")
            if any(not math.isfinite(self._px(o)) or self._px(o) <= 0 for o in orders):
                raise ValueError("PnL unavailable: invalid execution price")

            # 2. 按 side 分类
            buy_orders = [o for o in orders if (o.side or "").lower() == "buy"]
            sell_orders = [o for o in orders if (o.side or "").lower() == "sell"]

            # 3. 计算（掌柜算法）
            metrics = self._compute_pnl_metrics(buy_orders, sell_orders, orders)
            total_pnl = metrics['total_pnl']
            total_fee = metrics['total_fee']
            avg_buy_px = metrics['avg_buy_price']
            realized_pnl = metrics['realized_pnl']
            unrealized_pnl = metrics['unrealized_pnl']
            net_position = metrics['net_position']
            # fee_rate：从策略参数取，默认 0.001
            fee_rate = 0.001
            if instance and instance.params:
                try:
                    fee_rate = float(instance.params.get("fee_rate", 0.001))
                except (TypeError, ValueError):
                    fee_rate = 0.001
            if not math.isfinite(fee_rate) or fee_rate < 0:
                raise ValueError("PnL unavailable: invalid estimated closing fee rate")

            # 修正 unrealized_pnl：用当前价重算（与 incremental_update / heartbeat 一致）
            # _compute_pnl_metrics 的 unrealized = total_pnl - realized 在仅有买单时会得到 -buy_total，
            # 严重失真。这里用 (current_price - avg_buy_price) * net_position - 预估手续费 重算。
            current_price_for_pnl = 0.0
            if client is not None and symbol and net_position != 0:
                try:
                    current_price_for_pnl = await self._get_current_price(
                        symbol, client, strategy_instance_id
                    )
                except Exception as e:
                    logger.warning(f"recompute: 获取 {symbol} 当前价失败: {e}")
                    current_price_for_pnl = 0.0
            unrealized_pnl = 0.0
            if net_position != 0:
                if not math.isfinite(current_price_for_pnl) or current_price_for_pnl <= 0:
                    raise ValueError("PnL unavailable: current market price is required for an open position")
                unrealized_pnl = (current_price_for_pnl - avg_buy_px) * net_position
                unrealized_pnl -= metrics["remaining_open_fee"]
                unrealized_pnl -= abs(net_position) * current_price_for_pnl * fee_rate
            # 重算 total_pnl = realized + unrealized（保持一致性）
            total_pnl = compose_total_pnl(realized_pnl, unrealized_pnl)

            # 4. equity：保留上次 equity（账户级快照）；无记录且提供 client 时用当前价兜底
            latest = self._get_latest_pnl_record(db, strategy_instance_id)
            if latest is not None and latest.equity is not None:
                equity = float(latest.equity)
            elif client is not None and symbol and current_price_for_pnl:
                equity = total_pnl + net_position * current_price_for_pnl
            else:
                equity = 0.0

            # 5. 写入 PnlRecord
            recorded_at = datetime.now(timezone.utc)
            record = PnlRecord(
                account_id=account_id,
                strategy_instance_id=strategy_instance_id,
                equity=equity,
                unrealized_pnl=unrealized_pnl,
                realized_pnl=realized_pnl,
                total_pnl=total_pnl,
                is_final=False,
                recorded_at=recorded_at,
                net_position=net_position,
                avg_buy_price=avg_buy_px,
                total_fee=total_fee,
                order_count=len(orders),
            )
            db.add(record)

            # The accounted flag is informational; partial executions can change.
            db.query(Order).filter(
                Order.strategy_instance_id == strategy_instance_id,
                Order.id.in_([o.id for o in orders]),
            ).update({Order.pnl_accounted: True}, synchronize_session=False)

            db.commit()

            return PnlSnapshot(
                strategy_instance_id=strategy_instance_id,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                total_pnl=total_pnl,
                equity=equity,
                net_position=net_position,
                avg_buy_price=avg_buy_px,
                total_fee=total_fee,
                order_count=len(orders),
                recorded_at=recorded_at,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def incremental_update(
        self, strategy_instance_id: int, client: OKXClient | None = None
    ) -> PnlSnapshot | None:
        """Rebuild from cumulative executions, including changes to partial fills.

        A boolean accounted flag cannot represent an order whose executed quantity
        changes. Full FIFO replay also preserves each remaining lot's cost.
        """
        return await self.recompute(strategy_instance_id, client)

    async def heartbeat_snapshot(
        self, strategy_instance_id: int, client: OKXClient | None = None
    ) -> PnlSnapshot | None:
        """Refresh from executions; never persist a fabricated zero baseline."""
        snapshot = await self.recompute(strategy_instance_id, client)
        if snapshot is not None:
            return snapshot
        db = SessionLocal()
        try:
            if db.query(StrategyInstance).filter(StrategyInstance.id == strategy_instance_id).first() is None:
                return None
        finally:
            db.close()
        return PnlSnapshot(
            strategy_instance_id=strategy_instance_id,
            realized_pnl=0.0, unrealized_pnl=0.0, total_pnl=0.0,
            equity=0.0, net_position=0.0, avg_buy_price=0.0,
            total_fee=0.0, order_count=0,
            recorded_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _qty(o: Order) -> float:
        """成交数量：actual_qty 优先，回退 fill_sz → filled_quantity → quantity。"""
        if o.actual_qty is not None and float(o.actual_qty) > 0:
            return float(o.actual_qty)
        contract_value = getattr(o, "ct_val", None)
        multiplier = float(contract_value) if isinstance(contract_value, (int, float)) else 1.0
        if o.fill_sz is not None:
            return float(o.fill_sz) * multiplier
        if o.filled_quantity is not None:
            return float(o.filled_quantity) * multiplier
        return float(o.quantity or 0) * multiplier

    @staticmethod
    def _px(o: Order) -> float:
        """成交价：fill_px 优先，回退 price。"""
        if o.fill_px is not None:
            return float(o.fill_px)
        return float(o.price or 0)

    @staticmethod
    def _compute_pnl_metrics(buy_orders, sell_orders, all_orders):
        """从订单列表计算 PnL 指标（FIFO 配对算法）。

        使用 FIFO（先买先配）配对 buy/sell 订单计算 realized_pnl，
        与 OKX get_fills 独立计算保持一致，避免平均价法在网格策略中高估盈亏。
        """
        from collections import deque

        buy_total = sum(PnlAccountingEngine._px(o) * PnlAccountingEngine._qty(o) for o in buy_orders)
        sell_total = sum(PnlAccountingEngine._px(o) * PnlAccountingEngine._qty(o) for o in sell_orders)
        buy_qty_sum = sum(PnlAccountingEngine._qty(o) for o in buy_orders)
        sell_qty_sum = sum(PnlAccountingEngine._qty(o) for o in sell_orders)
        total_fee = 0.0
        total_pnl = sell_total - buy_total - total_fee

        # FIFO 配对：按成交时间排序（update_time = OKX uTime，毫秒时间戳字符串）
        # 注意：不能用 created_at（下单时间），因为网格策略下单顺序和成交顺序可能不同，
        # 用下单时间排序会导致 FIFO 配对与 OKX fills 的成交时间顺序不一致
        def _sort_key(o):
            try:
                # update_time 是 OKX 的 uTime（毫秒时间戳字符串），filled 时为成交时间
                if o.update_time and str(o.update_time).isdigit():
                    return (0, int(o.update_time))
            except (ValueError, TypeError):
                pass
            # 回退到 created_at
            return (1, o.created_at if o.created_at else "")
        sorted_orders = sorted(all_orders, key=_sort_key)
        buy_queue: deque = deque()  # Signed FIFO lots: [quantity, price, fee/unit]
        realized_pnl = 0.0
        matched_qty = 0.0

        for o in sorted_orders:
            qty = PnlAccountingEngine._qty(o)
            px = PnlAccountingEngine._px(o)
            fee = float(o.fee or 0)
            if not math.isfinite(fee):
                raise ValueError("PnL unavailable: invalid execution fee")
            currency = getattr(o, "fee_ccy", None)
            # With exchange currency metadata, OKX fees are signed cash flows:
            # negative = charge, positive = rebate. Legacy rows used unsigned fees.
            cost = abs(fee)
            if isinstance(currency, str) and currency:
                base, quote, *_ = o.symbol.split("-")
                if currency == quote:
                    cost = -fee
                elif currency == base:
                    cost = -fee * px
                    if len(o.symbol.split("-")) == 2:
                        # Spot base fees change delivered inventory, not quote cash.
                        # Preserve cash consideration through the effective lot price.
                        total_fee += cost
                        net_qty = qty + fee if o.side == "buy" else qty - fee
                        if net_qty <= 0:
                            raise ValueError("PnL unavailable: base fee exceeds execution quantity")
                        px = px * qty / net_qty
                        qty = net_qty
                        cost = 0.0
                else:
                    raise ValueError(f"PnL unavailable: unsupported fee currency {currency}")
            fee_per_unit = cost / qty if qty > 0 else 0.0
            total_fee += cost
            side = (o.side or "").lower()

            direction = 1 if side == "buy" else -1
            if side not in ("buy", "sell") or qty <= 0:
                continue
            remaining = qty
            while remaining > 1e-12 and buy_queue and buy_queue[0][0] * direction < 0:
                lot = buy_queue[0]
                lot_direction = 1 if lot[0] > 0 else -1
                matched = min(remaining, abs(lot[0]))
                realized_pnl += (px - lot[1]) * matched * lot_direction
                realized_pnl -= matched * (lot[2] + fee_per_unit)
                lot[0] -= matched * lot_direction
                remaining -= matched
                matched_qty += matched
                if abs(lot[0]) <= 1e-12:
                    buy_queue.popleft()
            if remaining > 1e-12:
                buy_queue.append([remaining * direction, px, fee_per_unit])

        # avg_buy_price 用 FIFO 配对后剩余买单的加权平均（用于 unrealized 计算和增量核算基准）
        # 注意：不能用所有买单的加权平均，否则已被卖单配对消耗的高价买单会拉偏均价，
        # 导致 incremental_update 用错误均价作为 buy_queue 基准，realized_pnl 误差持续累积。
        remaining_buy_qty = sum(abs(b[0]) for b in buy_queue)
        remaining_buy_value = sum(abs(b[0]) * b[1] for b in buy_queue)
        avg_buy_px = remaining_buy_value / remaining_buy_qty if remaining_buy_qty > 0 else 0
        avg_sell_px = sell_total / sell_qty_sum if sell_qty_sum else 0
        total_pnl = sell_total - buy_total - total_fee
        unrealized_pnl = total_pnl - realized_pnl
        net_position = sum(b[0] for b in buy_queue)
        return {
            'buy_total': buy_total, 'sell_total': sell_total, 'total_fee': total_fee,
            'total_pnl': total_pnl, 'matched_qty': matched_qty,
            'avg_buy_price': avg_buy_px, 'avg_sell_price': avg_sell_px,
            'realized_pnl': realized_pnl, 'unrealized_pnl': unrealized_pnl,
            'net_position': net_position, 'order_count': len(all_orders),
            'remaining_open_fee': sum(abs(b[0]) * b[2] for b in buy_queue),
        }

    async def _get_current_price(
        self, symbol: str, client: OKXClient, strategy_instance_id: int | None = None
    ) -> float:
        """调用 client.get_ticker(symbol) 获取最新价。

        获取失败（异常或空响应）时记录 ``market_data_unavailable`` 事件，
        不中断主流程，返回 0.0。

        Args:
            symbol: 交易品种
            client: OKXClient 实例
            strategy_instance_id: 策略实例 ID，用于事件落库；为 None 时不记录事件。
        """
        try:
            tickers = await client.get_ticker(symbol)
            if tickers:
                return float(tickers[0].get("last", 0))
            # 空响应：记录 market_data_unavailable 事件
            if strategy_instance_id is not None:
                self._record_event(
                    strategy_instance_id,
                    "market_data_unavailable",
                    f"获取 {symbol} 行情失败：空响应",
                    {"symbol": symbol, "reason": "empty_ticker"},
                )
            return 0.0
        except Exception as e:
            logger.warning(f"_get_current_price: 获取 {symbol} 行情异常: {e}")
            if strategy_instance_id is not None:
                self._record_event(
                    strategy_instance_id,
                    "market_data_unavailable",
                    f"获取 {symbol} 行情异常: {e}",
                    {"symbol": symbol, "reason": str(e)},
                )
            return 0.0

    def _record_event(
        self, strategy_instance_id: int, event_type: str, message: str, details: dict | None = None
    ):
        """记录策略事件到 strategy_events 表（参考 base_strategy._record_event）。

        使用独立 session，避免影响调用方事务；写入失败仅打印 warning，不抛异常。
        """
        try:
            import json
            from models.strategy_event import StrategyEvent
            db = SessionLocal()
            try:
                event = StrategyEvent(
                    strategy_instance_id=strategy_instance_id,
                    event_type=event_type,
                    message=message,
                    details=json.dumps(details, ensure_ascii=False) if details else None,
                )
                db.add(event)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"_record_event: 写 strategy_event 失败 type={event_type} err={e}")

    async def _get_client(self, strategy_instance_id: int) -> OKXClient | None:
        """从 StrategyEngine 获取或按账户创建 OKXClient，按 strategy_instance_id 缓存。"""
        if strategy_instance_id in self._client_map:
            return self._client_map[strategy_instance_id]

        # 延迟导入避免循环依赖
        from services.strategy_engine import strategy_engine
        from models.account import Account

        db = SessionLocal()
        try:
            instance = (
                db.query(StrategyInstance)
                .filter(StrategyInstance.id == strategy_instance_id)
                .first()
            )
            if not instance:
                return None
            account = db.query(Account).filter(Account.id == instance.account_id).first()
            if not account:
                return None
            client = strategy_engine._get_client_for_account(account, strategy_instance_id=strategy_instance_id)
            self._client_map[strategy_instance_id] = client
            return client
        finally:
            db.close()

    def _get_latest_pnl_record(self, db: Session, strategy_instance_id: int) -> PnlRecord | None:
        """查询该策略实例最新一条 PnlRecord。"""
        return (
            db.query(PnlRecord)
            .filter(PnlRecord.strategy_instance_id == strategy_instance_id)
            .order_by(PnlRecord.recorded_at.desc())
            .first()
        )

    async def reconcile_positions(
        self,
        account_id: int,
        symbol: str,
        client: OKXClient | None = None,
        tolerance: float | None = None,
    ) -> dict:
        """虚拟仓位对账（SubTask 4.2 / 4.3）。

        聚合该账户下所有交易该 symbol 的活跃策略实例的虚拟持仓之和，与交易所真实持仓对比。

        Args:
            account_id: 账户 ID
            symbol: 交易品种，如 "ETH-USDT-SWAP"
            client: 可选 OKXClient，未提供时延迟创建（按账户取）
            tolerance: 容差；为 None 时用默认 0.0001

        Returns:
            {"account_id", "symbol", "virtual_total", "real_total",
             "diff", "tolerance", "matched": bool}
        """
        # 默认容差 0.0001（足以覆盖浮点累加误差与小数量持仓）
        tol = float(tolerance) if tolerance is not None else 0.0001

        db = SessionLocal()
        try:
            # 1. 查询该账户下交易该 symbol 的活跃策略实例
            instances = (
                db.query(StrategyInstance)
                .filter(StrategyInstance.account_id == account_id)
                .filter(StrategyInstance.symbol == symbol)
                .filter(StrategyInstance.status.in_(["running", "paused"]))
                .all()
            )

            # 2. 聚合每个实例最新 PnlRecord 的 net_position
            virtual_total = 0.0
            instance_ids: list[int] = []
            for inst in instances:
                instance_ids.append(inst.id)
                latest = self._get_latest_pnl_record(db, inst.id)
                if latest is not None and latest.net_position is not None:
                    virtual_total += float(latest.net_position)

            # 3. 获取 instrument 元信息（用于区分现货/合约 + ctVal 转换）
            okx_client = client
            if okx_client is None and instance_ids:
                # 延迟按第一个策略实例取 client
                okx_client = await self._get_client(instance_ids[0])

            inst_info = None
            if okx_client is not None:
                try:
                    from services.instrument_cache import instrument_cache
                    inst_info = await instrument_cache.get_instrument(symbol, okx_client)
                except Exception as e:
                    logger.warning(
                        f"reconcile_positions: 获取 {symbol} instrument 元信息失败: {e}"
                    )

            # 3.1 现货/合约判断：
            # - ctType 非空（linear/inverse）或符号以 -SWAP 结尾 → 合约，用 /account/positions 查真实持仓
            # - 否则视为现货：positions 接口不返回现货持仓，仓位隔离对账不适用
            #   （现货余额是共享池，无法按策略隔离；pnl_correctness 检查已覆盖虚拟仓位一致性）
            ct_type = (inst_info.get("ctType") if inst_info else None)
            is_derivative = bool(ct_type) or symbol.endswith("-SWAP")
            is_spot = not is_derivative

            if is_spot:
                logger.info(
                    f"reconcile_positions: {symbol} 为现货，仓位隔离对账不适用，跳过 "
                    f"(virtual_total={virtual_total})"
                )
                result = {
                    "account_id": account_id,
                    "symbol": symbol,
                    "virtual_total": virtual_total,
                    "real_total": 0.0,
                    "diff": 0.0,
                    "tolerance": tol,
                    "matched": True,
                    "note": "spot_instrument_position_isolation_not_applicable",
                }
                return result

            # 3.2 合约：查交易所真实持仓
            real_total = 0.0
            if okx_client is not None:
                try:
                    risk = await okx_client.get_position_risk(symbol)
                    if risk is not None:
                        pos_str = risk.get("pos")
                        if pos_str is not None and pos_str != "":
                            try:
                                real_total = float(pos_str)
                            except (ValueError, TypeError):
                                real_total = 0.0
                except Exception as e:
                    logger.warning(
                        f"reconcile_positions: 查询 {symbol} 真实持仓失败: {e}"
                    )

            # 3.3 合约持仓单位转换：OKX pos 为合约张数，虚拟持仓为币种数量（actual_qty = sz × ctVal）
            # 需将 real_total 乘以 ctVal 统一到同一单位
            if okx_client is not None and real_total != 0.0 and inst_info is not None:
                try:
                    ct_val = float(inst_info.get("ctVal", 1.0))
                    if ct_val != 1.0:
                        real_total = real_total * ct_val
                except Exception as e:
                    logger.warning(
                        f"reconcile_positions: {symbol} ctVal 转换失败，按 ctVal=1.0 处理: {e}"
                    )

            # 4. 差异
            diff = abs(virtual_total - real_total)
            matched = diff <= tol

            result = {
                "account_id": account_id,
                "symbol": symbol,
                "virtual_total": virtual_total,
                "real_total": real_total,
                "diff": diff,
                "tolerance": tol,
                "matched": matched,
            }

            # 5. 差异超容差：记录日志 + 触发通知（SubTask 4.3）
            if not matched:
                logger.warning(
                    f"position_mismatch: account={account_id} symbol={symbol} "
                    f"virtual_total={virtual_total} real_total={real_total} "
                    f"diff={diff} tolerance={tol}"
                )
                # 可选：写入该账户下第一个相关策略实例的事件
                first_instance_id = instance_ids[0] if instance_ids else None
                if first_instance_id is not None:
                    try:
                        from models.strategy_event import StrategyEvent
                        event = StrategyEvent(
                            strategy_instance_id=first_instance_id,
                            event_type="position_mismatch",
                            message=(
                                f"仓位对账不一致: {symbol} virtual={virtual_total} "
                                f"real={real_total} diff={diff} tolerance={tol}"
                            ),
                            details=__import__("json").dumps(result, ensure_ascii=False),
                        )
                        db.add(event)
                        db.commit()
                    except Exception as e:
                        db.rollback()
                        logger.warning(f"reconcile_positions: 写 strategy_event 失败: {e}")

                # 触发通知（延迟导入避免循环依赖）
                try:
                    from services.notification_service import notification_service
                    title = f"[仓位对账不一致] {symbol}"
                    message = (
                        f"账户 {account_id} {symbol} 虚拟持仓 {virtual_total} 与真实持仓 "
                        f"{real_total} 不一致，差异 {diff} 超容差 {tol}"
                    )
                    ctx = dict(result)
                    ctx["event"] = "position_mismatch"
                    try:
                        loop = __import__("asyncio").get_running_loop()
                        loop.create_task(
                            notification_service.notify(
                                "position_mismatch", title, message, ctx
                            )
                        )
                    except RuntimeError:
                        # 无事件循环：跳过异步通知
                        pass
                except Exception as e:
                    logger.warning(f"reconcile_positions: 触发通知失败: {e}")

            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def reconcile_orphan_orders(
        self,
        account_id: int,
        symbol: str,
        client: OKXClient | None = None,
    ) -> dict:
        """检测并回补 OKX 上有成交但 DB 缺失的孤儿订单。

        流程：
        1. 从 OKX 拉取最近成交记录（get_fills）
        2. 按 ordId 与 DB orders 对账，找出 orphan ordId
        3. 对每个 orphan ordId，查 OKX 订单历史获取完整订单信息
        4. 将缺失订单回补到 DB（分配给该 symbol 下唯一有成交的策略实例，
           若多个则选最新 PnLRecord 的策略）
        5. 回补后重算受影响策略的 PnL

        Returns:
            {"account_id", "symbol", "orphan_ord_ids", "backfilled", "failed", "recomputed"}
        """
        from models.account import Account
        from services.instrument_cache import instrument_cache

        db = SessionLocal()
        result = {
            "account_id": account_id,
            "symbol": symbol,
            "orphan_ord_ids": [],
            "backfilled": [],
            "failed": [],
            "recomputed": [],
        }
        try:
            # 获取或创建 client
            okx_client = client
            if okx_client is None:
                account = db.query(Account).filter(Account.id == account_id).first()
                if account:
                    okx_client = OKXClient(
                        api_key_encrypted=account.api_key_encrypted,
                        secret_encrypted=account.secret_key_encrypted,
                        passphrase_encrypted=account.passphrase_encrypted,
                        trade_mode=account.trade_mode,
                        account_name=account.name,
                    )
            if okx_client is None:
                logger.warning(f"reconcile_orphan_orders: 账户 {account_id} 不存在，跳过")
                return result

            # 1. 拉取 OKX 成交记录
            try:
                fills = await okx_client.trade.get_fills(instId=symbol, limit="100")
            except Exception as e:
                logger.error(f"reconcile_orphan_orders: get_fills 失败 {symbol}: {e}")
                return result

            # 2. 找出 orphan ordId
            orphan_ord_ids: set[str] = set()
            for fill in fills:
                ord_id = fill.get("ordId", "")
                if not ord_id:
                    continue
                existing = db.query(Order).filter(Order.order_id == ord_id).first()
                if existing is None:
                    orphan_ord_ids.add(ord_id)

            result["orphan_ord_ids"] = sorted(orphan_ord_ids)
            if not orphan_ord_ids:
                logger.info(f"reconcile_orphan_orders: {symbol} 无孤儿订单")
                return result

            logger.info(f"reconcile_orphan_orders: {symbol} 发现 {len(orphan_ord_ids)} 个孤儿订单: {orphan_ord_ids}")

            # 3. 获取 instrument 元信息
            inst_info = await instrument_cache.get_instrument(symbol, okx_client)
            ct_val = float(inst_info.get("ctVal", 1.0))
            ct_type = inst_info.get("ctType") or ""
            settle_ccy = inst_info.get("settleCcy") or ""

            # 4. 确定目标策略实例（该 symbol 下有成交的活跃策略）
            instances = (
                db.query(StrategyInstance)
                .filter(StrategyInstance.account_id == account_id)
                .filter(StrategyInstance.symbol == symbol)
                .filter(StrategyInstance.status.in_(["running", "paused"]))
                .all()
            )
            # 选有 PnlRecord 的策略（说明已有成交），否则选第一个
            target_instance_id: int | None = None
            for inst in instances:
                latest = self._get_latest_pnl_record(db, inst.id)
                if latest is not None:
                    target_instance_id = inst.id
                    break
            if target_instance_id is None and instances:
                target_instance_id = instances[0].id
            if target_instance_id is None:
                logger.warning(f"reconcile_orphan_orders: {symbol} 无可用策略实例，跳过回补")
                result["failed"] = list(orphan_ord_ids)
                return result

            # 5. 查 OKX 订单历史并回补
            inst_type = "SWAP" if "-SWAP" in symbol else "SPOT"
            for ord_id in sorted(orphan_ord_ids):
                try:
                    # 先查 order history（最近7天）
                    order_data = await okx_client.trade.get_orders_history(
                        instType=inst_type, instId=symbol, limit="50"
                    )
                    okx_order = None
                    for od in order_data:
                        if od.get("ordId") == ord_id:
                            okx_order = od
                            break
                    if okx_order is None:
                        # 再查 archive（更早的历史）
                        order_data = await okx_client.trade.get_orders_history_archive(
                            instType=inst_type, instId=symbol, limit="50"
                        )
                        for od in order_data:
                            if od.get("ordId") == ord_id:
                                okx_order = od
                                break

                    if okx_order is None:
                        logger.warning(f"reconcile_orphan_orders: OKX 未找到订单 {ord_id}，跳过")
                        result["failed"].append(ord_id)
                        continue

                    # 从 fills 聚合该订单的成交信息（可能多次部分成交）
                    ord_fills = [f for f in fills if f.get("ordId") == ord_id]
                    total_fill_sz = sum(float(f.get("fillSz") or 0) for f in ord_fills)
                    # 加权平均成交价
                    if total_fill_sz > 0:
                        avg_fill_px = sum(
                            float(f.get("fillPx") or 0) * float(f.get("fillSz") or 0)
                            for f in ord_fills
                        ) / total_fill_sz
                    else:
                        avg_fill_px = float(okx_order.get("avgPx") or 0)
                    total_fee = sum(float(f.get("fee") or 0) for f in ord_fills)

                    # 判断状态
                    okx_state = okx_order.get("state", "")
                    state_map = {
                        "filled": "filled",
                        "canceled": "canceled",
                        "partially_filled": "partially_filled",
                        "live": "live",
                    }
                    state = state_map.get(okx_state, okx_state)
                    status = "filled" if state == "filled" else ("live" if state in ("live", "partially_filled") else "canceled")

                    new_order = Order(
                        strategy_instance_id=target_instance_id,
                        account_id=account_id,
                        symbol=symbol,
                        order_id=ord_id,
                        cl_ord_id=okx_order.get("clOrdId") or "",
                        side=okx_order.get("side", ""),
                        order_type=okx_order.get("ordType", "limit"),
                        price=float(okx_order.get("px") or 0) if okx_order.get("px") else None,
                        quantity=float(okx_order.get("sz") or 0) if okx_order.get("sz") else None,
                        filled_quantity=total_fill_sz if total_fill_sz > 0 else 0,
                        fill_px=avg_fill_px if avg_fill_px > 0 else None,
                        fill_sz=total_fill_sz if total_fill_sz > 0 else None,
                        fee=total_fee if total_fee != 0 else None,
                        state=state,
                        status=status,
                        update_time=okx_order.get("uTime", ""),
                        ct_val=ct_val,
                        ct_type=ct_type or None,
                        settle_ccy=settle_ccy or None,
                        actual_qty=total_fill_sz * ct_val if total_fill_sz > 0 else 0,
                    )
                    db.add(new_order)
                    db.commit()
                    result["backfilled"].append(ord_id)
                    logger.info(
                        f"reconcile_orphan_orders: 回补订单 {ord_id} "
                        f"side={new_order.side} fillSz={total_fill_sz} fillPx={avg_fill_px} "
                        f"-> strategy_instance_id={target_instance_id}"
                    )

                    # 写 strategy_event
                    self._record_event(
                        target_instance_id,
                        "order_backfilled",
                        f"孤儿订单回补 ordId={ord_id} symbol={symbol} side={new_order.side}",
                        {
                            "ordId": ord_id,
                            "symbol": symbol,
                            "side": new_order.side,
                            "fill_sz": total_fill_sz,
                            "fill_px": avg_fill_px,
                            "source": "reconcile_orphan_orders",
                        },
                    )
                except Exception as e:
                    db.rollback()
                    logger.error(f"reconcile_orphan_orders: 回补订单 {ord_id} 失败: {e}", exc_info=True)
                    result["failed"].append(ord_id)

            # 6. 重算受影响策略的 PnL
            if result["backfilled"] and target_instance_id is not None:
                try:
                    snapshot = await self.recompute(target_instance_id, client=okx_client)
                    result["recomputed"].append({
                        "strategy_instance_id": target_instance_id,
                        "realized_pnl": float(snapshot.realized_pnl) if snapshot else None,
                        "net_position": float(snapshot.net_position) if snapshot else None,
                    })
                    logger.info(
                        f"reconcile_orphan_orders: 重算策略#{target_instance_id} PnL 完成 "
                        f"realized={snapshot.realized_pnl if snapshot else 'N/A'} "
                        f"net_pos={snapshot.net_position if snapshot else 'N/A'}"
                    )
                except Exception as e:
                    logger.error(f"reconcile_orphan_orders: 重算 PnL 失败: {e}", exc_info=True)

            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


pnl_accounting_engine = PnlAccountingEngine()
