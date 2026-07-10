import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
        # 持有持久化 task 的强引用，避免被事件循环弱引用 GC 回收
        self._pending_persist_tasks: set = set()
        # 净持仓状态（用于未实现盈亏计算）
        self._net_position: float = 0.0       # 净持仓量（买入累计 - 卖出累计）
        self._avg_buy_price: float = 0.0       # 加权平均买入价
        self._total_buy_qty: float = 0.0       # 累计买入量
        self._total_buy_value: float = 0.0     # 累计买入价值（qty × px）
        self._total_sell_qty: float = 0.0      # 累计卖出量

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
                self._update_position_on_filled(order)
                self._trigger_callbacks("filled", order)
            elif new_state == "canceled":
                self._trigger_callbacks("canceled", order)
            elif new_state == "partially_filled":
                self._trigger_callbacks("partial_fill", order)
            self._trigger_callbacks("any", order)
        self._async_persist(order)
        return order

    def _update_position_on_filled(self, order: OrderInfo):
        """订单成交时更新净持仓状态。

        买单：累加买入量与价值，更新加权均价
        卖单：扣减净持仓（不改变加权均价，实现 FIFO 平仓）
        """
        fill_sz = float(order.fillSz) if order.fillSz else (float(order.sz) if order.sz else 0)
        fill_px = float(order.fillPx) if order.fillPx else (float(order.px) if order.px else 0)
        if fill_sz <= 0:
            return

        if order.side == "buy":
            self._total_buy_qty += fill_sz
            self._total_buy_value += fill_sz * fill_px
            if self._total_buy_qty > 0:
                self._avg_buy_price = self._total_buy_value / self._total_buy_qty
            self._net_position += fill_sz
        elif order.side == "sell":
            self._total_sell_qty += fill_sz
            self._net_position -= fill_sz

    def get_position_summary(self) -> tuple[float, float]:
        """返回当前净持仓与加权平均买入价，供策略计算未实现盈亏。"""
        return (self._net_position, self._avg_buy_price)

    def restore_position(self, net_position: float, avg_buy_price: float):
        """策略重启时从 DB 恢复持仓状态。"""
        self._net_position = net_position
        self._avg_buy_price = avg_buy_price

    def get_order(self, ordId: str) -> OrderInfo | None:
        return self._orders.get(ordId)

    def get_order_fee(self, ordId: str) -> float:
        """返回指定订单的手续费，供已实现盈亏扣费使用。"""
        order = self._orders.get(ordId)
        if order and order.fee:
            try:
                return float(order.fee)
            except (ValueError, TypeError):
                return 0.0
        return 0.0

    def get_order_fill_px(self, ordId: str) -> float:
        """返回指定订单的实际成交价，供已实现盈亏计算使用。"""
        order = self._orders.get(ordId)
        if order and order.fillPx:
            try:
                return float(order.fillPx)
            except (ValueError, TypeError):
                return 0.0
        return 0.0

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
                    try:
                        asyncio.create_task(result)
                    except RuntimeError:
                        # 无运行中的 event loop，跳过协程调度
                        pass
            except Exception:
                pass

    def _async_persist(self, order: OrderInfo):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # 无运行中的 event loop（如同步调用上下文），直接同步持久化
            self._persist_to_db(order)
            return
        task = asyncio.create_task(asyncio.to_thread(self._persist_to_db, order))
        self._pending_persist_tasks.add(task)
        task.add_done_callback(self._pending_persist_tasks.discard)

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
                existing.updated_at = datetime.now(timezone.utc)
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