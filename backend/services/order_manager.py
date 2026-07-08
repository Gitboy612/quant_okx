import asyncio
import threading
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class OrderInfo:
    ordId: str
    clOrdId: str = ""
    symbol: str = ""
    side: str = ""
    px: str = ""
    sz: str = ""
    state: str = "live"
    fillPx: str = ""
    fillSz: str = ""
    fee: str = ""
    cTime: str = ""
    uTime: str = ""

    def to_dict(self) -> dict:
        return {
            "ordId": self.ordId,
            "clOrdId": self.clOrdId,
            "symbol": self.symbol,
            "side": self.side,
            "px": self.px,
            "sz": self.sz,
            "state": self.state,
            "fillPx": self.fillPx,
            "fillSz": self.fillSz,
            "fee": self.fee,
            "cTime": self.cTime,
            "uTime": self.uTime,
        }


class OrderManager:
    def __init__(self, db_session_factory, okx_client, strategy_instance_id: int, account_id: int):
        self._db_session_factory = db_session_factory
        self._okx_client = okx_client
        self._strategy_instance_id = strategy_instance_id
        self._account_id = account_id
        self._orders: dict[str, OrderInfo] = {}
        self._callbacks: dict[str, list[Callable]] = {
            "filled": [],
            "canceled": [],
            "partial_fill": [],
            "any": [],
        }
        self._running: bool = True

    def add_order(self, ordId: str, clOrdId: str, symbol: str, side: str, px: str, sz: str, state: str = "live"):
        order = OrderInfo(
            ordId=ordId,
            clOrdId=clOrdId,
            symbol=symbol,
            side=side,
            px=px,
            sz=sz,
            state=state,
        )
        self._orders[ordId] = order
        self._async_persist(order)
        return order

    def add_batch(self, orders: list[dict]):
        for o in orders:
            self.add_order(
                ordId=o.get("ordId", ""),
                clOrdId=o.get("clOrdId", ""),
                symbol=o.get("symbol", ""),
                side=o.get("side", ""),
                px=o.get("px", ""),
                sz=o.get("sz", ""),
                state=o.get("state", "live"),
            )

    def update_order(self, ordId: str, **kwargs):
        if ordId not in self._orders:
            return None
        order = self._orders[ordId]
        old_state = order.state
        for key, value in kwargs.items():
            if hasattr(order, key):
                setattr(order, key, value)
        new_state = order.state
        if new_state != old_state:
            if new_state == "filled":
                self._trigger_callbacks("filled", order)
            elif new_state == "canceled":
                self._trigger_callbacks("canceled", order)
            elif new_state == "partially_filled":
                self._trigger_callbacks("partial_fill", order)
            self._trigger_callbacks("any", order)
        self._async_persist(order)
        return order

    def get_order(self, ordId: str) -> OrderInfo | None:
        return self._orders.get(ordId)

    def get_active_orders(self) -> list[OrderInfo]:
        return [o for o in self._orders.values() if o.state in ("live", "partially_filled")]

    def get_all_orders(self) -> list[OrderInfo]:
        return list(self._orders.values())

    async def cancel_all(self, symbol: str) -> int:
        cancelled_count = 0
        active_orders = self.get_active_orders()
        for order in active_orders:
            if order.symbol != symbol:
                continue
            resp = await self._okx_client.cancel_order(symbol, order.ordId)
            if resp.get("code") == "0":
                self.update_order(order.ordId, state="canceled")
                cancelled_count += 1
        return cancelled_count

    def load_from_db(self) -> int:
        db = self._db_session_factory()
        try:
            from models.order import Order
            orders = db.query(Order).filter(
                Order.account_id == self._account_id,
                Order.status.in_(["live"]),
            ).all()
            count = 0
            for row in orders:
                if row.order_id and row.order_id not in self._orders:
                    order_info = OrderInfo(
                        ordId=row.order_id,
                        clOrdId=row.cl_ord_id or "",
                        symbol=row.symbol,
                        side=row.side,
                        px=str(row.price) if row.price else "",
                        sz=str(row.quantity) if row.quantity else "",
                        state=row.state or "live",
                        fillPx=str(row.fill_px) if row.fill_px else "",
                        fillSz=str(row.fill_sz) if row.fill_sz else "",
                        fee=str(row.fee) if row.fee else "",
                        uTime=row.update_time or "",
                    )
                    self._orders[row.order_id] = order_info
                    count += 1
            return count
        finally:
            db.close()

    def on(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callbacks(self, event: str, order: OrderInfo):
        for cb in self._callbacks.get(event, []):
            try:
                result = cb(order)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception:
                pass

    def _async_persist(self, order: OrderInfo):
        t = threading.Thread(target=self._persist_to_db, args=(order,), daemon=True)
        t.start()

    def _persist_to_db(self, order: OrderInfo):
        db = self._db_session_factory()
        try:
            from models.order import Order

            existing = db.query(Order).filter(Order.order_id == order.ordId).first()
            if existing:
                existing.state = order.state
                existing.fill_px = float(order.fillPx) if order.fillPx else None
                existing.fill_sz = float(order.fillSz) if order.fillSz else None
                existing.fee = float(order.fee) if order.fee else None
                existing.filled_quantity = float(order.fillSz) if order.fillSz else 0
                existing.status = self._map_state_to_status(order.state)
                existing.update_time = order.uTime
            else:
                new_order = Order(
                    strategy_instance_id=self._strategy_instance_id,
                    account_id=self._account_id,
                    symbol=order.symbol,
                    order_id=order.ordId,
                    cl_ord_id=order.clOrdId,
                    side=order.side,
                    order_type="limit",
                    price=float(order.px) if order.px else None,
                    quantity=float(order.sz) if order.sz else None,
                    filled_quantity=float(order.fillSz) if order.fillSz else 0,
                    fill_px=float(order.fillPx) if order.fillPx else None,
                    fill_sz=float(order.fillSz) if order.fillSz else None,
                    fee=float(order.fee) if order.fee else None,
                    state=order.state,
                    status=self._map_state_to_status(order.state),
                    update_time=order.uTime,
                )
                db.add(new_order)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def _map_state_to_status(state: str) -> str:
        mapping = {
            "live": "live",
            "filled": "filled",
            "canceled": "canceled",
            "partially_filled": "live",
        }
        return mapping.get(state, "live")