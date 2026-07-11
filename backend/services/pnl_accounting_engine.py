"""PnL 核算引擎（掌柜算法）。

实现 recompute 全量核算与 incremental_update 增量核算：
- recompute 扫描某策略实例下所有 filled 订单，按买卖分类计算盈亏。
- incremental_update 仅处理 pnl_accounted=False 的新增订单，基于最新 PnlRecord 累加。

两者均写入 PnlRecord 并标记订单已核算。
"""

import logging
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

    async def recompute(self, strategy_instance_id: int, client: OKXClient | None = None) -> PnlSnapshot:
        """全量核算（掌柜算法）。

        扫描该策略实例下所有 status='filled' 的订单，按买卖分类计算盈亏指标，
        写入一条 PnlRecord，并批量标记这些订单的 pnl_accounted=True。

        Args:
            strategy_instance_id: 策略实例 ID
            client: 可选 OKXClient，用于获取当前价做 equity 兜底；为 None 时跳过。

        Returns:
            PnlSnapshot: 核算结果快照
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

            # 1. 查询所有 filled 订单（忽略 canceled）
            orders = (
                db.query(Order)
                .filter(Order.strategy_instance_id == strategy_instance_id)
                .filter(Order.status == "filled")
                .all()
            )

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
            # 兜底：avg_buy_price=0 且有净多头仓位时，避免 unrealized 异常
            if avg_buy_px == 0 and net_position > 0:
                unrealized_pnl = 0.0

            # 4. equity：保留上次 equity（账户级快照）；无记录且提供 client 时用当前价兜底
            latest = self._get_latest_pnl_record(db, strategy_instance_id)
            if latest is not None and latest.equity is not None:
                equity = float(latest.equity)
            elif client is not None and symbol:
                # 兜底：无历史记录时用 当前价×净持仓 + total_pnl 估算
                try:
                    current_price = await self._get_current_price(symbol, client)
                    equity = total_pnl + net_position * current_price
                except Exception as e:
                    logger.warning(f"recompute: 获取 {symbol} 当前价失败，equity 兜底为 0: {e}")
                    equity = 0.0
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

            # 6. 批量更新该策略所有 filled 订单的 pnl_accounted=True
            db.query(Order).filter(
                Order.strategy_instance_id == strategy_instance_id,
                Order.status == "filled",
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
        """增量核算：仅处理 pnl_accounted=False 的新增 filled 订单。

        基于该策略最新一条 PnlRecord 的累计值，叠加新增订单的影响，写入新 PnlRecord
        并标记这些订单已核算。若无新增订单返回 None（不写空记录）。

        Args:
            strategy_instance_id: 策略实例 ID
            client: 可选 OKXClient，用于获取当前价计算未实现盈亏。

        Returns:
            PnlSnapshot | None: 有新增订单时返回核算结果，否则 None。
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

            # fee_rate：从策略参数取，默认 0.001
            fee_rate = 0.001
            if instance and instance.params:
                try:
                    fee_rate = float(instance.params.get("fee_rate", 0.001))
                except (TypeError, ValueError):
                    fee_rate = 0.001

            # 1. 查询新增 filled 且未核算的订单（按时间升序）
            new_orders = (
                db.query(Order)
                .filter(Order.strategy_instance_id == strategy_instance_id)
                .filter(Order.status == "filled")
                .filter(Order.pnl_accounted.is_(False))
                .order_by(Order.created_at.asc())
                .all()
            )
            if not new_orders:
                return None

            # 2. 读取最新 PnlRecord 作为基准
            latest = self._get_latest_pnl_record(db, strategy_instance_id)
            if latest is None:
                # 首次核算无基准，转执行全量 recompute 确保 avg_buy_price 正确
                return await self.recompute(strategy_instance_id, client)
            base_realized = float(latest.realized_pnl or 0) if latest else 0.0
            base_net_position = float(latest.net_position or 0) if latest else 0.0
            base_avg_buy_price = float(latest.avg_buy_price or 0) if latest else 0.0
            base_total_fee = float(latest.total_fee or 0) if latest else 0.0
            base_order_count = int(latest.order_count or 0) if latest else 0
            latest_equity = float(latest.equity or 0) if latest else 0.0

            # base_buy_qty / base_buy_value 由 net_position 与 avg_buy_price 推算
            if base_net_position > 0 and base_avg_buy_price > 0:
                base_buy_qty = base_net_position
                base_buy_value = base_net_position * base_avg_buy_price
            else:
                base_buy_qty = 0.0
                base_buy_value = 0.0

            # 3. 按时间顺序处理新增订单
            realized_pnl = base_realized
            net_position = base_net_position
            avg_buy_price = base_avg_buy_price
            total_fee = base_total_fee
            order_count = base_order_count
            buy_qty = base_buy_qty
            buy_value = base_buy_value

            for o in new_orders:
                qty = self._qty(o)
                px = self._px(o)
                side = (o.side or "").lower()
                if side == "buy":
                    # 从空仓或反向开仓状态买入时，重置买入累计以新均价累加
                    if net_position <= 0:
                        buy_qty = 0.0
                        buy_value = 0.0
                    buy_qty += qty
                    buy_value += qty * px
                    avg_buy_price = buy_value / buy_qty if buy_qty else 0.0
                    net_position += qty
                elif side == "sell":
                    previous_net_position = net_position
                    net_position -= qty
                    # 仓位归零或变为负（反向开仓）时计算闭环盈亏
                    if net_position <= 0 and previous_net_position > 0:
                        closed_qty = min(qty, previous_net_position)
                        realized_pnl += closed_qty * (px - avg_buy_price)
                total_fee += float(o.fee or 0)
                order_count += 1

            # 4. 计算未实现盈亏
            unrealized_pnl = 0.0
            price_symbol = symbol or (new_orders[0].symbol if new_orders else None)
            if client is not None and price_symbol and net_position != 0:
                try:
                    current_price = await self._get_current_price(price_symbol, client)
                except Exception as e:
                    logger.warning(
                        f"incremental_update: 获取 {price_symbol} 当前价失败: {e}"
                    )
                    current_price = 0.0
                if current_price:
                    # 兜底：avg_buy_price=0 时不计算 unrealized（避免极端负值）
                    if avg_buy_price == 0 and net_position > 0:
                        unrealized_pnl = 0.0
                    else:
                        unrealized_pnl = (current_price - avg_buy_price) * net_position
                        # 扣预估手续费
                        unrealized_pnl -= abs(net_position) * current_price * fee_rate

            # 5. total_pnl
            total_pnl = realized_pnl + unrealized_pnl

            # 6. equity：保留上次 equity（账户级快照，不随策略 PnL 变动）
            equity = latest_equity

            # 7. 写入新 PnlRecord
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
                avg_buy_price=avg_buy_price,
                total_fee=total_fee,
                order_count=order_count,
            )
            db.add(record)

            # 8. 批量标记新增订单 pnl_accounted=True
            new_order_ids = [o.id for o in new_orders]
            db.query(Order).filter(Order.id.in_(new_order_ids)).update(
                {Order.pnl_accounted: True}, synchronize_session=False
            )

            db.commit()

            return PnlSnapshot(
                strategy_instance_id=strategy_instance_id,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                total_pnl=total_pnl,
                equity=equity,
                net_position=net_position,
                avg_buy_price=avg_buy_price,
                total_fee=total_fee,
                order_count=order_count,
                recorded_at=recorded_at,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def heartbeat_snapshot(
        self, strategy_instance_id: int, client: OKXClient | None = None
    ) -> PnlSnapshot | None:
        """心跳快照：无成交时复用最新 PnlRecord 的累计值，重新计算 unrealized_pnl。

        不更新任何订单的 pnl_accounted 标记。
        """
        db = SessionLocal()
        try:
            # 读取策略实例信息
            instance = (
                db.query(StrategyInstance)
                .filter(StrategyInstance.id == strategy_instance_id)
                .first()
            )
            if not instance:
                return None
            account_id = instance.account_id
            symbol = instance.symbol

            # 读取最新 PnlRecord
            latest = self._get_latest_pnl_record(db, strategy_instance_id)
            if not latest:
                return None  # 无基准记录，无法写心跳

            realized_pnl = float(latest.realized_pnl or 0)
            net_position = float(latest.net_position or 0)
            avg_buy_price = float(latest.avg_buy_price or 0)
            total_fee = float(latest.total_fee or 0)
            order_count = int(latest.order_count or 0)
            equity = float(latest.equity or 0)

            # fee_rate
            fee_rate = 0.001
            if instance.params:
                try:
                    fee_rate = float(instance.params.get("fee_rate", 0.001))
                except (TypeError, ValueError):
                    fee_rate = 0.001

            # 计算 unrealized_pnl
            unrealized_pnl = 0.0
            if client is not None and symbol and net_position != 0:
                try:
                    current_price = await self._get_current_price(symbol, client)
                except Exception as e:
                    logger.warning(f"heartbeat_snapshot: 获取 {symbol} 当前价失败: {e}")
                    current_price = 0.0
                if current_price:
                    # 兜底：avg_buy_price=0 时不计算（避免极端负值）
                    if avg_buy_price == 0 and net_position > 0:
                        unrealized_pnl = 0.0
                    else:
                        unrealized_pnl = (current_price - avg_buy_price) * net_position
                        unrealized_pnl -= abs(net_position) * current_price * fee_rate

            total_pnl = realized_pnl + unrealized_pnl
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
                avg_buy_price=avg_buy_price,
                total_fee=total_fee,
                order_count=order_count,
            )
            db.add(record)
            db.commit()

            return PnlSnapshot(
                strategy_instance_id=strategy_instance_id,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                total_pnl=total_pnl,
                equity=equity,
                net_position=net_position,
                avg_buy_price=avg_buy_price,
                total_fee=total_fee,
                order_count=order_count,
                recorded_at=recorded_at,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _qty(o: Order) -> float:
        """成交数量：actual_qty 优先，回退 fill_sz → filled_quantity → quantity。"""
        if o.actual_qty is not None:
            return float(o.actual_qty)
        if o.fill_sz is not None:
            return float(o.fill_sz)
        if o.filled_quantity is not None:
            return float(o.filled_quantity)
        return float(o.quantity or 0)

    @staticmethod
    def _px(o: Order) -> float:
        """成交价：fill_px 优先，回退 price。"""
        if o.fill_px is not None:
            return float(o.fill_px)
        return float(o.price or 0)

    @staticmethod
    def _compute_pnl_metrics(buy_orders, sell_orders, all_orders):
        """从订单列表计算 PnL 指标（掌柜算法核心）"""
        buy_total = sum(PnlAccountingEngine._px(o) * PnlAccountingEngine._qty(o) for o in buy_orders)
        sell_total = sum(PnlAccountingEngine._px(o) * PnlAccountingEngine._qty(o) for o in sell_orders)
        buy_qty_sum = sum(PnlAccountingEngine._qty(o) for o in buy_orders)
        sell_qty_sum = sum(PnlAccountingEngine._qty(o) for o in sell_orders)
        total_fee = sum(float(o.fee or 0) for o in all_orders)
        total_pnl = sell_total - buy_total - total_fee
        matched_qty = min(buy_qty_sum, sell_qty_sum)
        avg_buy_px = buy_total / buy_qty_sum if buy_qty_sum else 0
        avg_sell_px = sell_total / sell_qty_sum if sell_qty_sum else 0
        avg_fee_per_unit = total_fee / (buy_qty_sum + sell_qty_sum) if (buy_qty_sum + sell_qty_sum) else 0
        realized_pnl = matched_qty * (avg_sell_px - avg_buy_px) - matched_qty * avg_fee_per_unit
        unrealized_pnl = total_pnl - realized_pnl
        net_position = buy_qty_sum - sell_qty_sum
        return {
            'buy_total': buy_total, 'sell_total': sell_total, 'total_fee': total_fee,
            'total_pnl': total_pnl, 'matched_qty': matched_qty,
            'avg_buy_price': avg_buy_px, 'avg_sell_price': avg_sell_px,
            'realized_pnl': realized_pnl, 'unrealized_pnl': unrealized_pnl,
            'net_position': net_position, 'order_count': len(all_orders),
        }

    async def _get_current_price(self, symbol: str, client: OKXClient) -> float:
        """调用 client.get_ticker(symbol) 获取最新价。"""
        tickers = await client.get_ticker(symbol)
        if tickers:
            return float(tickers[0].get("last", 0))
        return 0.0

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


pnl_accounting_engine = PnlAccountingEngine()
