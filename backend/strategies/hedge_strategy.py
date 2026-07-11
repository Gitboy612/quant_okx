import asyncio
import time
import traceback
from datetime import datetime, timezone

from strategies.base_strategy import BaseStrategy


class AdvancedGridHedgeStrategy(BaseStrategy):
    """对冲策略（Hedge Strategy）。

    注意：本策略名为 AdvancedGridHedgeStrategy 仅为向后兼容，实际行为是
    **对冲策略**而非网格策略。策略不含任何网格挂单/档位逻辑，仅基于参考价
    的涨跌阈值（y%）进行自动套保与平套保，并在保证金率过高时触发紧急救险。

    策略逻辑：
      1. 以启动时首个价格为 ref_price 基准
      2. 价格上涨 y% → 卖出 n% 仓位进行套保（hedge_open）
      3. 价格下跌 y% → 买回平掉套保（hedge_close），核算已实现盈亏
      4. 平套保后若保证金率 > 0.8，用 safe_usdt 紧急买入救险
      5. 运行期间持续监控保证金率，过高时自动减仓

    参数：y（涨跌阈值%）、n（套保比例%）、order_qty、grid_count（保留兼容，
    未实际使用）、safe_usdt、symbol。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 对冲状态提升为实例属性，供 DB 恢复与回调访问
        self._ref_price: float = 0.0
        self._hedged: bool = False
        self._hedge_entry_price: float = 0.0
        self._hedge_qty: float = 0.0
        self._hedge_ord_id: str = ""

    async def validate_params(self) -> bool:
        required = ["y", "n", "order_qty", "grid_count", "safe_usdt", "symbol"]
        for key in required:
            if key not in self.params:
                return False
        if not (0 < self.params["y"] <= 100):
            return False
        if not (0 < self.params["n"] <= 100):
            return False
        if self.params["order_qty"] <= 0:
            return False
        if self.params["grid_count"] < 2:
            return False
        return True

    # ========== DB 恢复 ==========

    async def _persist_hedge_order(self, symbol: str, side: str, price: float, qty: float,
                                   order_id: str, status: str):
        """将对冲订单持久化到 orders 表，使用自定义 status 便于恢复区分。"""
        try:
            from models.order import Order
            db = self.db_session_factory()
            try:
                order = Order(
                    strategy_instance_id=self.instance_id,
                    account_id=self.account_id or 0,
                    symbol=symbol,
                    order_id=order_id or None,
                    side=side,
                    order_type="market",
                    price=price,
                    quantity=qty,
                    filled_quantity=qty,
                    fill_px=price,
                    fill_sz=qty,
                    state=status,
                    status=status,
                )
                db.add(order)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            print(f"[HedgeStrategy] persist order error: {e}")

    async def _mark_hedge_order_closed(self, order_id: str):
        """平套保时将对应开仓订单标记为已平仓。"""
        if not order_id:
            return
        try:
            from models.order import Order
            db = self.db_session_factory()
            try:
                leg = db.query(Order).filter(Order.order_id == order_id).first()
                if leg and leg.status == "hedge_open":
                    leg.status = "hedge_close"
                    leg.state = "hedge_close"
                    leg.updated_at = datetime.now(timezone.utc)
                    db.commit()
            finally:
                db.close()
        except Exception as e:
            print(f"[HedgeStrategy] mark closed error: {e}")

    async def _restore_hedge_state_from_db(self):
        """启动时从 orders 表恢复对冲状态。

        查询 status='hedge_open' 的订单，若存在未平仓的套保单则恢复 hedged 状态。
        """
        try:
            from models.order import Order
            db = self.db_session_factory()
            try:
                open_legs = db.query(Order).filter(
                    Order.strategy_instance_id == self.instance_id,
                    Order.status == "hedge_open",
                ).order_by(Order.id.desc()).all()
            finally:
                db.close()
        except Exception as e:
            print(f"[HedgeStrategy] restore state error: {e}")
            return

        if not open_legs:
            return

        # 取最近一笔未平仓的套保单恢复状态
        latest = open_legs[0]
        self._hedged = True
        self._hedge_entry_price = float(latest.price or 0)
        self._hedge_qty = float(latest.quantity or 0)
        self._hedge_ord_id = latest.order_id or ""

        self._record_event("restored",
                           f"从 DB 恢复对冲状态: hedged=True entry={self._hedge_entry_price} qty={self._hedge_qty}")

    async def _restore_realized_pnl(self):
        """从 DB 恢复已实现盈亏与初始净值。"""
        try:
            from models.pnl import PnlRecord
            db = self.db_session_factory()
            try:
                latest_pnl = db.query(PnlRecord).filter(
                    PnlRecord.strategy_instance_id == self.instance_id
                ).order_by(PnlRecord.recorded_at.desc()).first()
                if latest_pnl:
                    self.restore_realized_pnl(latest_pnl.realized_pnl or 0)
                    self._initial_equity = latest_pnl.equity - (latest_pnl.realized_pnl or 0) - (latest_pnl.unrealized_pnl or 0)
            finally:
                db.close()
        except Exception:
            pass

    # ========== WebSocket 订单回调 ==========

    async def _on_order_filled(self, order_info):
        """处理订单成交回调（来自 OrderManager 的 'filled' 事件）。

        对冲策略使用市价单，成交在 place_order 返回时即完成。
        此回调用于对账：确认套保单的实际成交价。
        """
        ord_id = order_info.ordId
        fill_px = float(order_info.fillPx) if order_info.fillPx else 0.0

        if not ord_id or fill_px <= 0:
            return

        # 对账：更新套保入场价
        if self._hedged and ord_id == self._hedge_ord_id:
            self._hedge_entry_price = fill_px
            self._record_event("order_filled",
                               f"套保单成交对账: ordId={ord_id} px={fill_px}",
                               {"order_id": ord_id, "fill_px": fill_px})

    # ========== 保证金率监控 ==========

    async def _check_margin_ratio(self, symbol: str, current_price: float, safe_usdt: float):
        """监控保证金率，过高时触发紧急救险或自动减仓。"""
        try:
            positions = await self.client.get_positions()
            if not positions:
                return
            for pos in positions:
                if pos.get("instId") != symbol:
                    continue
                margin_ratio = float(pos.get("mgnRatio", "1"))
                if margin_ratio > 0.8:
                    # 紧急救险：用 safe_usdt 买入降低保证金率
                    rescue_qty = safe_usdt / current_price if current_price > 0 else 0
                    if rescue_qty <= 0:
                        break
                    resp = await self.client.place_order(
                        inst_id=symbol,
                        side="buy",
                        ord_type="market",
                        sz=str(round(rescue_qty, 6)),
                    )
                    rescue_ord_id = resp.get("data", [{}])[0].get("ordId", "") if resp.get("code") == "0" else ""
                    await self._persist_hedge_order(
                        symbol, "buy", current_price, round(rescue_qty, 6), rescue_ord_id, "emergency_margin")
                    await self.record_order(
                        symbol, "buy", "market", current_price, round(rescue_qty, 6),
                        status="emergency_margin",
                    )
                    self._record_event("emergency_margin",
                                       f"保证金率 {margin_ratio:.4f} 超阈值，紧急救险买入 {rescue_qty:.6f}",
                                       {"margin_ratio": margin_ratio, "rescue_qty": rescue_qty})
                break
        except Exception as e:
            print(f"[HedgeStrategy] margin check error: {e}")

    # ========== 主执行循环 ==========

    async def execute(self):
        try:
            if not await self.validate_params():
                self.update_status("error")
                return

            y_pct = self.params["y"] / 100
            n_pct = self.params["n"] / 100
            order_qty = self.params["order_qty"]
            safe_usdt = self.params["safe_usdt"]
            symbol = self.params["symbol"]
            fee_rate = self._fee_rate

            self.update_status("running")

            # 获取初始净值
            try:
                balances = await self.client.get_balance()
                if balances:
                    self._initial_equity = float(balances.get("totalEq", "0"))
            except Exception:
                self._initial_equity = 0.0

            # 从 DB 恢复已实现盈亏
            await self._restore_realized_pnl()

            # 从 DB 恢复对冲状态
            await self._restore_hedge_state_from_db()

            # 注册 WebSocket 订单成交回调
            self.order_manager.on("filled", self._on_order_filled)

            ref_price = self._ref_price
            hedged = self._hedged

            last_margin_check = 0.0
            consecutive_errors = 0

            while self._running:
                if self._paused:
                    await asyncio.sleep(1)
                    continue

                try:
                    tickers = await self.client.get_ticker(symbol)
                    if not tickers:
                        await asyncio.sleep(3)
                        continue

                    current_price = float(tickers[0]["last"])

                    if ref_price == 0.0:
                        ref_price = current_price
                        self._ref_price = ref_price
                        await asyncio.sleep(10)
                        continue

                    change_pct = (current_price - ref_price) / ref_price

                    if change_pct >= y_pct and not hedged:
                        hedge_qty = order_qty * n_pct
                        resp = await self.client.place_order(
                            inst_id=symbol,
                            side="sell",
                            ord_type="market",
                            sz=str(round(hedge_qty, 6)),
                        )
                        hedge_ord_id = resp.get("data", [{}])[0].get("ordId", "") if resp.get("code") == "0" else ""
                        await self._persist_hedge_order(
                            symbol, "sell", current_price, round(hedge_qty, 6), hedge_ord_id, "hedge_open")
                        hedged = True
                        self._hedged = True
                        self._hedge_entry_price = current_price
                        self._hedge_qty = round(hedge_qty, 6)
                        self._hedge_ord_id = hedge_ord_id
                        await self.record_order(
                            symbol, "sell", "market", current_price, round(hedge_qty, 6),
                            status="hedge_open",
                        )
                        ref_price = current_price
                        self._ref_price = ref_price

                    elif change_pct <= -y_pct and hedged:
                        close_qty = self._hedge_qty or round(order_qty * n_pct, 6)
                        resp = await self.client.place_order(
                            inst_id=symbol,
                            side="buy",
                            ord_type="market",
                            sz=str(round(close_qty, 6)),
                        )
                        close_ord_id = resp.get("data", [{}])[0].get("ordId", "") if resp.get("code") == "0" else ""
                        await self._persist_hedge_order(
                            symbol, "buy", current_price, round(close_qty, 6), close_ord_id, "hedge_close")
                        # 核算已实现盈亏：卖空套保后买回平仓
                        entry_price = self._hedge_entry_price
                        buy_fee = entry_price * close_qty * fee_rate
                        sell_fee = current_price * close_qty * fee_rate
                        cycle_pnl = (entry_price - current_price) * close_qty - buy_fee - sell_fee
                        self.add_realized_pnl(cycle_pnl)
                        # 标记原套保单为已平仓
                        await self._mark_hedge_order_closed(self._hedge_ord_id)
                        hedged = False
                        self._hedged = False
                        self._hedge_entry_price = 0.0
                        self._hedge_qty = 0.0
                        self._hedge_ord_id = ""
                        await self.record_order(
                            symbol, "buy", "market", current_price, round(close_qty, 6),
                            status="hedge_close",
                        )
                        ref_price = current_price
                        self._ref_price = ref_price

                    # 定期检查保证金率（每 30 秒一次）
                    now = time.time()
                    if now - last_margin_check > 30:
                        last_margin_check = now
                        await self._check_margin_ratio(symbol, current_price, safe_usdt)

                    balances = await self.client.get_balance()
                    if balances:
                        total_equity = float(balances.get("totalEq", "0"))
                        if self._initial_equity == 0.0:
                            self._initial_equity = total_equity
                        strategy_pnl = total_equity - self._initial_equity

                    consecutive_errors = 0

                except Exception as e:
                    consecutive_errors += 1
                    error_msg = str(e)
                    # 判断是否网络异常
                    is_network_error = any(kw in error_msg.lower() for kw in [
                        "winerror 64", "winerror 10054", "winerror 10060", "winerror 10061",
                        "timed out", "connection refused", "ssl", "eof", "network", "connect",
                        "timeout", "unreachable"
                    ])

                    if is_network_error:
                        backoff = min(2 ** consecutive_errors, 60)
                        print(f"[HedgeStrategy] Network error #{consecutive_errors}, backing off {backoff}s: {e}")
                        self._record_event("error", f"网络异常 (第{consecutive_errors}次)，退避 {backoff}s: {error_msg[:200]}")

                        if consecutive_errors >= 10:
                            print(f"[HedgeStrategy] Too many network errors ({consecutive_errors}), stopping strategy")
                            self._record_event("error", f"连续网络异常 {consecutive_errors} 次，自动停止策略")
                            self.record_final_pnl()
                            self.update_status("stopped")
                            self._running = False
                            break

                        await asyncio.sleep(backoff)
                        continue
                    else:
                        backoff = min(3 * consecutive_errors, 30)
                        print(f"[HedgeStrategy] Non-network error #{consecutive_errors}, backing off {backoff}s: {e}")
                        self._record_event("error", f"策略异常 (第{consecutive_errors}次)，退避 {backoff}s: {error_msg[:200]}")

                        if consecutive_errors >= 20:
                            print(f"[HedgeStrategy] Too many non-network errors ({consecutive_errors}), stopping strategy")
                            self._record_event("error", f"连续策略异常 {consecutive_errors} 次，自动停止策略: {error_msg[:200]}")
                            self.record_final_pnl()
                            self.update_status("stopped")
                            self._running = False
                            break

                        await asyncio.sleep(backoff)
                        continue

                await asyncio.sleep(5)

        except Exception as e:
            print(f"[HedgeStrategy] execute error: {e}\n{traceback.format_exc()}")
            self._record_event("error", f"策略执行异常: {e}", {"traceback": traceback.format_exc()})
            self.update_status("error")
            return
