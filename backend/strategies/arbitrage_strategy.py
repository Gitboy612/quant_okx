import asyncio
import traceback
from datetime import datetime, timezone

from strategies.base_strategy import BaseStrategy


class ArbitrageStrategy(BaseStrategy):
    """跨市场套利策略。

    在现货与期货之间捕捉价差：
      - spread > threshold：买现货 + 卖期货（direction > 0）
      - spread < -threshold：卖现货 + 买期货（direction < 0）
      - 价差回归时 FIFO 平仓并核算已实现盈亏。

    支持多次开仓累积、DB 恢复、网络退避与 WebSocket 订单回调。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 持仓列表提升为实例属性，供 DB 恢复与回调访问。
        # 每个元素：{"buy_price", "sell_price", "qty", "direction",
        #           "futures_ord_id", "spot_ord_id"}
        self._open_positions: list[dict] = []

    async def validate_params(self) -> bool:
        required = ["spot_symbol", "futures_symbol", "spread_threshold", "order_qty"]
        for key in required:
            if key not in self.params:
                return False
        if self.params["spread_threshold"] <= 0:
            return False
        if self.params["order_qty"] <= 0:
            return False
        return True

    # ========== DB 恢复 ==========

    async def _persist_arb_leg(self, symbol: str, side: str, price: float, qty: float,
                               order_id: str, status: str):
        """将套利腿持久化到 orders 表，使用自定义 status 便于恢复区分。"""
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
            print(f"[ArbitrageStrategy] persist leg error: {e}")

    async def _mark_arb_leg_closed(self, order_id: str):
        """平仓时将对应开仓腿标记为已平仓。"""
        if not order_id:
            return
        try:
            from models.order import Order
            db = self.db_session_factory()
            try:
                leg = db.query(Order).filter(Order.order_id == order_id).first()
                if leg and leg.status == "arbitrage_open":
                    leg.status = "arbitrage_close"
                    leg.state = "arbitrage_close"
                    leg.updated_at = datetime.now(timezone.utc)
                    db.commit()
            finally:
                db.close()
        except Exception as e:
            print(f"[ArbitrageStrategy] mark closed error: {e}")

    async def _restore_positions_from_db(self):
        """启动时从 orders 表恢复 open_positions 列表。

        查询 status='arbitrage_open' 的订单，按 id 排序后两两配对
        （每笔套利仓位含现货腿 + 期货腿），重建持仓字典。
        """
        try:
            from models.order import Order
            db = self.db_session_factory()
            try:
                open_legs = db.query(Order).filter(
                    Order.strategy_instance_id == self.instance_id,
                    Order.status == "arbitrage_open",
                ).order_by(Order.id).all()
            finally:
                db.close()
        except Exception as e:
            print(f"[ArbitrageStrategy] restore positions error: {e}")
            return

        if not open_legs:
            return

        spot_symbol = self.params["spot_symbol"]
        futures_symbol = self.params["futures_symbol"]

        # 两两配对：偶数索引为期货腿（先下单），奇数索引为现货腿
        i = 0
        while i + 1 < len(open_legs):
            leg_a = open_legs[i]
            leg_b = open_legs[i + 1]
            i += 2

            # 区分现货腿与期货腿
            if leg_a.symbol == futures_symbol:
                fut_leg, spot_leg = leg_a, leg_b
            else:
                fut_leg, spot_leg = leg_b, leg_a

            # 跳过不匹配的配对
            if fut_leg.symbol != futures_symbol or spot_leg.symbol != spot_symbol:
                self._record_event("restore_warn",
                                   f"套利腿配对不匹配: leg_a={leg_a.symbol} leg_b={leg_b.symbol}")
                continue

            qty = float(spot_leg.quantity or fut_leg.quantity or 0)
            if qty <= 0:
                continue

            # direction > 0: 买现货 + 卖期货
            # direction < 0: 卖现货 + 买期货
            if spot_leg.side == "buy" and fut_leg.side == "sell":
                direction = 1
                buy_price = float(spot_leg.price or 0)
                sell_price = float(fut_leg.price or 0)
            elif spot_leg.side == "sell" and fut_leg.side == "buy":
                direction = -1
                buy_price = float(fut_leg.price or 0)
                sell_price = float(spot_leg.price or 0)
            else:
                self._record_event("restore_warn",
                                   f"套利腿方向不匹配: spot={spot_leg.side} fut={fut_leg.side}")
                continue

            self._open_positions.append({
                "buy_price": buy_price,
                "sell_price": sell_price,
                "qty": qty,
                "direction": direction,
                "futures_ord_id": fut_leg.order_id or "",
                "spot_ord_id": spot_leg.order_id or "",
            })

        if self._open_positions:
            self._record_event("restored",
                               f"从 DB 恢复 {len(self._open_positions)} 笔套利持仓")

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

        套利策略使用市价单，成交在 place_order 返回时即完成。
        此回调用于对账：确认成交价与费用，更新对应持仓腿的成交信息。
        不在此处触发平仓逻辑——平仓由 execute 主循环的价差判断驱动。
        """
        ord_id = order_info.ordId
        fill_px = float(order_info.fillPx) if order_info.fillPx else 0.0
        fill_sz = float(order_info.fillSz) if order_info.fillSz else 0.0
        fee = float(order_info.fee) if order_info.fee else 0.0

        if not ord_id:
            return

        # 对账：更新持仓字典中对应腿的实际成交价
        updated = False
        for pos in self._open_positions:
            if pos.get("futures_ord_id") == ord_id or pos.get("spot_ord_id") == ord_id:
                if fill_px > 0:
                    if pos.get("futures_ord_id") == ord_id:
                        if pos["direction"] > 0:
                            pos["sell_price"] = fill_px
                        else:
                            pos["buy_price"] = fill_px
                    elif pos.get("spot_ord_id") == ord_id:
                        if pos["direction"] > 0:
                            pos["buy_price"] = fill_px
                        else:
                            pos["sell_price"] = fill_px
                    updated = True
                break

        if updated:
            self._record_event("order_filled",
                               f"套利腿成交对账: ordId={ord_id} px={fill_px} qty={fill_sz} fee={fee}",
                               {"order_id": ord_id, "fill_px": fill_px, "fill_sz": fill_sz, "fee": fee})

    # ========== 主执行循环 ==========

    async def execute(self):
        try:
            if not await self.validate_params():
                self.update_status("error")
                return

            spot_symbol = self.params["spot_symbol"]
            futures_symbol = self.params["futures_symbol"]
            spread_threshold = self.params["spread_threshold"]
            order_qty = self.params["order_qty"]
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

            # 从 DB 恢复未平仓套利持仓
            await self._restore_positions_from_db()

            # 注册 WebSocket 订单成交回调
            self.order_manager.on("filled", self._on_order_filled)

            consecutive_errors = 0

            while self._running:
                if self._paused:
                    await asyncio.sleep(1)
                    continue

                try:
                    spot_ticker = await self.client.get_ticker(spot_symbol)
                    futures_ticker = await self.client.get_ticker(futures_symbol)

                    if not spot_ticker or not futures_ticker:
                        await asyncio.sleep(3)
                        continue

                    spot_price = float(spot_ticker[0]["last"])
                    futures_price = float(futures_ticker[0]["last"])
                    spread_pct = (futures_price - spot_price) / spot_price * 100

                    if not self._open_positions and abs(spread_pct) > spread_threshold:
                        if spread_pct > 0:
                            fut_resp = await self.client.place_order(
                                inst_id=futures_symbol, side="sell", ord_type="market", sz=str(order_qty))
                            spot_resp = await self.client.place_order(
                                inst_id=spot_symbol, side="buy", ord_type="market", sz=str(order_qty))
                            fut_ord_id = fut_resp.get("data", [{}])[0].get("ordId", "") if fut_resp.get("code") == "0" else ""
                            spot_ord_id = spot_resp.get("data", [{}])[0].get("ordId", "") if spot_resp.get("code") == "0" else ""
                            await self._persist_arb_leg(futures_symbol, "sell", futures_price, order_qty, fut_ord_id, "arbitrage_open")
                            await self._persist_arb_leg(spot_symbol, "buy", spot_price, order_qty, spot_ord_id, "arbitrage_open")
                            await self.record_order(futures_symbol, "sell", "market", futures_price, order_qty)
                            await self.record_order(spot_symbol, "buy", "market", spot_price, order_qty)
                            self._open_positions.append({
                                "buy_price": spot_price,
                                "sell_price": futures_price,
                                "qty": order_qty,
                                "direction": 1,
                                "futures_ord_id": fut_ord_id,
                                "spot_ord_id": spot_ord_id,
                            })
                        else:
                            fut_resp = await self.client.place_order(
                                inst_id=futures_symbol, side="buy", ord_type="market", sz=str(order_qty))
                            spot_resp = await self.client.place_order(
                                inst_id=spot_symbol, side="sell", ord_type="market", sz=str(order_qty))
                            fut_ord_id = fut_resp.get("data", [{}])[0].get("ordId", "") if fut_resp.get("code") == "0" else ""
                            spot_ord_id = spot_resp.get("data", [{}])[0].get("ordId", "") if spot_resp.get("code") == "0" else ""
                            await self._persist_arb_leg(futures_symbol, "buy", futures_price, order_qty, fut_ord_id, "arbitrage_open")
                            await self._persist_arb_leg(spot_symbol, "sell", spot_price, order_qty, spot_ord_id, "arbitrage_open")
                            await self.record_order(futures_symbol, "buy", "market", futures_price, order_qty)
                            await self.record_order(spot_symbol, "sell", "market", spot_price, order_qty)
                            self._open_positions.append({
                                "buy_price": futures_price,
                                "sell_price": spot_price,
                                "qty": order_qty,
                                "direction": -1,
                                "futures_ord_id": fut_ord_id,
                                "spot_ord_id": spot_ord_id,
                            })

                    elif self._open_positions and abs(spread_pct) < spread_threshold * 0.3:
                        # FIFO 平仓：每次平掉最早开仓的一笔，支持多次开仓累积
                        pos = self._open_positions.pop(0)
                        direction = pos["direction"]
                        futures_close_side = "buy" if direction > 0 else "sell"
                        spot_close_side = "sell" if direction > 0 else "buy"
                        await self.client.place_order(
                            inst_id=futures_symbol, side=futures_close_side, ord_type="market", sz=str(order_qty))
                        await self.client.place_order(
                            inst_id=spot_symbol, side=spot_close_side, ord_type="market", sz=str(order_qty))
                        await self.record_order(futures_symbol, futures_close_side, "market", futures_price, order_qty, status="close")
                        await self.record_order(spot_symbol, spot_close_side, "market", spot_price, order_qty, status="close")
                        # 平仓时核算已实现盈亏，避免 PnL 曲线缺失
                        buy_fee = pos["buy_price"] * pos["qty"] * fee_rate
                        sell_fee = pos["sell_price"] * pos["qty"] * fee_rate
                        cycle_pnl = (pos["sell_price"] - pos["buy_price"]) * pos["qty"] - buy_fee - sell_fee
                        self.add_realized_pnl(cycle_pnl)
                        # 标记对应开仓腿为已平仓
                        await self._mark_arb_leg_closed(pos.get("futures_ord_id", ""))
                        await self._mark_arb_leg_closed(pos.get("spot_ord_id", ""))

                    balances = await self.client.get_balance()
                    if balances:
                        total_equity = float(balances.get("totalEq", "0"))

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
                        print(f"[ArbitrageStrategy] Network error #{consecutive_errors}, backing off {backoff}s: {e}")
                        self._record_event("error", f"网络异常 (第{consecutive_errors}次)，退避 {backoff}s: {error_msg[:200]}")

                        if consecutive_errors >= 10:
                            print(f"[ArbitrageStrategy] Too many network errors ({consecutive_errors}), stopping strategy")
                            self._record_event("error", f"连续网络异常 {consecutive_errors} 次，自动停止策略")
                            self.record_final_pnl()
                            self.update_status("stopped")
                            self._running = False
                            break

                        await asyncio.sleep(backoff)
                        continue
                    else:
                        backoff = min(3 * consecutive_errors, 30)
                        print(f"[ArbitrageStrategy] Non-network error #{consecutive_errors}, backing off {backoff}s: {e}")
                        self._record_event("error", f"策略异常 (第{consecutive_errors}次)，退避 {backoff}s: {error_msg[:200]}")

                        if consecutive_errors >= 20:
                            print(f"[ArbitrageStrategy] Too many non-network errors ({consecutive_errors}), stopping strategy")
                            self._record_event("error", f"连续策略异常 {consecutive_errors} 次，自动停止策略: {error_msg[:200]}")
                            self.record_final_pnl()
                            self.update_status("stopped")
                            self._running = False
                            break

                        await asyncio.sleep(backoff)
                        continue

                await asyncio.sleep(5)

        except Exception as e:
            print(f"[ArbitrageStrategy] execute error: {e}\n{traceback.format_exc()}")
            self._record_event("error", f"策略执行异常: {e}", {"traceback": traceback.format_exc()})
            self.update_status("error")
            return
