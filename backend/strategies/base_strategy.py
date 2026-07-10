import asyncio
import json
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from services.okx_client import OKXClient
from database import SessionLocal

if TYPE_CHECKING:
    from services.order_manager import OrderManager
    from services.okx_ws_client import OKXWsClient


class BaseStrategy(ABC):
    def __init__(self, instance_id: int, params: dict, client: OKXClient, db_session_factory, account_id: int | None = None,
                 order_manager: "OrderManager | None" = None, ws_client: "OKXWsClient | None" = None):
        self.instance_id = instance_id
        self.params = params
        self.client = client
        self.db_session_factory = db_session_factory
        self.account_id = account_id
        self._running = False
        self._paused = False
        self._realized_pnl = 0.0
        self._buy_trades: list[dict] = []
        self._initial_equity = 0.0
        self._last_pnl_record_ts: float = 0.0
        self._last_pnl_total: float = 0.0
        self._fee_rate = float(self.params.get("fee_rate", 0.001))

        # OrderManager setup
        if order_manager is not None:
            self.order_manager = order_manager
        else:
            from services.order_manager import OrderManager
            self.order_manager = OrderManager(db_session_factory, client, instance_id, account_id or 0)

        # WebSocket client
        self._ws_client = ws_client

    @property
    def ws_client(self):
        return self._ws_client

    @ws_client.setter
    def ws_client(self, value):
        self._ws_client = value

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

    async def start(self):
        self._running = True
        self._paused = False
        # Start WebSocket if available
        if self._ws_client and not self._ws_client.is_connected:
            await self._ws_client.connect()
            symbol = self.params.get("symbol", "")
            if symbol:
                inst_type = "SWAP" if "-SWAP" in symbol else "SPOT"
                await self._ws_client.subscribe_orders(inst_type, symbol)
        # 注册 WebSocket 订单更新回调，实现实时订单状态同步
        if self._ws_client:
            self._ws_client.on_order_update(self._on_ws_order_update)
        self._record_event("started", "策略已启动")

    def _on_ws_order_update(self, ord_id: str, state: str, order_data: dict):
        """WebSocket 订单更新回调：解析订单数据并同步到 OrderManager。

        由 OKXWsClient._handle_data 在收到 orders 频道推送时调用。
        异常被捕获并记录事件，不抛出以避免阻塞 WS message_loop。
        """
        try:
            fill_px = order_data.get("fillPx", "")
            fill_sz = order_data.get("fillSz", "")
            fee = order_data.get("fee", "")
            self.order_manager.update_order(
                ord_id,
                state=state,
                fillPx=fill_px,
                fillSz=fill_sz,
                fee=fee,
            )
        except Exception as e:
            self._record_event(
                "error",
                f"WS 订单回调处理异常: ordId={ord_id} state={state} err={e}",
                {"ord_id": ord_id, "state": state},
            )

    def pause(self):
        self._paused = True
        symbol = self.params.get("symbol", "")
        import asyncio as _asyncio
        try:
            _asyncio.get_running_loop()
            _asyncio.ensure_future(self._pause_async(symbol))
        except RuntimeError:
            cancelled = _asyncio.run(self.order_manager.cancel_all(symbol))
            self._record_event("paused", f"策略已暂停, 撤销 {cancelled} 笔订单")
            self.record_final_pnl()

    async def _pause_async(self, symbol: str):
        cancelled = await self.order_manager.cancel_all(symbol)
        self._record_event("paused", f"策略已暂停, 撤销 {cancelled} 笔订单")
        self.record_final_pnl()

    def resume(self):
        self._paused = False
        self._record_event("resumed", "策略已恢复")

    def stop(self):
        self._running = False
        self._paused = False
        symbol = self.params.get("symbol", "")
        import asyncio as _asyncio
        try:
            _asyncio.get_running_loop()
            _asyncio.ensure_future(self._stop_async(symbol))
        except RuntimeError:
            cancelled = _asyncio.run(self.order_manager.cancel_all(symbol))
            self._record_event("stopped", f"策略已停止, 撤销 {cancelled} 笔订单")
            self.record_final_pnl()

    async def _stop_async(self, symbol: str):
        cancelled = await self.order_manager.cancel_all(symbol)
        self._record_event("stopped", f"策略已停止, 撤销 {cancelled} 笔订单")
        self.record_final_pnl()

    def add_realized_pnl(self, pnl: float):
        """Accumulate realized PnL from a completed trade."""
        self._realized_pnl += pnl

    def get_realized_pnl(self) -> float:
        return self._realized_pnl

    def restore_realized_pnl(self, pnl: float):
        """Restore realized PnL from DB after restart."""
        self._realized_pnl = pnl

    async def sync_orders(self, symbol: str) -> dict[str, dict[str, str]]:
        """
        Sync unfilled orders from DB on strategy restart using OrderManager.
        Queries OKX for each order's current status, updates DB,
        and returns still-active orders for re-tracking.
        Returns: {"buy": {idx: order_id}, "sell": {idx: order_id}}
        """
        count = self.order_manager.load_from_db()

        active_buy: dict[str, str] = {}
        active_sell: dict[str, str] = {}

        for order in self.order_manager.get_active_orders():
            if order.symbol != symbol:
                continue
            try:
                info = await self.client.get_order(symbol, order.ordId)
                if info and len(info) > 0:
                    state = info[0].get("state", "")
                    if state == "filled":
                        self.order_manager.update_order(order.ordId, state="filled",
                            fillPx=info[0].get("fillPx", ""),
                            fillSz=info[0].get("fillSz", ""),
                            fee=info[0].get("fee", ""))
                        self._record_event("order_filled",
                            f"{order.side.upper()} 已成交(恢复): {symbol} ordId={order.ordId} px={order.px} qty={order.sz}",
                            {"order_id": order.ordId, "side": order.side, "price": order.px, "quantity": order.sz})
                    elif state == "canceled":
                        self.order_manager.update_order(order.ordId, state="canceled")
                        self._record_event("order_canceled",
                            f"{order.side.upper()} 已撤销(恢复): {symbol} ordId={order.ordId}",
                            {"order_id": order.ordId, "side": order.side})
                    elif state in ("live", "partially_filled"):
                        if order.side == "buy":
                            active_buy[order.ordId] = order.side
                        else:
                            active_sell[order.ordId] = order.side
                        self._record_event("order_placed",
                            f"{order.side.upper()} 订单恢复跟踪: {symbol} ordId={order.ordId} px={order.px} qty={order.sz}",
                            {"order_id": order.ordId, "side": order.side, "price": order.px, "quantity": order.sz, "status": "live"})
                else:
                    self.order_manager.update_order(order.ordId, state="canceled")
                    self._record_event("order_canceled",
                        f"{order.side.upper()} 订单不存在(恢复): {symbol} ordId={order.ordId}",
                        {"order_id": order.ordId, "side": order.side})
            except Exception as e:
                print(f"[sync_orders] Error syncing order {order.ordId}: {e}")
                if order.side == "buy":
                    active_buy[order.ordId] = order.side
                else:
                    active_sell[order.ordId] = order.side

        self._record_event("started",
            f"订单同步完成: 加载 {count} 笔订单, {len(self.order_manager.get_active_orders())} 笔仍活跃",
            {"total_loaded": count, "still_active": len(self.order_manager.get_active_orders())})

        return {"buy": active_buy, "sell": active_sell}

    @property
    def is_running(self):
        return self._running and not self._paused

    @property
    def is_paused(self):
        return self._paused

    def record_order(self, symbol: str, side: str, order_type: str, price: float, quantity: float, order_id: str = "", status: str = "filled"):
        # Delegate to OrderManager for persistence
        if status == "live":
            self.order_manager.add_order(
                ordId=order_id,
                clOrdId="",
                symbol=symbol,
                side=side,
                px=str(price),
                sz=str(quantity),
                state="live",
            )
        elif order_id:
            update_kwargs = {"state": status}
            if status == "filled":
                update_kwargs["fillSz"] = str(quantity)
                update_kwargs["fillPx"] = str(price)
            self.order_manager.update_order(order_id, **update_kwargs)

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

    def _should_record_pnl(self, total_pnl: float, interval_seconds: float = 60.0, change_threshold: float = 0.01) -> bool:
        """判断是否应写入 PnL 记录：间隔 ≥ 60s 或 total_pnl 变化超阈值。"""
        import time
        now = time.time()
        if now - self._last_pnl_record_ts >= interval_seconds:
            return True
        if self._last_pnl_record_ts > 0:
            delta = abs(total_pnl - self._last_pnl_total)
            if self._last_pnl_total != 0:
                # 有基准值时用相对变化率
                if delta / abs(self._last_pnl_total) > change_threshold:
                    return True
            else:
                # 无基准值（首次从0变化）时用绝对变化量
                if delta > 0.01:
                    return True
        return False

    def _mark_pnl_recorded(self, total_pnl: float):
        """记录已写入 PnL，更新时间戳与上次值。"""
        import time
        self._last_pnl_record_ts = time.time()
        self._last_pnl_total = total_pnl

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
        except Exception as e:
            db.rollback()
            print(f"[BaseStrategy] record_pnl error: {e}")
        finally:
            db.close()

    def record_final_pnl(self):
        """策略停止时写一条 unrealized_pnl=0 的最终 PnL 记录。"""
        try:
            from models.pnl import PnlRecord
            db = self.db_session_factory()
            try:
                # 读取最新 PnlRecord 保留 realized 和 equity
                latest = db.query(PnlRecord).filter(
                    PnlRecord.strategy_instance_id == self.instance_id
                ).order_by(PnlRecord.recorded_at.desc()).first()

                realized = latest.realized_pnl if latest else self.get_realized_pnl()
                equity = latest.equity if latest else 0

                last_unrealized = latest.unrealized_pnl if latest else 0
                record = PnlRecord(
                    account_id=self.account_id,
                    strategy_instance_id=self.instance_id,
                    equity=equity,
                    unrealized_pnl=last_unrealized,  # 保留最后浮动盈亏（不再清零）
                    realized_pnl=realized,
                    total_pnl=last_unrealized + realized,
                    is_final=True,
                    recorded_at=datetime.now(timezone.utc),
                )
                db.add(record)
                db.commit()
                self._record_event("stopped", f"策略已停止，最终 PnL: equity={equity}, realized={realized}, unrealized={last_unrealized}")
            finally:
                db.close()
        except Exception as e:
            print(f"[BaseStrategy] record_final_pnl error: {e}")

    # —— 可拼接 DSL 钩子（默认空实现，供 ComposableStrategy 编排调用）——
    async def on_start(self, ctx=None) -> None:
        """策略启动时调用（放置初始网格等）。默认空。"""
        pass

    async def on_tick(self, ctx=None) -> None:
        """每个 tick 调用（监控 + 记录 PnL）。默认空。"""
        pass

    async def on_order_filled(self, order_info, ctx=None) -> None:
        """订单成交时调用。默认空。"""
        pass

    async def on_pause(self, ctx=None) -> None:
        """暂停时调用（撤挂单但保留持仓）。默认空。"""
        pass

    async def on_resume(self, ctx=None) -> None:
        """恢复时调用（重新挂网格）。默认空。"""
        pass

    async def on_stop(self, ctx=None) -> None:
        """停止时调用。默认空。"""
        pass

    def get_theoretical_position(self, ctx=None) -> float:
        """返回当前价位下的理论持仓量。供 rebalance_position 动作使用。默认 0。"""
        return 0.0

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