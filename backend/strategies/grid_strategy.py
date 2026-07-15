import asyncio
import math
import time
import traceback
from strategies.base_strategy import BaseStrategy
from services.market_data_service import market_data_service


class GridStrategy(BaseStrategy):
    # Task 9: post_only 被拒的 OKX 错误码（sCode）集合。
    # 51031 = 订单会立即成交（post_only 单会穿越盘口时被拒）
    _POST_ONLY_REJECT_SCODES = {"51031"}

    @property
    def _post_only(self) -> bool:
        """Task 9: 是否启用 post_only（只挂 maker）下单。"""
        return bool(self.params.get("post_only", False))

    @property
    def _post_only_ord_type(self) -> str:
        """Task 9: 根据 post_only 参数返回 ordType。"""
        return "post_only" if self._post_only else "limit"

    def _is_post_only_rejection(self, s_code: str, s_msg: str) -> bool:
        """Task 9: 判断订单是否因 post_only 被拒。

        OKX 在 post_only 单会立即成交时拒绝，sCode 非 0，
        sMsg 通常含 "post" 或 "立即成交" 字样。
        """
        if s_code == "0":
            return False
        s_msg_lower = (s_msg or "").lower()
        if "post" in s_msg_lower:
            return True
        if "立即成交" in (s_msg or ""):
            return True
        if s_code in self._POST_ONLY_REJECT_SCODES:
            return True
        return False

    async def _batch_place_with_post_only_retry(self, payloads: list[dict]) -> dict:
        """Task 9: 批量下单，post_only 被拒时降级为 limit 重挂（最多 3 轮）。

        流程：
        1. 用原始 payloads（含 post_only）下单
        2. 解析响应，找出 post_only 被拒的订单
        3. 对被拒订单记录 post_only_rejected 事件，降级 ordType 为 limit
        4. sleep 0.5s 后批量重挂被拒订单
        5. 用重挂结果替换原始响应中被拒位置，重复直到无拒绝或达到上限

        max_retries=3 已足够防止无限重挂；重挂时 ordType 已降级为 limit，
        正常情况下 limit 单不会返回 post_only 错误码。

        Returns:
            合并后的响应 dict，data 数组按原始顺序包含各订单最终结果
        """
        resp = await self.client.batch_place_orders(payloads)
        # 非 post_only 模式或请求级别失败，直接返回
        if not self._post_only or resp.get("code") != "0":
            return resp

        max_retries = 3
        data = list(resp.get("data", []))
        # 补齐 data 长度以对齐 payloads
        while len(data) < len(payloads):
            data.append({"sCode": "-1", "sMsg": "no response"})

        for attempt in range(max_retries):
            # 找出 post_only 被拒的索引
            rejected_indices = []
            for i, item in enumerate(data):
                if self._is_post_only_rejection(item.get("sCode", ""), item.get("sMsg", "")):
                    rejected_indices.append(i)

            if not rejected_indices:
                break  # 无 post_only 拒绝，结束

            # 记录被拒事件 + 构造降级 payload
            retry_payloads = []
            for i in rejected_indices:
                orig = payloads[i]
                self._record_event(
                    "post_only_rejected",
                    f"post_only 订单被拒，降级为 limit 重挂: idx={i} px={orig.get('px')} "
                    f"side={orig.get('side')} sCode={data[i].get('sCode')} sMsg={data[i].get('sMsg')}",
                    {
                        "idx": i,
                        "px": orig.get("px"),
                        "side": orig.get("side"),
                        "sCode": data[i].get("sCode"),
                        "sMsg": data[i].get("sMsg"),
                        "downgrade": "limit",
                        "attempt": attempt + 1,
                    },
                )
                retry_p = dict(orig)
                retry_p["ordType"] = "limit"
                retry_payloads.append(retry_p)

            if attempt == max_retries - 1:
                # 达到上限，不再重挂
                self._record_event(
                    "post_only_retry_exhausted",
                    f"post_only 重挂次数达上限 {max_retries}，停止重挂",
                    {"max_retries": max_retries, "rejected_count": len(rejected_indices)},
                )
                break

            await asyncio.sleep(0.5)
            retry_resp = await self.client.batch_place_orders(retry_payloads)
            if retry_resp.get("code") != "0":
                # 请求级别失败，保留原始被拒结果
                break

            retry_data = retry_resp.get("data", [])
            # 用重挂结果替换原始响应中被拒的位置
            for j, orig_idx in enumerate(rejected_indices):
                if j < len(retry_data):
                    data[orig_idx] = retry_data[j]

        resp["data"] = data
        return resp

    async def validate_params(self) -> bool:
        required = ["upper_price", "lower_price", "grid_count", "order_qty", "symbol"]
        for key in required:
            if key not in self.params:
                return False
        # 防御性类型转换：JSON 字段可能存储为字符串
        try:
            upper = float(self.params["upper_price"])
            lower = float(self.params["lower_price"])
            grid_count = int(self.params["grid_count"])
            order_qty = float(self.params["order_qty"])
        except (TypeError, ValueError):
            return False
        if upper <= lower:
            return False
        if grid_count < 2:
            return False
        if order_qty <= 0:
            return False
        return True

    def _find_grid_index(self, px: float) -> int | None:
        """Bug 3: 精确档位索引匹配，容差作为兜底。

        优先精确匹配（rounded grid price == px，用 1e-9 容差消除浮点误差）；
        精确匹配失败时回退到容差 < tick_size * 0.6 的最近层级。
        解决密集网格下纯容差匹配可能错位到相邻档位的问题。
        """
        if not getattr(self, "_grid_levels", None):
            return None
        # 1. 精确档位匹配
        for i, level in enumerate(self._grid_levels):
            price = round(round(level / self._grid_tick_size) * self._grid_tick_size, self._grid_tick_decimals)
            if abs(price - px) < 1e-9:
                return i
        # 2. 兜底：容差范围内找最近层级
        best_idx = None
        best_diff = self._grid_tick_size * 0.6
        for i, level in enumerate(self._grid_levels):
            price = round(round(level / self._grid_tick_size) * self._grid_tick_size, self._grid_tick_decimals)
            diff = abs(price - px)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        return best_idx

    def _on_ticker_update(self, ticker_data: dict):
        """WebSocket ticker callback — update cached latest price."""
        try:
            last = ticker_data.get("last")
            if last:
                self._latest_price = float(last)
        except Exception as e:
            print(f"[GridStrategy] _on_ticker_update error: {e}")

    async def _on_order_filled(self, order_info):
        """Handle order fill event from OrderManager (WebSocket or REST fallback)."""
        # SubTask 8.3: 快速重挂期间抑制补单回调，避免与重挂冲突
        if getattr(self, "_suppress_fill_callback", False):
            return
        symbol = order_info.symbol
        side = order_info.side
        px = float(order_info.px) if order_info.px else 0
        sz = float(order_info.sz) if order_info.sz else 0
        ordId = order_info.ordId

        # Bug 3: 精确档位索引匹配，容差作为兜底
        grid_idx = self._find_grid_index(px)

        if grid_idx is None:
            return

        if side == "buy":
            if grid_idx in self._active_buy_orders:
                del self._active_buy_orders[grid_idx]
            await self.record_order(symbol, "buy", "limit", px, sz, order_id=ordId, status="filled")

            sell_price = round(round((self._grid_levels[grid_idx] + self._grid_step) / self._grid_tick_size) * self._grid_tick_size, self._grid_tick_decimals)
            sell_price_str = f"{sell_price:.{self._grid_tick_decimals}f}"
            # 去重：目标档位已有 live 卖单时跳过补单，避免同价位重复下单
            if (grid_idx + 1) in self._active_sell_orders:
                self._record_event("order_warn",
                                   f"买单成交后补卖单跳过: grid_idx+1={grid_idx + 1} 已有 live 卖单 ordId={self._active_sell_orders[grid_idx + 1]}",
                                   {"grid_idx": grid_idx, "sell_px": sell_price_str,
                                    "existing_ord_id": self._active_sell_orders[grid_idx + 1]})
                return
            # SubTask 7.1: 批量预挂卖单（当前档位），记录补单延迟
            # Task 9: post_only 模式下用 ordType=post_only，被拒时自动降级重挂
            fill_received_ts = time.time()
            sell_payloads = [
                {"instId": symbol, "side": "sell", "ordType": self._post_only_ord_type,
                 "sz": str(self._grid_order_qty), "px": sell_price_str}
            ]
            try:
                sell_resp = await self._batch_place_with_post_only_retry(sell_payloads)
            except Exception as e:
                self._record_event("order_failed",
                                   f"买单成交后批量下卖单异常: grid_idx={grid_idx} px={sell_price_str} err={e}")
                return
            sell_placed_ts = time.time()
            latency = sell_placed_ts - fill_received_ts
            self._latency_samples.append(latency)
            # SubTask 7.5: 延迟超阈值告警
            latency_threshold = float(self.params.get("latency_threshold", 2.0))
            if latency > latency_threshold:
                self._record_event("order_latency",
                                   f"补单延迟超阈值: grid_idx={grid_idx} latency={latency:.3f}s threshold={latency_threshold}s",
                                   {"latency": latency, "threshold": latency_threshold,
                                    "buy_ord_id": ordId, "grid_idx": grid_idx, "sell_px": sell_price_str})
            if sell_resp.get("code") == "0":
                data = sell_resp.get("data", [])
                if data and data[0].get("sCode") == "0":
                    sell_ord_id = data[0].get("ordId", "")
                    self._active_sell_orders[grid_idx + 1] = sell_ord_id
                    await self.record_order(symbol, "sell", "limit", sell_price,
                                      self._grid_order_qty, order_id=sell_ord_id, status="live")
                else:
                    s_code = data[0].get("sCode", "") if data else ""
                    s_msg = data[0].get("sMsg", "") if data else ""
                    self._record_event("order_failed",
                                       f"买单成交后批量下卖单失败: grid_idx={grid_idx} px={sell_price_str} sCode={s_code} {s_msg}",
                                       {"grid_idx": grid_idx, "px": sell_price_str, "sCode": s_code, "sMsg": s_msg})
            else:
                self._record_event("order_failed",
                                   f"买单成交后批量下卖单请求失败: code={sell_resp.get('code')} msg={sell_resp.get('msg', '')}",
                                   {"code": sell_resp.get("code"), "msg": sell_resp.get("msg", "")})

        elif side == "sell":
            if grid_idx in self._active_sell_orders:
                del self._active_sell_orders[grid_idx]

            if grid_idx == 0:
                # 边界防护：grid_idx=0 不应出现卖单成交，跳过 realized 计算
                self._record_event("order_warn",
                                   f"grid_idx=0 出现卖单成交，跳过 realized 计算: {symbol} ordId={ordId} px={px} qty={sz}",
                                   {"order_id": ordId, "side": "sell", "price": px, "quantity": sz, "grid_idx": 0})
            else:
                # 查找对应买单的实际成交价
                buy_ord_id = self._active_buy_orders.get(grid_idx - 1, "")
                buy_fill_px = self.order_manager.get_order_fill_px(buy_ord_id) if buy_ord_id else 0.0
                if buy_fill_px > 0:
                    buy_px_for_pnl = buy_fill_px
                else:
                    # fillPx 缺失时回退使用网格档位价
                    buy_px_for_pnl = self._grid_levels[grid_idx - 1]
                    self._record_event("order_warn",
                                       f"买单 fillPx 缺失，回退使用网格档位价: grid_idx={grid_idx} buy_ord_id={buy_ord_id} fallback_px={buy_px_for_pnl}",
                                       {"grid_idx": grid_idx, "buy_ord_id": buy_ord_id, "fallback_px": buy_px_for_pnl})
                buy_fee = self.order_manager.get_order_fee(buy_ord_id) if buy_ord_id else 0.0
                sell_fee = self.order_manager.get_order_fee(ordId)
                # OKX fee 为负数（扣除），- abs(fee) 才是真正扣减手续费
                cycle_pnl = (px - buy_px_for_pnl) * sz - abs(buy_fee) - abs(sell_fee)
                self.add_realized_pnl(cycle_pnl)
            await self.record_order(symbol, "sell", "limit", px, sz, order_id=ordId, status="filled")

            buy_price = round(round((self._grid_levels[grid_idx] - self._grid_step) / self._grid_tick_size) * self._grid_tick_size, self._grid_tick_decimals)
            buy_price_str = f"{buy_price:.{self._grid_tick_decimals}f}"
            # 去重：目标档位已有 live 买单时跳过补单，避免同价位重复下单
            if (grid_idx - 1) in self._active_buy_orders:
                self._record_event("order_warn",
                                   f"卖单成交后补买单跳过: grid_idx-1={grid_idx - 1} 已有 live 买单 ordId={self._active_buy_orders[grid_idx - 1]}",
                                   {"grid_idx": grid_idx, "buy_px": buy_price_str,
                                    "existing_ord_id": self._active_buy_orders[grid_idx - 1]})
                return
            # Task 9: post_only 模式下用 ordType=post_only，被拒时自动降级重挂
            try:
                buy_payloads = [
                    {"instId": symbol, "side": "buy", "ordType": self._post_only_ord_type,
                     "sz": str(self._grid_order_qty), "px": buy_price_str}
                ]
                buy_resp = await self._batch_place_with_post_only_retry(buy_payloads)
            except Exception as e:
                self._record_event("order_failed",
                                   f"卖单成交后下买单异常: grid_idx={grid_idx} px={buy_price_str} err={e}")
                return
            if buy_resp.get("code") == "0":
                buy_ord_id = buy_resp.get("data", [{}])[0].get("ordId", "")
                self._active_buy_orders[grid_idx - 1] = buy_ord_id
                await self.record_order(symbol, "buy", "limit", buy_price,
                                  self._grid_order_qty, order_id=buy_ord_id, status="live")
            else:
                self._record_event("order_failed",
                                   f"卖单成交后下买单失败: grid_idx={grid_idx} px={buy_price_str} code={buy_resp.get('code')} msg={buy_resp.get('msg', '')}")

    def _rebuild_active_dicts(self, symbol: str):
        """Rebuild active_buy_orders and active_sell_orders from OrderManager."""
        new_buy: dict[int, str] = {}
        new_sell: dict[int, str] = {}
        for order in self.order_manager.get_active_orders():
            if order.symbol != symbol:
                continue
            px_val = float(order.px) if order.px else 0
            # Bug 3: 精确档位索引匹配，容差作为兜底
            grid_idx = self._find_grid_index(px_val)
            if grid_idx is not None:
                if order.side == "buy":
                    new_buy[grid_idx] = order.ordId
                elif order.side == "sell":
                    new_sell[grid_idx] = order.ordId
        self._active_buy_orders = new_buy
        self._active_sell_orders = new_sell

    def get_latency_stats(self) -> dict:
        """返回补单延迟统计（SubTask 7.5）。

        Returns:
            {"p50": float, "p95": float, "count": int}；无样本返回全 0。
        """
        samples = getattr(self, "_latency_samples", None)
        if not samples:
            return {"p50": 0.0, "p95": 0.0, "count": 0}
        sorted_samples = sorted(samples)
        n = len(sorted_samples)
        p50 = sorted_samples[min(int(n * 0.5), n - 1)]
        p95 = sorted_samples[min(int(n * 0.95), n - 1)]
        return {"p50": p50, "p95": p95, "count": n}

    async def _place_grid_orders(self, symbol: str, current_price: float,
                                grid_levels: list[float] | None = None):
        """批量下网格订单（SubTask 8.3 提取自 execute）。

        根据 current_price 划分买单（level <= price）和卖单（level > price），
        分批 batch_place_orders。grid_levels 默认用 self._grid_levels。
        """
        if grid_levels is None:
            grid_levels = self._grid_levels
        order_qty = self._grid_order_qty
        tick_size = self._grid_tick_size
        tick_decimals = self._grid_tick_decimals

        buy_orders = []
        sell_orders = []
        for i, level in enumerate(grid_levels):
            price = round(round(level / tick_size) * tick_size, tick_decimals)
            price_str = f"{price:.{tick_decimals}f}"
            if level <= current_price:
                # 去重：跳过已有 live 买单的档位，避免重复下单（重启/补单场景）
                if i in self._active_buy_orders:
                    continue
                buy_orders.append({"idx": i, "level": level, "px": price_str})
            elif level > current_price:
                # 去重：跳过已有 live 卖单的档位
                if i in self._active_sell_orders:
                    continue
                sell_orders.append({"idx": i, "level": level, "px": price_str})

        BATCH_SIZE = 20
        # TODO(后续 Task): 批量下单接入资金上限校验，当前 batch_place_orders 无单笔校验
        # Task 9: post_only 模式下 ordType=post_only，被拒时自动降级重挂
        for batch_start in range(0, len(buy_orders), BATCH_SIZE):
            batch = buy_orders[batch_start:batch_start + BATCH_SIZE]
            order_payloads = [
                {"instId": symbol, "side": "buy", "ordType": self._post_only_ord_type, "sz": str(order_qty), "px": o["px"]}
                for o in batch
            ]
            resp = await self._batch_place_with_post_only_retry(order_payloads)
            if resp.get("code") == "0":
                for j, o in enumerate(batch):
                    try:
                        data = resp.get("data", [])
                        if j < len(data) and data[j].get("sCode") == "0":
                            order_id = data[j].get("ordId", "")
                            self._active_buy_orders[o["idx"]] = order_id
                            await self.record_order(symbol, "buy", "limit", o["level"], order_qty, order_id=order_id, status="live")
                        else:
                            s_code = data[j].get("sCode", "") if j < len(data) else ""
                            s_msg = data[j].get("sMsg", "") if j < len(data) else ""
                            self._record_event("order_failed",
                                               f"批量买单失败: idx={o['idx']} px={o['px']} sCode={s_code} {s_msg}",
                                               {"idx": o["idx"], "px": o["px"], "sCode": s_code, "sMsg": s_msg})
                    except Exception as e:
                        print(f"[GridStrategy] record buy order error: {e}")
            else:
                self._record_event("order_failed",
                                   f"批量买单请求失败: code={resp.get('code')} msg={resp.get('msg', '')}",
                                   {"code": resp.get("code"), "msg": resp.get("msg", "")})
            await asyncio.sleep(0.15)

        for batch_start in range(0, len(sell_orders), BATCH_SIZE):
            batch = sell_orders[batch_start:batch_start + BATCH_SIZE]
            order_payloads = [
                {"instId": symbol, "side": "sell", "ordType": self._post_only_ord_type, "sz": str(order_qty), "px": o["px"]}
                for o in batch
            ]
            resp = await self._batch_place_with_post_only_retry(order_payloads)
            if resp.get("code") == "0":
                for j, o in enumerate(batch):
                    try:
                        data = resp.get("data", [])
                        if j < len(data) and data[j].get("sCode") == "0":
                            order_id = data[j].get("ordId", "")
                            self._active_sell_orders[o["idx"]] = order_id
                            await self.record_order(symbol, "sell", "limit", o["level"], order_qty, order_id=order_id, status="live")
                        else:
                            s_code = data[j].get("sCode", "") if j < len(data) else ""
                            s_msg = data[j].get("sMsg", "") if j < len(data) else ""
                            self._record_event("order_failed",
                                               f"批量卖单失败: idx={o['idx']} px={o['px']} sCode={s_code} {s_msg}",
                                               {"idx": o["idx"], "px": o["px"], "sCode": s_code, "sMsg": s_msg})
                    except Exception as e:
                        print(f"[GridStrategy] record sell order error: {e}")
            else:
                self._record_event("order_failed",
                                   f"批量卖单请求失败: code={resp.get('code')} msg={resp.get('msg', '')}",
                                   {"code": resp.get("code"), "msg": resp.get("msg", "")})
            await asyncio.sleep(0.15)

    async def _check_volatility_spike(self, symbol: str, current_price: float) -> None:
        """检查波动率是否触发快速路径（SubTask 8.2）。

        在主循环内价格更新后调用。波动率超阈值时：
        - 首次触发：记录 volatility_spike 事件 + 调用 _rapid_realign_grid
        - 持续中：仅延长 spike_until
        波动率回落且 spike 窗口已过：重置 _spike_active。
        """
        vol = market_data_service.get_volatility(symbol)
        vol_threshold = float(self.params.get("volatility_threshold", 0.01))
        now_ts = time.time()
        if vol > vol_threshold:
            was_spiking = self._spike_active
            self._volatility_spike_until = now_ts + float(self.params.get("spike_duration", 10.0))
            if not was_spiking:
                self._spike_active = True
                self._record_event("volatility_spike",
                                   f"波动率 {vol:.4f} 超阈值 {vol_threshold}",
                                   {"volatility": vol, "threshold": vol_threshold,
                                    "symbol": symbol, "current_price": current_price})
                try:
                    await self._rapid_realign_grid(symbol, current_price)
                except Exception as e:
                    self._record_event("error", f"快速重挂异常: {e}", {"error": str(e)})
        else:
            # 波动率回落且 spike 窗口已过：重置标志，允许下次触发
            if self._spike_active and now_ts >= self._volatility_spike_until:
                self._spike_active = False

    async def _rapid_realign_grid(self, symbol: str, current_price: float):
        """快速路径：批量撤单 + 基于新价位重挂网格（SubTask 8.3）。

        在波动 spike 首次触发时调用：
        1. 设置 _suppress_fill_callback 抑制 _on_order_filled 回调内的补单
        2. 撤销所有活跃订单（order_manager.cancel_all）
        3. 清空 _active_buy_orders / _active_sell_orders
        4. 基于 current_price 重新计算网格档位并重挂
        5. 记录 grid_realigned 事件
        6. 释放抑制标志
        """
        self._suppress_fill_callback = True
        try:
            cancelled = await self.order_manager.cancel_all(symbol)
            # 从 OrderManager 重建跟踪字典（而非无条件清空），
            # cancel_all 失败的订单仍留在 OrderManager 中，
            # 重建后 _place_grid_orders 的去重逻辑会跳过这些档位，避免重复下单
            self._rebuild_active_dicts(symbol)
            remaining = len(self._active_buy_orders) + len(self._active_sell_orders)
            if remaining > 0:
                self._record_event("order_warn",
                                   f"快速重挂: cancel_all 后仍有 {remaining} 个未撤销订单, 将跳过这些档位",
                                   {"cancelled": cancelled, "remaining": remaining})

            # 基于新价格重算网格档位（与 execute 中的自动校正逻辑一致）
            upper = float(self.params["upper_price"])
            lower = float(self.params["lower_price"])
            grid_count = int(self.params["grid_count"])
            grid_center = (upper + lower) / 2
            deviation = abs(current_price - grid_center) / grid_center if grid_center > 0 else 1
            if current_price < lower or current_price > upper or deviation > 0.05:
                grid_width = upper - lower
                new_lower = round(current_price - grid_width / 2, self._grid_tick_decimals)
                new_upper = round(current_price + grid_width / 2, self._grid_tick_decimals)
                self.params["upper_price"] = new_upper
                self.params["lower_price"] = new_lower
                upper, lower = new_upper, new_lower
                step = (upper - lower) / (grid_count - 1)
                grid_levels = [lower + i * step for i in range(grid_count)]
                self._grid_levels = grid_levels
                self._grid_step = step
                # 持久化更新参数
                try:
                    from models.strategy import StrategyInstance
                    _db = self.db_session_factory()
                    try:
                        _inst = _db.query(StrategyInstance).filter(
                            StrategyInstance.id == self.instance_id).first()
                        if _inst:
                            _inst.params = self.params
                            _db.commit()
                    finally:
                        _db.close()
                except Exception:
                    pass
                self._record_event("grid_realigned",
                                   f"波动 spike 网格校正: 中心价 {grid_center} → {current_price}, [{lower}, {upper}]")

            # 基于新价位重挂网格
            await self._place_grid_orders(symbol, current_price)
            self._record_event("grid_realigned",
                               f"波动 spike 触发快速重挂: {symbol} cancelled={cancelled} price={current_price}",
                               {"symbol": symbol, "cancelled": cancelled,
                                "current_price": current_price})
        finally:
            self._suppress_fill_callback = False

    async def execute(self):
        try:
            if not await self.validate_params():
                self.update_status("error")
                return

            # 类型规范化：确保数值字段为 float/int（JSON 可能存为字符串）
            upper = float(self.params["upper_price"])
            lower = float(self.params["lower_price"])
            grid_count = int(self.params["grid_count"])
            order_qty = float(self.params["order_qty"])
            symbol = self.params["symbol"]

            step = (upper - lower) / (grid_count - 1)
            grid_levels = [lower + i * step for i in range(grid_count)]

            ticker = await self.client.get_ticker(symbol)
            if not ticker:
                self.update_status("error")
                return
            current_price = float(ticker[0]["last"])

            # Subscribe to WebSocket ticker for real-time price updates.
            self._latest_price = current_price
            try:
                await market_data_service.subscribe_ticker(symbol, self._on_ticker_update)
            except Exception as e:
                print(f"[GridStrategy] WS ticker subscribe failed, using REST fallback: {e}")

            self.update_status("running")

            # Get initial equity once at start (use shared cache to reduce API calls)
            try:
                from services.strategy_engine import strategy_engine
                balances = await strategy_engine.get_shared_balance(self.account_id)
                if balances:
                    self._initial_equity = float(balances.get("totalEq", "0"))
            except Exception:
                self._initial_equity = 0.0

            # Restore realized PnL from latest DB record
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

            tick_size = 0.1 if "-SWAP" in symbol else 0.01
            tick_decimals = 1 if "-SWAP" in symbol else 2

            # 自动校正：当前价不在网格区间内，或偏离中心超过 5% 时，以当前价为中心重算上下轨
            grid_center = (upper + lower) / 2
            deviation = abs(current_price - grid_center) / grid_center if grid_center > 0 else 1
            if current_price < lower or current_price > upper or deviation > 0.05:
                grid_width = upper - lower
                new_lower = round(current_price - grid_width / 2, tick_decimals)
                new_upper = round(current_price + grid_width / 2, tick_decimals)
                self.params["upper_price"] = new_upper
                self.params["lower_price"] = new_lower
                upper, lower = new_upper, new_lower
                step = (upper - lower) / (grid_count - 1)
                grid_levels = [lower + i * step for i in range(grid_count)]
                try:
                    from models.strategy import StrategyInstance
                    _db = self.db_session_factory()
                    try:
                        _inst = _db.query(StrategyInstance).filter(
                            StrategyInstance.id == self.instance_id).first()
                        if _inst:
                            _inst.params = self.params
                            _db.commit()
                    finally:
                        _db.close()
                except Exception:
                    pass
                print(f"[GridStrategy] execute 网格自动校正: 中心价 {grid_center} → {current_price}, [{lower}, {upper}]")

            # Store grid data as instance variables for callback access
            self._grid_levels = grid_levels
            self._grid_step = step
            self._grid_tick_size = tick_size
            self._grid_tick_decimals = tick_decimals
            self._grid_order_qty = order_qty
            self._grid_symbol = symbol
            self._active_buy_orders: dict[int, str] = {}
            self._active_sell_orders: dict[int, str] = {}
            # SubTask 7.5: 补单延迟样本（成交事件触发→补单下单完成）
            self._latency_samples: list[float] = []
            # SubTask 8.2: 波动 spike 快速路径状态
            self._volatility_spike_until = 0.0
            self._spike_active = False
            # SubTask 8.3: 快速重挂时抑制 _on_order_filled 补单回调
            self._suppress_fill_callback = False

            # Register order fill callback
            self.order_manager.on("filled", self._on_order_filled)

            # Sync existing orders from DB on restart
            synced = await self.sync_orders(symbol)
            # Rebuild active orders from synced DB orders
            try:
                from models.order import Order
                db = self.db_session_factory()
                try:
                    live_orders = db.query(Order).filter(
                        Order.strategy_instance_id == self.instance_id,
                        Order.status == "live"
                    ).all()
                    stale_orders: list[tuple[str, str, float]] = []  # (order_id, side, price)
                    for o in live_orders:
                        if not o.order_id:
                            continue
                        # Bug 3: 精确档位索引匹配，容差作为兜底
                        grid_idx = self._find_grid_index(float(o.price or 0))
                        if grid_idx is not None:
                            if o.side == "buy":
                                self._active_buy_orders[grid_idx] = o.order_id
                            elif o.side == "sell":
                                self._active_sell_orders[grid_idx] = o.order_id
                        else:
                            # 网格自动校正后，旧网格档位上的残留订单需撤销
                            stale_orders.append((o.order_id, o.side or "", float(o.price or 0)))

                    # 撤销不在新网格档位上的残留订单（网格重校正后常见）
                    if stale_orders:
                        canceled_count = 0
                        for order_id, side, px in stale_orders:
                            try:
                                await self.client.cancel_order(symbol, order_id)
                                # 更新 DB 状态
                                db.query(Order).filter(Order.order_id == order_id).update(
                                    {Order.status: "canceled"}, synchronize_session=False)
                                canceled_count += 1
                            except Exception as e:
                                print(f"[GridStrategy] 撤销残留订单失败 ordId={order_id}: {e}")
                        if canceled_count:
                            db.commit()
                            self._record_event("order_canceled",
                                f"网格校正清理残留订单: 撤销 {canceled_count}/{len(stale_orders)} 笔",
                                {"canceled": canceled_count, "total_stale": len(stale_orders),
                                 "orders": [{"ordId": oid, "side": s, "px": p} for oid, s, p in stale_orders]})
                finally:
                    db.close()
            except Exception:
                pass

            # 批量下初始网格订单（SubTask 8.3: 提取为可复用方法 _place_grid_orders）
            await self._place_grid_orders(symbol, current_price, grid_levels)
        except Exception as e:
            print(f"[GridStrategy] execute error: {e}\n{traceback.format_exc()}")
            self._record_event("error", f"策略执行异常: {e}", {"traceback": traceback.format_exc()})
            # Unsubscribe from WebSocket ticker if subscription was made.
            try:
                symbol = locals().get("symbol", self.params.get("symbol", ""))
                if symbol:
                    await market_data_service.unsubscribe_ticker(symbol, self._on_ticker_update)
            except Exception:
                pass
            self.update_status("error")
            return

        last_rest_check = 0.0
        # SubTask 7.3: REST 兜底间隔可配（默认 5s，原 15s）
        rest_poll_interval = float(self.params.get("rest_poll_interval", 5.0))
        consecutive_errors = 0

        while self._running:
            if self._paused:
                await asyncio.sleep(1)
                continue

            try:
                # Prefer WebSocket-cached ticker; fall back to REST polling.
                ws_ticker = market_data_service.get_latest_ticker(symbol)
                if ws_ticker and ws_ticker.get("last"):
                    current_price = float(ws_ticker["last"])
                else:
                    tickers = await self.client.get_ticker(symbol)
                    if not tickers:
                        await asyncio.sleep(5)
                        continue
                    current_price = float(tickers[0]["last"])

                # Fallback REST polling (SubTask 7.3: 间隔可配，默认 5s)
                now = time.time()
                if now - last_rest_check > rest_poll_interval:
                    last_rest_check = now
                    for order in self.order_manager.get_active_orders():
                        if order.symbol != symbol:
                            continue
                        try:
                            info = await self.client.get_order(symbol, order.ordId)
                            if info and len(info) > 0:
                                state = info[0].get("state", "")
                                if state != order.state:
                                    self.order_manager.update_order(
                                        order.ordId,
                                        state=state,
                                        fillPx=info[0].get("fillPx", ""),
                                        fillSz=info[0].get("fillSz", ""),
                                        fee=info[0].get("fee", ""),
                                        uTime=info[0].get("uTime", ""),
                                    )
                        except Exception:
                            pass

                # Rebuild active_buy_orders and active_sell_orders from OrderManager
                self._rebuild_active_dicts(symbol)

                consecutive_errors = 0

                # 保证金占用率检查（SubTask 3.2）：合约且保证金临界时跳过本轮下单
                if not await self.check_margin_risk(symbol):
                    await asyncio.sleep(3)
                    continue

                # SubTask 8.2: 波动率检测，触发快速路径
                await self._check_volatility_spike(symbol, current_price)

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
                    backoff = min(2 ** consecutive_errors, 60)  # 指数退避，上限 60s
                    print(f"[GridStrategy] Network error #{consecutive_errors}, backing off {backoff}s: {e}")
                    self._record_event("error", f"网络异常 (第{consecutive_errors}次)，退避 {backoff}s: {error_msg[:200]}")

                    if consecutive_errors >= 10:
                        print(f"[GridStrategy] Too many network errors ({consecutive_errors}), stopping strategy")
                        self._record_event("error", f"连续网络异常 {consecutive_errors} 次，自动停止策略")
                        self.record_final_pnl()
                        self.update_status("stopped")
                        # 设置停止标志，退出循环
                        self._running = False
                        break

                    await asyncio.sleep(backoff)
                    continue
                else:
                    # 非网络异常，使用线性退避，避免快速循环刷日志
                    backoff = min(3 * consecutive_errors, 30)
                    print(f"[GridStrategy] Non-network error #{consecutive_errors}, backing off {backoff}s: {e}")
                    self._record_event("error", f"策略异常 (第{consecutive_errors}次)，退避 {backoff}s: {error_msg[:200]}")

                    if consecutive_errors >= 20:
                        print(f"[GridStrategy] Too many non-network errors ({consecutive_errors}), stopping strategy")
                        self._record_event("error", f"连续策略异常 {consecutive_errors} 次，自动停止策略: {error_msg[:200]}")
                        self.record_final_pnl()
                        self.update_status("stopped")
                        self._running = False
                        break

                    await asyncio.sleep(backoff)
                    continue

            # SubTask 7.2 / 8.2: 主循环间隔可配，spike 期间使用更短间隔
            if time.time() < self._volatility_spike_until:
                await asyncio.sleep(self.params.get("spike_loop_interval", 0.5))
            else:
                await asyncio.sleep(self.params.get("loop_interval", 1.0))

        # Unsubscribe from WebSocket ticker on exit.
        try:
            await market_data_service.unsubscribe_ticker(symbol, self._on_ticker_update)
        except Exception:
            pass

        for _, order_id in {**self._active_buy_orders, **self._active_sell_orders}.items():
            try:
                await self.client.cancel_order(symbol, order_id)
            except Exception:
                pass