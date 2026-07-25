import asyncio
from strategies.base_strategy import BaseStrategy
from services.market_data_service import market_data_service


class TrendStrategy(BaseStrategy):
    SUPPORTED_BARS = {"1m", "3m", "5m", "15m", "30m", "1H"}

    def _runtime_params(self) -> dict:
        """Normalize current and legacy trend-strategy parameters."""
        fast_period = self.params.get("fast_period")
        if fast_period is None:
            fast_period = self.params.get("fast_ma_period")
        slow_period = self.params.get("slow_period")
        if slow_period is None:
            slow_period = self.params.get("slow_ma_period")

        return {
            "fast_period": int(fast_period),
            "slow_period": int(slow_period),
            "order_qty": float(self.params["order_qty"]),
            "symbol": str(self.params["symbol"]),
            "bar": str(self.params.get("bar", "5m")),
            "poll_interval": float(self.params.get("poll_interval", 60)),
            "enter_on_start": bool(self.params.get("enter_on_start", False)),
            "closed_candle_only": bool(self.params.get("closed_candle_only", True)),
        }

    async def validate_params(self) -> bool:
        try:
            runtime = self._runtime_params()
        except (KeyError, TypeError, ValueError):
            return False

        fast_period = runtime["fast_period"]
        slow_period = runtime["slow_period"]
        if fast_period < 2 or slow_period < 3 or fast_period >= slow_period:
            return False
        if runtime["order_qty"] <= 0 or not runtime["symbol"]:
            return False
        if runtime["bar"] not in self.SUPPORTED_BARS:
            return False
        if runtime["poll_interval"] < 5 or runtime["poll_interval"] > 300:
            return False
        return True

    @staticmethod
    def _parse_place_order_response(response: dict) -> tuple[str | None, str | None]:
        """Return (ordId, error), validating both OKX outer and per-order codes."""
        if not isinstance(response, dict):
            return None, "OKX 返回格式无效"

        code = str(response.get("code", ""))
        if code != "0":
            detail = ""
            data = response.get("data")
            if isinstance(data, list) and data and isinstance(data[0], dict):
                item = data[0]
                sub_code = str(item.get("sCode", "")).strip()
                sub_message = str(item.get("sMsg", "")).strip()
                if sub_code or sub_message:
                    detail = f" sCode={sub_code or 'missing'} sMsg={sub_message}"
            return None, (
                f"OKX code={code or 'missing'} msg={response.get('msg', '')}{detail}"
            )

        data = response.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return None, "OKX 下单响应缺少 data[0]"

        item = data[0]
        sub_code = str(item.get("sCode", ""))
        if sub_code != "0":
            return None, f"OKX sCode={sub_code or 'missing'} sMsg={item.get('sMsg', '')}"

        order_id = str(item.get("ordId", "")).strip()
        if not order_id:
            return None, "OKX 下单成功响应缺少 ordId"
        return order_id, None

    @staticmethod
    def _calculate_signal(
        closes: list[float],
        fast_period: int,
        slow_period: int,
        enter_on_start: bool = False,
    ) -> tuple[str | None, dict]:
        """Calculate a crossover signal and return its moving-average snapshot."""
        fast_ma = sum(closes[-fast_period:]) / fast_period
        slow_ma = sum(closes[-slow_period:]) / slow_period
        prev_fast_ma = sum(closes[-fast_period - 1:-1]) / fast_period
        prev_slow_ma = sum(closes[-slow_period - 1:-1]) / slow_period

        signal = None
        reason = "waiting"
        if prev_fast_ma <= prev_slow_ma and fast_ma > slow_ma:
            signal = "buy"
            reason = "golden_cross"
        elif prev_fast_ma >= prev_slow_ma and fast_ma < slow_ma:
            signal = "sell"
            reason = "death_cross"
        elif enter_on_start and fast_ma != slow_ma:
            signal = "buy" if fast_ma > slow_ma else "sell"
            reason = "initial_trend"

        return signal, {
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "prev_fast_ma": prev_fast_ma,
            "prev_slow_ma": prev_slow_ma,
            "reason": reason,
        }

    async def _on_order_filled(self, order_info):
        """Handle order fill event for position tracking."""
        symbol = order_info.symbol
        side = order_info.side
        px = float(order_info.px) if order_info.px else 0
        sz = float(order_info.sz) if order_info.sz else 0

        if side == "buy":
            if self._position < 0:
                # Closing short position → realized PnL
                close_qty = min(sz, abs(self._position))
                realized = (self._avg_entry_price - px) * close_qty
                self.add_realized_pnl(realized)
                remaining = sz - close_qty
                if remaining > 0:
                    self._position = remaining
                    self._avg_entry_price = px
                else:
                    self._position += sz
                    if self._position >= 0:
                        self._avg_entry_price = px
            else:
                # Opening/adding to long position
                new_total = self._position + sz
                self._avg_entry_price = (self._avg_entry_price * self._position + px * sz) / new_total if new_total > 0 else px
                self._position = new_total
        elif side == "sell":
            if self._position > 0:
                # Closing long position → realized PnL
                close_qty = min(sz, self._position)
                realized = (px - self._avg_entry_price) * close_qty
                self.add_realized_pnl(realized)
                remaining = sz - close_qty
                if remaining > 0:
                    self._position = -remaining
                    self._avg_entry_price = px
                else:
                    self._position -= sz
                    if self._position <= 0:
                        self._avg_entry_price = px
            else:
                # Opening/adding to short position
                new_total = abs(self._position) + sz
                self._avg_entry_price = (self._avg_entry_price * abs(self._position) + px * sz) / new_total if new_total > 0 else px
                self._position = -new_total

        await self.record_order(symbol, side, "market", px, sz, order_id=order_info.ordId, status="filled")

    def _on_ticker_update(self, ticker_data: dict):
        """WebSocket ticker callback — update cached latest price."""
        try:
            last = ticker_data.get("last")
            if last:
                self._latest_price = float(last)
        except Exception as e:
            print(f"[TrendStrategy] _on_ticker_update error: {e}")

    async def execute(self):
        if not await self.validate_params():
            self.update_status("error")
            return

        runtime = self._runtime_params()
        fast_period = runtime["fast_period"]
        slow_period = runtime["slow_period"]
        order_qty = runtime["order_qty"]
        symbol = runtime["symbol"]
        bar = runtime["bar"]
        poll_interval = runtime["poll_interval"]
        enter_on_start = runtime["enter_on_start"]
        closed_candle_only = runtime["closed_candle_only"]

        last_signal = None
        last_processed_candle_ts = None
        first_evaluation = True
        consecutive_errors = 0
        self.update_status("running")

        # Subscribe to WebSocket ticker for real-time price updates.
        self._latest_price = 0.0
        try:
            await market_data_service.subscribe_ticker(symbol, self._on_ticker_update)
        except Exception as e:
            print(f"[TrendStrategy] WS ticker subscribe failed, using REST fallback: {e}")

        # Get initial equity once at start (use shared cache to reduce API calls)
        try:
            from services.strategy_engine import strategy_engine
            balances = await strategy_engine.get_shared_balance(self.account_id)
            if balances:
                self._initial_equity = float(balances.get("totalEq", "0"))
        except Exception:
            self._initial_equity = 0.0

        # Register order fill callback for position tracking
        self.order_manager.on("filled", self._on_order_filled)
        self._position = 0.0  # net position
        self._avg_entry_price = 0.0  # average entry price

        # Restore strategy-level realized PnL and virtual position from latest DB record.
        try:
            from models.pnl import PnlRecord
            db = self.db_session_factory()
            try:
                latest_pnl = db.query(PnlRecord).filter(
                    PnlRecord.strategy_instance_id == self.instance_id
                ).order_by(PnlRecord.recorded_at.desc()).first()
                if latest_pnl:
                    self.restore_realized_pnl(latest_pnl.realized_pnl or 0)
                    self._position = float(latest_pnl.net_position or 0)
                    self._avg_entry_price = float(latest_pnl.avg_buy_price or 0)
                    self.order_manager.restore_position(self._position, self._avg_entry_price)
            finally:
                db.close()
        except Exception:
            pass

        while self._running:
            if self._paused:
                await asyncio.sleep(1)
                continue

            try:
                candles = await self.client.get_candles(
                    symbol,
                    bar=bar,
                    limit=str(slow_period + 10),
                )
                if closed_candle_only and candles and any(len(candle) > 8 for candle in candles):
                    candles = [
                        candle for candle in candles
                        if len(candle) > 8 and str(candle[8]) == "1"
                    ]
                if not candles or len(candles) < slow_period + 1:
                    await asyncio.sleep(min(poll_interval, 5))
                    continue

                ordered_candles = list(reversed(candles))
                candle_ts = str(ordered_candles[-1][0])
                if candle_ts == last_processed_candle_ts:
                    await asyncio.sleep(poll_interval)
                    continue

                closes = [float(candle[4]) for candle in ordered_candles]
                allow_initial_entry = (
                    first_evaluation
                    and enter_on_start
                    and abs(self._position) < 1e-12
                )
                signal, snapshot = self._calculate_signal(
                    closes,
                    fast_period,
                    slow_period,
                    enter_on_start=allow_initial_entry,
                )
                last_processed_candle_ts = candle_ts
                first_evaluation = False

                if signal and signal != last_signal:
                    response = await self.client.place_order(
                        inst_id=symbol,
                        side=signal,
                        ord_type="market",
                        sz=str(order_qty),
                    )
                    order_id, response_error = self._parse_place_order_response(response)
                    if response_error:
                        self._record_event(
                            "order_rejected",
                            f"{signal.upper()} market 下单失败: {symbol} qty={order_qty}; {response_error}",
                            {
                                "symbol": symbol,
                                "side": signal,
                                "quantity": order_qty,
                                "bar": bar,
                                "candle_ts": candle_ts,
                                "signal": snapshot,
                                "response": response,
                            },
                        )
                        raise RuntimeError(response_error)

                    current_price = closes[-1]
                    await self.record_order(
                        symbol,
                        signal,
                        "market",
                        current_price,
                        order_qty,
                        order_id=order_id,
                        status="live",
                    )
                    self._record_event(
                        "signal_triggered",
                        f"{snapshot['reason']} 触发 {signal.upper()}: {symbol} "
                        f"fast_ma={snapshot['fast_ma']:.6f} slow_ma={snapshot['slow_ma']:.6f}",
                        {
                            "symbol": symbol,
                            "side": signal,
                            "order_id": order_id,
                            "bar": bar,
                            "candle_ts": candle_ts,
                            **snapshot,
                        },
                    )
                    last_signal = signal

                consecutive_errors = 0

            except Exception as e:
                # Bug 2: 替换静默 pass，记录错误日志 + 指数退避（参考 grid_strategy 实现）
                consecutive_errors += 1
                error_msg = str(e)
                is_network_error = any(kw in error_msg.lower() for kw in [
                    "winerror 64", "winerror 10054", "winerror 10060", "winerror 10061",
                    "timed out", "connection refused", "ssl", "eof", "network", "connect",
                    "timeout", "unreachable"
                ])

                if is_network_error:
                    backoff = min(2 ** consecutive_errors, 60)
                    print(f"[TrendStrategy] Network error #{consecutive_errors}, backing off {backoff}s: {e}")
                    self._record_event("error", f"网络异常 (第{consecutive_errors}次)，退避 {backoff}s: {error_msg[:200]}")

                    if consecutive_errors >= 10:
                        print(f"[TrendStrategy] Too many network errors ({consecutive_errors}), stopping strategy")
                        self._record_event("error", f"连续网络异常 {consecutive_errors} 次，自动停止策略")
                        self.record_final_pnl()
                        self.update_status("stopped")
                        self._running = False
                        break

                    await asyncio.sleep(backoff)
                    continue
                else:
                    backoff = min(3 * consecutive_errors, 30)
                    print(f"[TrendStrategy] Non-network error #{consecutive_errors}, backing off {backoff}s: {e}")
                    self._record_event("error", f"策略异常 (第{consecutive_errors}次)，退避 {backoff}s: {error_msg[:200]}")

                    if consecutive_errors >= 20:
                        print(f"[TrendStrategy] Too many non-network errors ({consecutive_errors}), stopping strategy")
                        self._record_event("error", f"连续策略异常 {consecutive_errors} 次，自动停止策略: {error_msg[:200]}")
                        self.record_final_pnl()
                        self.update_status("stopped")
                        self._running = False
                        break

                    await asyncio.sleep(backoff)
                    continue

            await asyncio.sleep(poll_interval)

        # Unsubscribe from WebSocket ticker on exit.
        try:
            await market_data_service.unsubscribe_ticker(symbol, self._on_ticker_update)
        except Exception:
            pass
