import asyncio
import json
import math
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from services.okx_client import OKXClient
from services.okx.exceptions import OKXAPIException
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
        # 保证金检查节流（SubTask 3.2）
        self._last_margin_check_ts: float = 0.0
        self._last_margin_check_result: bool = True
        # 仓位冲突检查节流（SubTask 5.1）
        self._last_conflict_check_ts: float = 0.0
        self._last_conflict_check_result: bool = True
        self._fee_rate = float(self.params.get("fee_rate", 0.001))

        # 旧实例参数迁移：检测缺失字段并补默认值（SubTask 1.4）
        self._param_migrated = False
        if "investment_amount" not in self.params:
            self.params.setdefault("investment_amount", 0)
            self.params.setdefault("lever", 1)
            self.params.setdefault("td_mode", "cross")
            self._param_migrated = True
            self._record_event(
                "param_migrated",
                "旧实例参数迁移：补默认 investment_amount=0, lever=1, td_mode=cross",
                {"added": {"investment_amount": 0, "lever": 1, "td_mode": "cross"}},
            )

        # 投入资金上限与持仓上限（SubTask 1.1）
        self.investment_amount = float(self.params.get("investment_amount", 0))
        self.max_position_value = float(self.params.get("max_position_value", 0))

        # 合约杠杆与持仓模式（SubTask 2.2）
        self.lever = int(self.params.get("lever", 1))
        self.td_mode = str(self.params.get("td_mode", "cross"))

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
        except Exception as e:
            # Bug 9: 增加 print 兜底，确保异常可见而非静默吞掉
            print(f"[BaseStrategy] _record_event error: type={event_type} msg={message} err={e}")

        # 异步触发多渠道通知（不阻塞策略主循环）
        # 只对配置了规则的事件类型触发；无规则时 notify 内部会直接返回 0
        self._fire_notification(event_type, message, details)

    def _fire_notification(self, event_type: str, message: str, details: dict | None):
        """异步分发通知，失败不影响策略主循环。

        使用 asyncio.create_task 调度，确保：
        - 在事件循环中运行时不阻塞调用方
        - 无事件循环时（如同步上下文调用 _record_event）降级为 fire-and-forget，
          异常被捕获并打印
        """
        try:
            from services.notification_service import notification_service
            title = f"[策略#{self.instance_id}] {event_type}"
            payload = details if isinstance(details, dict) else ({"raw": details} if details else {})
            # 添加策略上下文，便于通知中定位来源
            ctx = dict(payload)
            ctx.setdefault("strategy_instance_id", self.instance_id)
            if self.account_id is not None:
                ctx.setdefault("account_id", self.account_id)
            symbol = self.params.get("symbol") if isinstance(self.params, dict) else None
            if symbol:
                ctx.setdefault("symbol", symbol)
            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(
                    notification_service.notify(event_type, title, message, ctx)
                )
            except RuntimeError:
                # 无运行中的事件循环：无法 create_task，记录后跳过
                # （_record_event 多在异步上下文中被调用，此处为兜底）
                print(f"[BaseStrategy] _fire_notification: 无事件循环，跳过通知 type={event_type}")
        except Exception as e:
            print(f"[BaseStrategy] _fire_notification error: type={event_type} err={e}")

    def get_virtual_position(self) -> dict:
        """返回当前策略的虚拟持仓（SubTask 4.1）。

        优先从最新 PnlRecord 读取（DB 已有 net_position/avg_buy_price/realized_pnl）；
        无记录时返回 0/0/_realized_pnl。

        Returns:
            {"net_position": float, "avg_buy_price": float, "realized_pnl": float}
        """
        # 延迟导入 PnlRecord 避免循环依赖
        from models.pnl import PnlRecord
        try:
            db = self.db_session_factory()
            try:
                latest = (
                    db.query(PnlRecord)
                    .filter(PnlRecord.strategy_instance_id == self.instance_id)
                    .order_by(PnlRecord.recorded_at.desc())
                    .first()
                )
            finally:
                db.close()
        except Exception as e:
            print(f"[BaseStrategy] get_virtual_position 查询异常: {e}")
            return {
                "net_position": 0.0,
                "avg_buy_price": 0.0,
                "realized_pnl": float(self._realized_pnl or 0.0),
            }

        if latest is None:
            return {
                "net_position": 0.0,
                "avg_buy_price": 0.0,
                "realized_pnl": float(self._realized_pnl or 0.0),
            }
        return {
            "net_position": float(latest.net_position or 0),
            "avg_buy_price": float(latest.avg_buy_price or 0),
            "realized_pnl": float(latest.realized_pnl or 0),
        }

    def _get_current_position_value(self, symbol: str) -> float:
        """返回当前持仓名义价值（USDT），基于虚拟持仓 × 当前价（SubTask 4.1）。

        - 优先用 self._latest_price（若策略子类已设置）
        - 否则从 market_data_service.get_latest_ticker(symbol) 取最新价
        - 取价失败时按 avg_buy_price 兜底（避免返回 0 漏检）
        - net_position <= 0 时返回 0
        """
        virtual = self.get_virtual_position()
        net_position = virtual.get("net_position", 0.0)
        if not net_position or net_position <= 0:
            return 0.0

        # 1. 优先用策略子类维护的最新价
        price = 0.0
        latest_price = getattr(self, "_latest_price", None)
        if latest_price:
            try:
                price = float(latest_price)
            except (TypeError, ValueError):
                price = 0.0

        # 2. 回退到 market_data_service 缓存
        if price <= 0:
            try:
                from services.market_data_service import market_data_service
                ticker = market_data_service.get_latest_ticker(symbol)
                if ticker:
                    last_str = ticker.get("last") or ticker.get("lastPx")
                    if last_str:
                        price = float(last_str)
            except Exception as e:
                print(f"[BaseStrategy] _get_current_position_value 获取最新价异常: {e}")

        # 3. 最终兜底：用 avg_buy_price（至少反映持仓成本）
        if price <= 0:
            price = float(virtual.get("avg_buy_price", 0.0))

        return abs(net_position) * price

    def check_capital_limit(self, symbol: str, side: str, qty: float, price: float) -> bool:
        """资金上限校验：检查新单是否超出投入资金上限（SubTask 1.1）。

        - investment_amount=0 时不限制（兼容存量策略）
        - 上限 = investment_amount × (lever if 合约 else 1)
        - 总名义价值 = 当前持仓 + 新单名义价值
        - 超出时记录 capital_limit 事件并返回 False，未超返回 True
        """
        if self.investment_amount <= 0:
            return True  # 不限制

        new_value = qty * price
        current_value = self._get_current_position_value(symbol)
        total_value = current_value + new_value

        # 合约按杠杆放大可动用名义价值；现货杠杆为 1
        is_contract = "-SWAP" in symbol
        lever = float(self.params.get("lever", 1)) if is_contract else 1.0
        cap = self.investment_amount * lever

        if total_value > cap:
            self._record_event(
                "capital_limit",
                f"资金上限超出，拒绝下单: {symbol} {side} qty={qty} px={price} "
                f"new_value={new_value} current_value={current_value} total={total_value} cap={cap}",
                {
                    "symbol": symbol, "side": side, "qty": qty, "price": price,
                    "new_value": new_value, "current_value": current_value,
                    "total_value": total_value, "cap": cap,
                    "investment_amount": self.investment_amount, "lever": lever,
                },
            )
            return False
        return True

    async def place_order_with_capital_check(self, symbol: str, side: str, ord_type: str, sz, px=None, **kwargs) -> dict:
        """带资金上限校验的下单包装方法（SubTask 1.2）。

        先执行 check_capital_limit，通过则调用 client.place_order，
        否则返回拒绝响应 dict（不实际下单）。供策略调用替代直接 client.place_order。
        """
        qty = float(sz) if sz else 0.0
        price = float(px) if px else 0.0
        if not self.check_capital_limit(symbol, side, qty, price):
            return {
                "code": "-1",
                "msg": "capital_limit_exceeded",
                "data": [{"sCode": "-1", "sMsg": "资金上限超出，订单被拒绝"}],
            }
        return await self.client.place_order(
            inst_id=symbol, side=side, ord_type=ord_type, sz=sz, px=px,
        )

    async def check_position_conflict(self, symbol: str, close_qty: float) -> bool:
        """平仓前仓位冲突校验（Task 6: 改代数和）。

        核心逻辑：多策略虚拟持仓代数叠加应等于真实持仓（"傅里叶叠加"原理），
        多空对冲（A=+5, B=-5, real=0）不应误报冲突。
        - others_occupied = 其他策略 net_position 的代数和（带符号，多正空负）
        - real_pos = 真实持仓（带符号，多头正空头负）
        - available = real_pos - others_occupied（代数运算，即本策略有效持仓）
        - 可用量 usable：
            * real_pos > 0（多头）：usable = max(0, available)
            * real_pos < 0（空头）：usable = max(0, -available)
            * real_pos == 0（纯对冲）：usable = abs(available)
        - 当 close_qty > usable 时，记录 position_conflict 事件并返回 False。

        - 节流：用 self._last_conflict_check_ts，默认 10s 内返回上次结果，避免频繁查 API
        """
        # 节流：间隔内返回上次结果
        now = time.time()
        interval = float(self.params.get("conflict_check_interval", 10))
        if now - self._last_conflict_check_ts < interval:
            return self._last_conflict_check_result

        # 延迟导入避免循环依赖
        from models.strategy import StrategyInstance
        from models.pnl import PnlRecord

        # 1. 查同账户同 symbol 其他活跃策略实例，聚合其虚拟持仓代数和（带符号，多正空负）
        others_occupied = 0.0
        try:
            db = self.db_session_factory()
            try:
                chain = (
                    db.query(StrategyInstance)
                    .filter(StrategyInstance.account_id == self.account_id)
                    .filter(StrategyInstance.symbol == symbol)
                    .filter(StrategyInstance.status.in_(["running", "paused"]))
                    .filter(StrategyInstance.id != self.instance_id)
                )
                others = chain.all()
                for inst in others:
                    latest = (
                        db.query(PnlRecord)
                        .filter(PnlRecord.strategy_instance_id == inst.id)
                        .order_by(PnlRecord.recorded_at.desc())
                        .first()
                    )
                    if latest is not None and latest.net_position is not None:
                        others_occupied += float(latest.net_position)
            finally:
                db.close()
        except Exception as e:
            print(f"[BaseStrategy] check_position_conflict 查询异常: {e}")
            self._last_conflict_check_ts = now
            self._last_conflict_check_result = True  # 查询异常不阻塞交易
            return True

        # 2. 查真实持仓（带符号，多头正空头负）
        real_pos = 0.0
        try:
            risk = await self.client.get_position_risk(symbol)
            if risk is not None:
                pos_str = risk.get("pos")
                if pos_str is not None and pos_str != "":
                    try:
                        real_pos = float(pos_str)
                    except (ValueError, TypeError):
                        real_pos = 0.0
        except Exception as e:
            self._record_event(
                "position_conflict",
                f"仓位冲突校验查询真实持仓异常: {symbol} err={e}",
                {"symbol": symbol, "error": str(e)},
            )
            self._last_conflict_check_ts = now
            self._last_conflict_check_result = True
            return True

        # 3. 代数运算：available = real_pos - others_occupied（本策略有效持仓）
        #    可用量 usable 按 real_pos 方向取值；available 与 real_pos 异号时，
        #    真实方向不足以覆盖其他策略占用，usable=0 必然冲突。
        available = real_pos - others_occupied
        self._last_conflict_check_ts = now

        if real_pos > 0:
            # 多头：可用 = max(0, available)
            usable = max(0.0, available)
        elif real_pos < 0:
            # 空头：可用 = max(0, -available)
            usable = max(0.0, -available)
        else:
            # 纯对冲（real_pos == 0）：双向可用 = abs(available)
            usable = abs(available)

        if close_qty > usable:
            self._record_event(
                "position_conflict",
                f"仓位冲突: {symbol} close_qty={close_qty} > usable={usable} "
                f"(real_pos={real_pos}, others_occupied={others_occupied}, available={available})",
                {
                    "symbol": symbol,
                    "close_qty": close_qty,
                    "real_pos": real_pos,
                    "others_occupied": others_occupied,
                    "available": available,
                },
            )
            self._last_conflict_check_result = False
            return False

        self._last_conflict_check_result = True
        return True

    async def close_position_with_conflict_check(
        self, symbol: str, side: str, ord_type: str, sz, px=None, **kwargs
    ) -> dict:
        """带仓位冲突校验的平仓下单包装方法（SubTask 5.1）。

        先调 check_position_conflict，通过则调 client.place_order，否则返回拒绝响应（不实际下单）。
        供策略平仓时调用，替代直接 client.place_order。
        """
        qty = float(sz) if sz else 0.0
        if not await self.check_position_conflict(symbol, qty):
            return {
                "code": "-1",
                "msg": "position_conflict",
                "data": [{"sCode": "-1", "sMsg": "仓位冲突，平仓被拒绝"}],
            }
        return await self.client.place_order(
            inst_id=symbol, side=side, ord_type=ord_type, sz=sz, px=px,
        )

    async def check_margin_risk(self, symbol: str) -> bool:
        """检查保证金占用率（SubTask 3.2）。

        仅合约（-SWAP）才检查，现货直接返回 True。
        调用 client.get_position_risk(symbol) 获取保证金占用率与强平价：
        - 无持仓（返回 None）：返回 True（无风险）
        - margin_ratio > 0.95：记录 margin_critical 事件并返回 False（调用方拒单）
        - margin_ratio > 0.80：记录 margin_warning 事件并返回 True（仅告警，不拒单）
        - 正常：返回 True

        用 self._last_margin_check_ts 节流，默认 30s 查一次
        （可配 self.params.get("margin_check_interval", 30)）；节流期内返回上次结果。
        """
        # 现货不检查保证金
        if "-SWAP" not in symbol:
            return True

        # 节流：间隔内返回上次结果，避免每 tick 都查 API
        now = time.time()
        interval = float(self.params.get("margin_check_interval", 30))
        if now - self._last_margin_check_ts < interval:
            return self._last_margin_check_result

        try:
            risk = await self.client.get_position_risk(symbol)
        except Exception as e:
            # 查询异常不阻塞交易，返回上次结果（默认 True）
            self._record_event(
                "margin_check_failed",
                f"保证金检查异常: {symbol} err={e}",
                {"symbol": symbol, "error": str(e)},
            )
            return self._last_margin_check_result

        self._last_margin_check_ts = now

        # 无持仓：无风险
        if risk is None:
            self._last_margin_check_result = True
            return True

        try:
            margin_ratio = float(risk.get("margin_ratio", 0.0))
        except (ValueError, TypeError):
            margin_ratio = 0.0
        liq_px = risk.get("liq_px")

        details = {
            "symbol": symbol,
            "margin_ratio": margin_ratio,
            "liq_px": liq_px,
            "margin": risk.get("margin"),
            "pos": risk.get("pos"),
            "pos_side": risk.get("pos_side"),
        }

        # 保证金临界：拒单
        if margin_ratio > 0.95:
            self._record_event(
                "margin_critical",
                f"保证金临界: {symbol} margin_ratio={margin_ratio:.4f} liq_px={liq_px}",
                details,
            )
            self._last_margin_check_result = False
            return False

        # 保证金告警：不拒单，仅告警
        if margin_ratio > 0.80:
            self._record_event(
                "margin_warning",
                f"保证金告警: {symbol} margin_ratio={margin_ratio:.4f} liq_px={liq_px}",
                details,
            )
            self._last_margin_check_result = True
            return True

        # 正常
        self._last_margin_check_result = True
        return True

    @abstractmethod
    async def execute(self):
        pass

    @abstractmethod
    async def validate_params(self) -> bool:
        pass

    async def _apply_leverage_settings(self) -> bool:
        """启动时设置合约杠杆（SubTask 2.2）。

        仅当 symbol 是合约（含 "-SWAP"）且 lever > 0 时调用 client.set_leverage。
        lever=1 且 td_mode=cross（OKX 默认）时跳过以减少 API 调用。
        成功记录 leverage_set 事件，失败记录 leverage_set_failed 并返回 False（应阻止启动）。

        Returns:
            True 表示无需设置或设置成功；False 表示设置失败
        """
        symbol = self.params.get("symbol", "")
        is_contract = "-SWAP" in symbol
        if not is_contract or self.lever <= 0:
            return True
        # OKX 默认即 lever=1 + cross，跳过以减少 API 调用
        if self.lever == 1 and self.td_mode == "cross":
            return True
        try:
            await self.client.set_leverage(
                inst_id=symbol, lever=self.lever, mgn_mode=self.td_mode,
            )
            self._record_event(
                "leverage_set",
                f"合约杠杆设置成功: {symbol} lever={self.lever} mgn_mode={self.td_mode}",
                {"symbol": symbol, "lever": self.lever, "td_mode": self.td_mode},
            )
            return True
        except OKXAPIException as e:
            self._record_event(
                "leverage_set_failed",
                f"合约杠杆设置失败: {symbol} lever={self.lever} mgn_mode={self.td_mode} "
                f"code={e.code} msg={e.msg}",
                {
                    "symbol": symbol, "lever": self.lever, "td_mode": self.td_mode,
                    "error_code": e.code, "error_msg": e.msg, "endpoint": e.endpoint,
                },
            )
            return False
        except Exception as e:
            self._record_event(
                "leverage_set_failed",
                f"合约杠杆设置异常: {symbol} lever={self.lever} mgn_mode={self.td_mode} err={e}",
                {"symbol": symbol, "lever": self.lever, "td_mode": self.td_mode, "error": str(e)},
            )
            return False

    def compute_order_qty(self, price: float, symbol: str) -> float:
        """计算下单数量（SubTask 2.3）。

        - 合约（-SWAP）：qty = investment_amount × lever / price，再按合约面值 ctVal 向下取整为整数张数
        - 现货：qty = investment_amount / price（lever 不适用）
        - investment_amount=0 或 price<=0 时返回 0
        - 若 instrument 缓存未命中（无 ctVal），返回 float 由调用方处理

        设计说明：网格策略当前用固定 order_qty 参数，本方法不强制改造 grid 的下单数量计算。
        网格档位 qty 固定，杠杆放大的是可下档位数而非单档 qty，由 check_capital_limit 兜底。
        """
        if self.investment_amount <= 0 or price <= 0:
            return 0.0
        is_contract = "-SWAP" in symbol
        if not is_contract:
            # 现货：lever 不适用
            return self.investment_amount / price
        # 合约：名义价值 / 价格 = base 数量，再 / ctVal = 张数
        raw_qty = self.investment_amount * self.lever / price
        from services.instrument_cache import instrument_cache
        cached = instrument_cache._cache.get(symbol)
        if cached is None:
            # 缓存未命中，返回 float 由调用方处理
            return float(raw_qty)
        ct_val = float(cached.get("ctVal", 1.0) or 1.0)
        if ct_val <= 0:
            ct_val = 1.0
        return float(math.floor(raw_qty / ct_val))

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
        # 设置合约杠杆（SubTask 2.2）；失败则阻止启动
        if not await self._apply_leverage_settings():
            self.update_status("error")
            return
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
            u_time = order_data.get("uTime", "")
            self.order_manager.update_order(
                ord_id,
                state=state,
                fillPx=fill_px,
                fillSz=fill_sz,
                fee=fee,
                uTime=u_time,
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
        # Bug 6: 检测是否在事件循环中，避免 asyncio.run 与主循环冲突
        try:
            asyncio.get_running_loop()
            # 在事件循环中：用 create_task 调度异步清理，不阻塞调用方
            asyncio.create_task(self._pause_async(symbol))
        except RuntimeError:
            # 无事件循环：用 asyncio.run 运行完整异步清理（含 record_event / record_final_pnl）
            asyncio.run(self._pause_async(symbol))

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
        # Bug 6: 检测是否在事件循环中，避免 asyncio.run 与主循环冲突
        try:
            asyncio.get_running_loop()
            asyncio.create_task(self._stop_async(symbol))
        except RuntimeError:
            asyncio.run(self._stop_async(symbol))

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
                            fee=info[0].get("fee", ""),
                            uTime=info[0].get("uTime", ""))
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

    async def record_order(self, symbol: str, side: str, order_type: str, price: float, quantity: float, order_id: str = "", status: str = "filled"):
        # Delegate to OrderManager for persistence
        if status == "live":
            await self.order_manager.add_order(
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
                # 不覆盖 OKX 推送的真实成交价 fillPx：
                # price 参数是网格档位价（限价），而非实际成交价。
                # OKX WS 推送的 fillPx 已在 _on_ws_order_update 中写入，
                # 此处仅在 fillPx 缺失时用限价回退。
                existing = self.order_manager.get_order(order_id)
                if existing is None or not existing.fillPx:
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
        """判断是否应写入 PnL 记录：间隔 ≥ 60s 或 total_pnl 变化超阈值。

        此方法由 PnlAccountingEngine 调用，策略不应直接调用。
        """
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

    def record_pnl(self, equity: float, unrealized_pnl: float, realized_pnl: float,
                   net_position: float = None, avg_buy_price: float = None,
                   total_fee: float = None, order_count: int = None):
        """写入一条 PnL 记录到数据库。

        此方法由 PnlAccountingEngine 调用，策略不应直接调用。
        """
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
                net_position=net_position,
                avg_buy_price=avg_buy_price,
                total_fee=total_fee,
                order_count=order_count,
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
                last_net_position = latest.net_position if latest else None
                last_avg_buy_price = latest.avg_buy_price if latest else None
                last_total_fee = latest.total_fee if latest else None
                last_order_count = latest.order_count if latest else None
                record = PnlRecord(
                    account_id=self.account_id,
                    strategy_instance_id=self.instance_id,
                    equity=equity,
                    unrealized_pnl=last_unrealized,  # 保留最后浮动盈亏（不再清零）
                    realized_pnl=realized,
                    total_pnl=last_unrealized + realized,
                    is_final=True,
                    recorded_at=datetime.now(timezone.utc),
                    net_position=last_net_position,
                    avg_buy_price=last_avg_buy_price,
                    total_fee=last_total_fee,
                    order_count=last_order_count,
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