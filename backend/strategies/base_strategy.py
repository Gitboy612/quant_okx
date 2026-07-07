import json
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from services.okx_client import OKXClient
from database import SessionLocal


class BaseStrategy(ABC):
    def __init__(self, instance_id: int, params: dict, client: OKXClient, db_session_factory, account_id: int | None = None):
        self.instance_id = instance_id
        self.params = params
        self.client = client
        self.db_session_factory = db_session_factory
        self.account_id = account_id
        self._running = False
        self._paused = False
        self._active_orders: dict[str, str] = {}  # order_id -> instId (symbol)
        self._realized_pnl = 0.0  # track accumulated realized PnL
        self._buy_trades: list[dict] = []  # track buy trades for PnL calc
        self._initial_equity = 0.0  # initial equity, set once at strategy start

    def _record_event(self, event_type: str, message: str, details: dict | None = None):
        """Record a strategy event to the database."""
        try:
            from models.strategy_event import StrategyEvent
            db = self.db_session_factory()
            try:
                event = StrategyEvent(
                    strategy_instance_id=self.instance_id,
                    event_type=event_type,
                    message=message,
                    details=json.dumps(details, ensure_ascii=False) if details else None,
                )
                db.add(event)
                db.commit()
            finally:
                db.close()
        except Exception:
            pass

    @abstractmethod
    async def execute(self):
        pass

    @abstractmethod
    async def validate_params(self) -> bool:
        pass

    def start(self):
        self._running = True
        self._paused = False
        self._record_event("started", "策略已启动")

    def pause(self):
        self._paused = True
        self._cancel_all_active_orders()
        self._record_event("paused", "策略已暂停")

    def resume(self):
        self._paused = False
        self._record_event("resumed", "策略已恢复")

    def stop(self):
        self._running = False
        self._paused = False
        self._cancel_all_active_orders()
        self._record_event("stopped", "策略已停止")

    def _cancel_all_active_orders(self):
        """Cancel all tracked active orders when pausing or stopping."""
        cancelled = 0
        failed = 0
        total = len(self._active_orders)
        for order_id, inst_id in list(self._active_orders.items()):
            try:
                resp = self.client.cancel_order(inst_id, order_id)
                if resp.get("code") == "0":
                    cancelled += 1
                    self.record_order(inst_id, "cancel", "cancel", 0, 0, order_id=order_id, status="canceled")
                else:
                    failed += 1
                    print(f"[BaseStrategy] cancel order {order_id} failed: {resp.get('msg', '')}")
            except Exception as e:
                failed += 1
                print(f"[BaseStrategy] cancel order {order_id} error: {e}")
            self._active_orders.pop(order_id, None)
        if cancelled > 0:
            print(f"[BaseStrategy] Cancelled {cancelled} active orders for strategy #{self.instance_id}")
            self._record_event("order_canceled", f"批量撤单完成: 成功 {cancelled}/{total}",
                               {"cancelled": cancelled, "failed": failed, "total": total})

    def track_order(self, inst_id: str, order_id: str):
        """Track an active order so it can be cancelled on pause/stop."""
        if order_id:
            self._active_orders[order_id] = inst_id

    def untrack_order(self, order_id: str):
        """Remove an order from tracking (e.g. when it's filled)."""
        self._active_orders.pop(order_id, None)

    def add_realized_pnl(self, pnl: float):
        """Accumulate realized PnL from a completed trade."""
        self._realized_pnl += pnl

    def get_realized_pnl(self) -> float:
        return self._realized_pnl

    def restore_realized_pnl(self, pnl: float):
        """Restore realized PnL from DB after restart."""
        self._realized_pnl = pnl

    def sync_orders(self, symbol: str) -> dict[str, dict[str, str]]:
        """
        Sync unfilled orders from DB on strategy restart.
        Queries OKX for each order's current status, updates DB,
        and returns still-active orders for re-tracking.
        Returns: {"buy": {idx: order_id}, "sell": {idx: order_id}}
        """
        from models.order import Order
        db = self.db_session_factory()
        active_buy: dict[str, str] = {}
        active_sell: dict[str, str] = {}

        try:
            pending = db.query(Order).filter(
                Order.strategy_instance_id == self.instance_id,
                Order.status == "live"
            ).all()

            for order in pending:
                if not order.order_id:
                    continue
                try:
                    info = self.client.get_order(symbol, order.order_id)
                    if info and len(info) > 0:
                        state = info[0].get("state", "")
                        if state == "filled":
                            order.status = "filled"
                            order.filled_quantity = float(info[0].get("accFillSz", order.quantity))
                            self._record_event("order_filled",
                                f"{order.side.upper()} 已成交(恢复): {symbol} ordId={order.order_id} px={order.price} qty={order.quantity}",
                                {"order_id": order.order_id, "side": order.side, "price": order.price, "quantity": order.quantity})
                            # If this was a sell that filled, we need to calculate realized PnL
                            # The grid strategy will handle this in its own context
                        elif state == "canceled":
                            order.status = "canceled"
                            self._record_event("order_canceled",
                                f"{order.side.upper()} 已撤销(恢复): {symbol} ordId={order.order_id}",
                                {"order_id": order.order_id, "side": order.side})
                        elif state in ("live", "partially_filled"):
                            # Still active - re-track
                            self._active_orders[order.order_id] = symbol
                            active_buy[order.order_id] = order.side  # temporary, grid strategy will remap
                            self._record_event("order_placed",
                                f"{order.side.upper()} 订单恢复跟踪: {symbol} ordId={order.order_id} px={order.price} qty={order.quantity}",
                                {"order_id": order.order_id, "side": order.side, "price": order.price, "quantity": order.quantity, "status": "live"})
                    else:
                        # Order not found on OKX, mark as canceled
                        order.status = "canceled"
                        self._record_event("order_canceled",
                            f"{order.side.upper()} 订单不存在(恢复): {symbol} ordId={order.order_id}",
                            {"order_id": order.order_id, "side": order.side})
                except Exception as e:
                    print(f"[sync_orders] Error syncing order {order.order_id}: {e}")
                    # Keep as live, will be checked in main loop
                    self._active_orders[order.order_id] = symbol
                    active_buy[order.order_id] = order.side

            db.commit()
            self._record_event("started",
                f"订单同步完成: 恢复 {len(pending)} 笔未成交订单, {len(self._active_orders)} 笔仍活跃",
                {"total_pending": len(pending), "still_active": len(self._active_orders)})
        finally:
            db.close()

        return {"buy": active_buy, "sell": active_sell}

    @property
    def is_running(self):
        return self._running and not self._paused

    @property
    def is_paused(self):
        return self._paused

    def record_order(self, symbol: str, side: str, order_type: str, price: float, quantity: float, order_id: str = "", status: str = "filled"):
        from models.order import Order
        db = self.db_session_factory()
        try:
            order = Order(
                strategy_instance_id=self.instance_id,
                account_id=None,
                symbol=symbol,
                order_id=order_id,
                side=side,
                order_type=order_type,
                price=price,
                quantity=quantity,
                filled_quantity=quantity,
                status=status,
            )
            db.add(order)
            db.commit()
        finally:
            db.close()

        event_type_map = {
            "filled": "order_filled",
            "live": "order_placed",
            "canceled": "order_canceled",
            "cancel": "order_canceled",
        }
        event_type = event_type_map.get(status, "order_placed")
        self._record_event(event_type,
                           f"{side.upper()} {order_type} {status}: {symbol} qty={quantity} px={price}",
                           {"symbol": symbol, "side": side, "order_type": order_type,
                            "price": price, "quantity": quantity, "order_id": order_id, "status": status})

    def record_pnl(self, equity: float, unrealized_pnl: float, realized_pnl: float):
        from models.pnl import PnlRecord
        db = self.db_session_factory()
        try:
            record = PnlRecord(
                account_id=self.account_id,
                strategy_instance_id=self.instance_id,
                equity=equity,
                unrealized_pnl=unrealized_pnl,
                realized_pnl=realized_pnl,
                total_pnl=unrealized_pnl + realized_pnl,
            )
            db.add(record)
            db.commit()
        finally:
            db.close()

        self._record_event("pnl_recorded",
                           f"equity={equity} unrealized={unrealized_pnl} realized={realized_pnl}",
                           {"equity": equity, "unrealized_pnl": unrealized_pnl, "realized_pnl": realized_pnl})

    def update_status(self, status: str):
        from models.strategy import StrategyInstance
        db = self.db_session_factory()
        try:
            instance = db.query(StrategyInstance).filter(StrategyInstance.id == self.instance_id).first()
            if instance:
                instance.status = status
                if status == "running":
                    instance.started_at = datetime.now(timezone.utc)
                elif status == "stopped":
                    instance.stopped_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()
