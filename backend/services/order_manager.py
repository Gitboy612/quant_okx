import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)


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
    ct_val: float = 1.0
    ct_type: str = ""
    settle_ccy: str = ""
    actual_qty: float = 0.0

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
            "ct_val": self.ct_val,
            "ct_type": self.ct_type,
            "settle_ccy": self.settle_ccy,
            "actual_qty": self.actual_qty,
        }


class OrderManager:
    def __init__(self, db_session_factory, okx_client, strategy_instance_id: int, account_id: int, instrument_cache=None):
        self._db_session_factory = db_session_factory
        self._okx_client = okx_client
        self._strategy_instance_id = strategy_instance_id
        self._account_id = account_id
        self._orders: dict[str, OrderInfo] = {}
        if instrument_cache is None:
            from services.instrument_cache import instrument_cache as _instrument_cache
            instrument_cache = _instrument_cache
        self._instrument_cache = instrument_cache
        self._callbacks: dict[str, list[Callable]] = {
            "filled": [],
            "canceled": [],
            "partial_fill": [],
            "any": [],
        }
        self._running: bool = True
        # 持有持久化 task 的强引用，避免被事件循环弱引用 GC 回收
        self._pending_persist_tasks: set = set()
        # SubTask 7.4: 下单/成交时间戳（内存字典，避免 DB 迁移）
        self._place_ts_map: dict[str, float] = {}
        self._fill_ts_map: dict[str, float] = {}
        # 净持仓状态（用于未实现盈亏计算）
        self._net_position: float = 0.0       # 净持仓量（买入累计 - 卖出累计）
        self._avg_buy_price: float = 0.0       # 加权平均买入价
        self._total_buy_qty: float = 0.0       # 累计买入量
        self._total_buy_value: float = 0.0     # 累计买入价值（qty × px）
        self._total_sell_qty: float = 0.0      # 累计卖出量

    async def add_order(self, ordId: str, clOrdId: str, symbol: str, side: str, px: str, sz: str, state: str = "live"):
        # 获取 instrument 元数据
        inst_info = await self._instrument_cache.get_instrument(symbol, self._okx_client)
        ct_val = inst_info.get("ctVal", 1.0)
        ct_type = inst_info.get("ctType") or ""
        settle_ccy = inst_info.get("settleCcy") or ""
        sz_float = float(sz) if sz else 0.0
        actual_qty = sz_float * ct_val  # 合约：张数 × 面值；现货：ctVal=1.0，actual_qty=sz
        order = OrderInfo(
            ordId=ordId,
            clOrdId=clOrdId,
            symbol=symbol,
            side=side,
            px=px,
            sz=sz,
            state=state,
            ct_val=ct_val,
            ct_type=ct_type,
            settle_ccy=settle_ccy,
            actual_qty=actual_qty,
        )
        # SubTask 7.4: 记录下单时间戳
        self._place_ts_map[ordId] = time.time()
        self._orders[ordId] = order
        self._async_persist(order)
        return order

    async def add_batch(self, orders: list[dict]):
        for o in orders:
            await self.add_order(
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
        # 若更新了 fillSz 且 actual_qty 未被显式传入，则根据 fillSz 和 ct_val 重新计算 actual_qty
        # 注意：不能用 not order.actual_qty 守卫，因为 add_order 已设置 actual_qty=sz*ct_val，
        # 会导致成交后 actual_qty 永远不更新为 fillSz*ct_val（委托量≠成交量时产生误差）
        if "fillSz" in kwargs and "actual_qty" not in kwargs:
            fill_sz_float = float(order.fillSz) if order.fillSz else 0.0
            sz_float = float(order.sz) if order.sz else 0.0
            base_qty = fill_sz_float if fill_sz_float > 0 else sz_float
            order.actual_qty = base_qty * (order.ct_val or 1.0)
        new_state = order.state
        if new_state != old_state:
            if new_state == "filled":
                # SubTask 7.4: 记录成交时间戳
                self._fill_ts_map[ordId] = time.time()
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
        # 优先用 actual_qty（已乘 ct_val），回退到 fillSz × ct_val
        if order.actual_qty and order.actual_qty > 0:
            fill_qty = order.actual_qty
        else:
            fill_sz = float(order.fillSz) if order.fillSz else (float(order.sz) if order.sz else 0)
            fill_qty = fill_sz * (order.ct_val or 1.0)
        fill_px = float(order.fillPx) if order.fillPx else (float(order.px) if order.px else 0)
        if fill_qty <= 0:
            return

        if order.side == "buy":
            self._total_buy_qty += fill_qty
            self._total_buy_value += fill_qty * fill_px
            if self._total_buy_qty > 0:
                self._avg_buy_price = self._total_buy_value / self._total_buy_qty
            self._net_position += fill_qty
        elif order.side == "sell":
            self._total_sell_qty += fill_qty
            self._net_position -= fill_qty

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

    def get_order_latency(self, ordId: str) -> float | None:
        """返回下单到成交的延迟（秒）。无记录返回 None（SubTask 7.4）。"""
        place_ts = self._place_ts_map.get(ordId)
        fill_ts = self._fill_ts_map.get(ordId)
        if place_ts is None or fill_ts is None:
            return None
        return fill_ts - place_ts

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
                        ct_val=row.ct_val if row.ct_val is not None else 1.0,
                        ct_type=row.ct_type or "",
                        settle_ccy=row.settle_ccy or "",
                        actual_qty=row.actual_qty if row.actual_qty is not None else 0.0,
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
                existing.ct_val = order.ct_val
                existing.ct_type = order.ct_type or None
                existing.settle_ccy = order.settle_ccy or None
                existing.actual_qty = order.actual_qty
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
                    ct_val=order.ct_val,
                    ct_type=order.ct_type or None,
                    settle_ccy=order.settle_ccy or None,
                    actual_qty=order.actual_qty,
                )
                db.add(new_order)
            db.commit()
        except Exception as e:
            db.rollback()
            # 并发竞争：两个线程同时 INSERT 同一 order_id，回退为 UPDATE
            if "UNIQUE constraint" in str(e) and order.ordId:
                try:
                    from models.order import Order as _Order
                    existing = db.query(_Order).filter(_Order.order_id == order.ordId).first()
                    if existing:
                        existing.state = order.state
                        existing.status = self._map_state_to_status(order.state)
                        existing.fill_px = float(order.fillPx) if order.fillPx else None
                        existing.fill_sz = float(order.fillSz) if order.fillSz else None
                        existing.fee = float(order.fee) if order.fee else None
                        existing.filled_quantity = float(order.fillSz) if order.fillSz else 0
                        existing.update_time = order.uTime
                        existing.updated_at = datetime.now(timezone.utc)
                        db.commit()
                        return  # 竞争修复成功，不记录错误
                except Exception as retry_err:
                    db.rollback()
                    logger.warning(f"_persist_to_db 竞争重试失败 ordId={order.ordId}: {retry_err}")
            # 不再静默吞掉异常：记录日志 + 写 strategy_event，确保 orphan 订单可被发现与回补
            logger.error(
                f"OrderManager._persist_to_db 失败 strategy_instance_id={self._strategy_instance_id} "
                f"ordId={order.ordId} symbol={order.symbol} side={order.side}: {e}",
                exc_info=True,
            )
            self._record_persist_failure_event(order, str(e))
        finally:
            db.close()

    def _record_persist_failure_event(self, order: OrderInfo, error_msg: str):
        """订单持久化失败时写入 strategy_event，供审计/监控链路消费。"""
        try:
            db = self._db_session_factory()
            try:
                from models.strategy_event import StrategyEvent
                event = StrategyEvent(
                    strategy_instance_id=self._strategy_instance_id,
                    event_type="order_persist_failed",
                    message=(
                        f"订单持久化失败 ordId={order.ordId} symbol={order.symbol} "
                        f"side={order.side} state={order.state}: {error_msg}"
                    ),
                    details=__import__("json").dumps({
                        "ordId": order.ordId,
                        "clOrdId": order.clOrdId,
                        "symbol": order.symbol,
                        "side": order.side,
                        "state": order.state,
                        "error": error_msg,
                    }, ensure_ascii=False),
                    created_at=datetime.now(timezone.utc),
                )
                db.add(event)
                db.commit()
            except Exception:
                db.rollback()
        except Exception:
            pass
        finally:
            try:
                db.close()
            except Exception:
                pass

    @staticmethod
    def _map_state_to_status(state: str) -> str:
        mapping = {
            "live": "live",
            "filled": "filled",
            "canceled": "canceled",
            "partially_filled": "live",
        }
        return mapping.get(state, "live")