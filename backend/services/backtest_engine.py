"""真实历史回测引擎。

同步实现（基于历史数据离线计算），不依赖 asyncio。

支持策略类型：
- grid：网格策略，在 K 线价格区间内挂限价单，按 K 线最高/最低价撮合
- trend：趋势策略，按 K 线收盘价计算 MA 交叉信号，市价单按收盘价+滑点成交
- arbitrage：套利策略（占位，暂复用 trend 撮合逻辑）

撮合规则：
- 限价买单：buy_price >= K 线最低价 则成交，成交价 = max(buy_price, low)
- 限价卖单：sell_price <= K 线最高价 则成交，成交价 = min(sell_price, high)
- 市价单：按 K 线收盘价 ± 滑点成交
- 手续费：fee_rate * 成交金额（成交金额 = 成交价 * 数量）
"""
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import httpx

from config import OKX_BASE_URL, OKX_DNS_OVERRIDE


# ============================================================
# 数据结构
# ============================================================

@dataclass
class BacktestConfig:
    """回测配置。"""
    symbol: str                            # OKX instId, 如 BTC-USDT
    strategy_type: str                     # grid | trend | arbitrage
    params: dict                           # 策略参数
    start_time: str                        # ISO8601, 如 "2024-01-01T00:00:00Z"
    end_time: str                          # ISO8601
    interval: str = "1H"                   # OKX bar 参数：1m/5m/15m/1H/4H/1D
    initial_capital: float = 10000.0       # 初始资金（USDT）
    slippage: float = 0.001                # 滑点，0.001 = 0.1%
    fee_rate: float = 0.001                # 手续费率，0.001 = 0.1%


@dataclass
class Trade:
    """单笔成交记录。"""
    timestamp: str       # ISO8601
    side: str            # buy | sell
    order_type: str      # limit | market
    price: float         # 成交价
    quantity: float      # 成交数量
    fee: float           # 手续费
    pnl: float = 0.0     # 该笔成交已实现盈亏（仅平仓时计算）


@dataclass
class EquityPoint:
    """权益曲线单点。"""
    timestamp: str
    equity: float
    cash: float
    position_value: float


@dataclass
class BacktestResult:
    """回测结果。"""
    config: dict
    trades: list[dict]
    equity_curve: list[dict]
    metrics: dict
    kline_count: int = 0
    error: str | None = None


# ============================================================
# 撮合引擎
# ============================================================

class MatchingEngine:
    """撮合引擎：根据单根 K 线撮合订单。"""

    def __init__(self, slippage: float, fee_rate: float):
        self.slippage = slippage
        self.fee_rate = fee_rate

    def match_limit_buy(self, order_price: float, kline_low: float) -> tuple[bool, float, float]:
        """限价买单撮合。

        Returns:
            (是否成交, 成交价, 手续费占金额比例前缀)
            成交价 = max(order_price, low)  —— 买单价 >= 最低价即成交
        """
        if order_price >= kline_low:
            fill_price = max(order_price, kline_low)
            return True, fill_price, fill_price
        return False, 0.0, 0.0

    def match_limit_sell(self, order_price: float, kline_high: float) -> tuple[bool, float, float]:
        """限价卖单撮合。

        成交价 = min(order_price, high)  —— 卖单价 <= 最高价即成交
        """
        if order_price <= kline_high:
            fill_price = min(order_price, kline_high)
            return True, fill_price, fill_price
        return False, 0.0, 0.0

    def match_market_buy(self, close_price: float) -> float:
        """市价买单：收盘价 * (1 + slippage)。"""
        return close_price * (1.0 + self.slippage)

    def match_market_sell(self, close_price: float) -> float:
        """市价卖单：收盘价 * (1 - slippage)。"""
        return close_price * (1.0 - self.slippage)

    def calc_fee(self, fill_price: float, quantity: float) -> float:
        """手续费 = fee_rate * 成交金额。"""
        return self.fee_rate * fill_price * quantity


# ============================================================
# 指标计算
# ============================================================

def _safe_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def compute_metrics(
    equity_curve: list[EquityPoint],
    trades: list[Trade],
    initial_capital: float,
) -> dict:
    """计算回测指标。"""
    if not equity_curve:
        return {
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "win_rate": 0.0,
            "trade_count": 0,
            "profit_factor": 0.0,
            "final_equity": initial_capital,
        }

    final_equity = equity_curve[-1].equity
    total_return = (final_equity - initial_capital) / initial_capital if initial_capital > 0 else 0.0

    # 最大回撤
    peak = equity_curve[0].equity
    max_dd = 0.0
    for pt in equity_curve:
        if pt.equity > peak:
            peak = pt.equity
        if peak > 0:
            dd = (peak - pt.equity) / peak
            if dd > max_dd:
                max_dd = dd

    # 日收益率序列（按权益曲线相邻点）
    daily_returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1].equity
        curr = equity_curve[i].equity
        if prev > 0:
            daily_returns.append((curr - prev) / prev)

    mean_r = sum(daily_returns) / len(daily_returns) if daily_returns else 0.0
    std_r = _safe_std(daily_returns)
    sharpe = (mean_r / std_r * math.sqrt(365)) if std_r > 0 else 0.0

    # 胜率与盈亏比：仅基于有 pnl 的成交
    pnls = [t.pnl for t in trades if t.pnl != 0.0]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    trade_count = len(pnls)
    win_rate = (len(wins) / trade_count) if trade_count > 0 else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

    return {
        "total_return": round(total_return, 6),
        "max_drawdown": round(max_dd, 6),
        "sharpe_ratio": round(sharpe, 6),
        "win_rate": round(win_rate, 6),
        "trade_count": trade_count,
        "profit_factor": round(profit_factor, 6) if profit_factor != float("inf") else float("inf"),
        "final_equity": round(final_equity, 6),
    }


# ============================================================
# BacktestEngine
# ============================================================

class BacktestEngine:
    """回测引擎。

    通过 OKX 公共行情 API 拉取历史 K 线，同步遍历模拟策略执行。
    """

    def __init__(self):
        # 内存缓存：(symbol, bar) -> list[Kline]，按时间升序
        self._kline_cache: dict[tuple[str, str], list[dict]] = {}
        self._http_client: httpx.Client | None = None

    # -------- HTTP client with DNS override --------

    def _get_http_client(self) -> httpx.Client:
        if self._http_client is None:
            dns_map: dict[str, str] = {}
            if OKX_DNS_OVERRIDE:
                for pair in OKX_DNS_OVERRIDE.split(","):
                    pair = pair.strip()
                    if ":" in pair:
                        host, ip = pair.split(":", 1)
                        dns_map[host.strip()] = ip.strip()

            transport = None
            if dns_map:
                dns_map_ref = dns_map

                class DNSOverrideTransport(httpx.HTTPTransport):
                    def handle_request(self, request):
                        from urllib.parse import urlparse
                        parsed = urlparse(str(request.url))
                        host = parsed.hostname or ""
                        if host in dns_map_ref:
                            request.url = request.url.copy_with(host=dns_map_ref[host])
                            request.headers["Host"] = host
                        return super().handle_request(request)

                transport = DNSOverrideTransport()

            self._http_client = httpx.Client(
                timeout=httpx.Timeout(connect=8.0, read=15.0, write=5.0, pool=3.0),
                follow_redirects=True,
                transport=transport,
            )
        return self._http_client

    def close(self):
        if self._http_client is not None:
            try:
                self._http_client.close()
            except Exception:
                pass
            self._http_client = None

    # -------- K 线拉取（同步，调用 OKX 公共 API，分页） --------

    @staticmethod
    def _to_ms(ts: str) -> int:
        """ISO8601 字符串转毫秒时间戳。"""
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)

    @staticmethod
    def _parse_kline(row: list) -> dict | None:
        """OKX K 线行 -> dict。

        OKX candles 字段：[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        """
        try:
            return {
                "ts": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]) if len(row) > 5 and row[5] else 0.0,
            }
        except (IndexError, ValueError, TypeError):
            return None

    def fetch_historical_klines(
        self,
        symbol: str,
        start_time: str,
        end_time: str,
        interval: str = "1H",
    ) -> list[dict]:
        """拉取历史 K 线（同步，分页，每页最多 300 根）。

        OKX /api/v5/market/history-candles 支持历史数据，使用 before/after 翻页。
        返回结果按时间升序排列，并已去重。

        Args:
            symbol: OKX instId
            start_time: ISO8601 起始时间
            end_time: ISO8601 结束时间
            interval: OKX bar 参数，如 1m/5m/15m/1H/4H/1D

        Returns:
            list of dict {ts, open, high, low, close, volume}，升序
        """
        cache_key = (symbol, interval, start_time, end_time)
        if cache_key in self._kline_cache:
            return self._kline_cache[cache_key]

        start_ms = self._to_ms(start_time)
        end_ms = self._to_ms(end_time)
        client = self._get_http_client()

        all_klines: dict[int, dict] = {}
        # OKX candles: before = 请求此时间戳之前（更旧）的数据；after = 请求此时间戳之后（更新）的数据
        # 翻页策略：从 end_ms 向前翻页，直到数据早于 start_ms
        before = str(end_ms)
        max_pages = 200  # 安全上限

        for _ in range(max_pages):
            url = (
                f"{OKX_BASE_URL}/api/v5/market/history-candles"
                f"?instId={symbol}&bar={interval}&before={before}&limit=300"
            )
            try:
                resp = client.get(url)
                data = resp.json()
            except Exception as e:
                # 历史K线接口在某些币种不可用时回退到 candles
                break

            if data.get("code") != "0":
                # 尝试回退到 /api/v5/market/candles（仅返回最近 1440 根）
                url2 = (
                    f"{OKX_BASE_URL}/api/v5/market/candles"
                    f"?instId={symbol}&bar={interval}&before={before}&limit=300"
                )
                try:
                    resp2 = client.get(url2)
                    data = resp2.json()
                except Exception:
                    break
                if data.get("code") != "0":
                    break

            rows = data.get("data", [])
            if not rows:
                break

            oldest_ts_in_page = None
            for row in rows:
                k = self._parse_kline(row)
                if k is None:
                    continue
                if k["ts"] < start_ms or k["ts"] > end_ms:
                    continue
                all_klines[k["ts"]] = k
                if oldest_ts_in_page is None or k["ts"] < oldest_ts_in_page:
                    oldest_ts_in_page = k["ts"]

            # 如果本页最早的时间已经早于 start_ms，停止翻页
            if oldest_ts_in_page is None or oldest_ts_in_page <= start_ms:
                break

            # 下一页的 before = 本页最早的 ts
            new_before = str(oldest_ts_in_page)
            # 避免无限循环（before 没有变化时停止）
            if new_before == before:
                break
            before = new_before

        result = [all_klines[ts] for ts in sorted(all_klines.keys())]
        self._kline_cache[cache_key] = result
        return result

    def set_klines_for_test(self, symbol: str, interval: str, klines: list[dict]):
        """注入 K 线用于单元测试。"""
        cache_key = (symbol, interval, "test_start", "test_end")
        self._kline_cache[cache_key] = klines
        # 同时注册一个万能键，让 fetch_historical_klines 返回注入数据
        # 测试时直接构造 BacktestConfig 并调用 run_backtest 时使用
        self._test_klines = klines

    # -------- 策略执行 --------

    def run_backtest(self, config: BacktestConfig) -> BacktestResult:
        """执行回测，返回 BacktestResult。

        Args:
            config: BacktestConfig

        Returns:
            BacktestResult
        """
        # 序列化配置用于结果
        config_dict = asdict(config)

        # 获取 K 线（优先使用测试注入数据）
        klines = getattr(self, "_test_klines", None)
        if klines is None:
            try:
                klines = self.fetch_historical_klines(
                    config.symbol, config.start_time, config.end_time, config.interval
                )
            except Exception as e:
                return BacktestResult(
                    config=config_dict,
                    trades=[],
                    equity_curve=[],
                    metrics={},
                    kline_count=0,
                    error=f"拉取 K 线失败: {e}",
                )

        if not klines:
            return BacktestResult(
                config=config_dict,
                trades=[],
                equity_curve=[],
                metrics={},
                kline_count=0,
                error="未获取到 K 线数据",
            )

        matcher = MatchingEngine(slippage=config.slippage, fee_rate=config.fee_rate)

        try:
            if config.strategy_type == "grid":
                trades, equity_curve = self._run_grid(config, klines, matcher)
            elif config.strategy_type == "trend":
                trades, equity_curve = self._run_trend(config, klines, matcher)
            elif config.strategy_type == "arbitrage":
                # 占位：套利策略暂复用 trend 的 MA 交叉撮合
                trades, equity_curve = self._run_trend(config, klines, matcher)
            else:
                return BacktestResult(
                    config=config_dict,
                    trades=[],
                    equity_curve=[],
                    metrics={},
                    kline_count=len(klines),
                    error=f"未知策略类型: {config.strategy_type}",
                )
        except Exception as e:
            return BacktestResult(
                config=config_dict,
                trades=[],
                equity_curve=[],
                metrics={},
                kline_count=len(klines),
                error=f"回测执行异常: {e}",
            )

        metrics = compute_metrics(equity_curve, trades, config.initial_capital)

        return BacktestResult(
            config=config_dict,
            trades=[asdict(t) for t in trades],
            equity_curve=[asdict(e) for e in equity_curve],
            metrics=metrics,
            kline_count=len(klines),
        )

    # -------- 网格策略 --------

    def _run_grid(
        self,
        config: BacktestConfig,
        klines: list[dict],
        matcher: MatchingEngine,
    ) -> tuple[list[Trade], list[EquityPoint]]:
        """网格策略回测。

        参数（config.params）：
        - upper_price: 网格上界
        - lower_price: 网格下界
        - grid_count: 网格数量（>=2）
        - order_qty: 每格下单数量

        逻辑：
        - 在 [lower, upper] 区间内均匀画 grid_count 个网格价位
        - 初始：所有低于首根 K 线收盘价的网格挂买单，高于的挂卖单
        - 每根 K 线：用 high/low 撮合已挂限价单
          - 买单成交后，在该网格上一格挂卖单
          - 卖单成交后，在该网格下一格挂买单
        - 资金以 USDT 计，持仓以币计
        """
        params = config.params
        upper = float(params.get("upper_price", 0))
        lower = float(params.get("lower_price", 0))
        grid_count = int(params.get("grid_count", 10))
        order_qty = float(params.get("order_qty", 0))

        if grid_count < 2 or upper <= lower or order_qty <= 0:
            return [], []

        step = (upper - lower) / (grid_count - 1)
        grid_levels = [lower + i * step for i in range(grid_count)]

        cash = config.initial_capital
        position = 0.0  # 币数量
        avg_buy_price = 0.0

        trades: list[Trade] = []
        equity_curve: list[EquityPoint] = []

        # 挂单簿：grid_idx -> {"side": "buy"|"sell", "price": float, "qty": float}
        pending_orders: dict[int, dict] = {}

        def place_initial_orders(current_price: float):
            for i, level in enumerate(grid_levels):
                if level < current_price:
                    pending_orders[i] = {"side": "buy", "price": level, "qty": order_qty}
                elif level > current_price:
                    pending_orders[i] = {"side": "sell", "price": level, "qty": order_qty}

        def equity_at(price: float) -> float:
            return cash + position * price

        first_price = klines[0]["close"]
        place_initial_orders(first_price)

        # 初始权益点
        ts0_iso = datetime.fromtimestamp(klines[0]["ts"] / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        equity_curve.append(EquityPoint(
            timestamp=ts0_iso,
            equity=equity_at(first_price),
            cash=cash,
            position_value=position * first_price,
        ))

        for k in klines:
            high = k["high"]
            low = k["low"]
            close = k["close"]
            ts_iso = datetime.fromtimestamp(k["ts"] / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")

            # 复制挂单索引避免遍历过程中修改
            filled_indices: list[int] = []
            for idx, order in list(pending_orders.items()):
                if order["side"] == "buy":
                    ok, fill_price, _ = matcher.match_limit_buy(order["price"], low)
                    if ok:
                        # 资金检查
                        cost = fill_price * order["qty"]
                        fee = matcher.calc_fee(fill_price, order["qty"])
                        if cash >= cost + fee:
                            cash -= cost + fee
                            # 更新持仓均价
                            new_total = position + order["qty"]
                            if new_total > 0:
                                avg_buy_price = (avg_buy_price * position + fill_price * order["qty"]) / new_total
                            position = new_total
                            trades.append(Trade(
                                timestamp=ts_iso, side="buy", order_type="limit",
                                price=fill_price, quantity=order["qty"], fee=fee, pnl=0.0,
                            ))
                            filled_indices.append(idx)
                elif order["side"] == "sell":
                    ok, fill_price, _ = matcher.match_limit_sell(order["price"], high)
                    if ok:
                        sell_qty = min(order["qty"], position)
                        if sell_qty > 0:
                            proceeds = fill_price * sell_qty
                            fee = matcher.calc_fee(fill_price, sell_qty)
                            cash += proceeds - fee
                            # 已实现盈亏 = (卖价 - 均价) * 数量 - 手续费
                            realized_pnl = (fill_price - avg_buy_price) * sell_qty - fee
                            position -= sell_qty
                            if position <= 1e-12:
                                position = 0.0
                                avg_buy_price = 0.0
                            trades.append(Trade(
                                timestamp=ts_iso, side="sell", order_type="limit",
                                price=fill_price, quantity=sell_qty, fee=fee, pnl=realized_pnl,
                            ))
                            filled_indices.append(idx)
                        else:
                            # 无持仓可卖，撤掉该卖单
                            filled_indices.append(idx)

            # 移除已成交/已撤销的订单
            for idx in filled_indices:
                if idx in pending_orders:
                    del pending_orders[idx]

            # 为已成交的网格补充反向订单
            for idx in filled_indices:
                if idx + 1 < grid_count and (idx + 1) not in pending_orders:
                    pending_orders[idx + 1] = {"side": "sell", "price": grid_levels[idx + 1], "qty": order_qty}
                if idx - 1 >= 0 and (idx - 1) not in pending_orders:
                    pending_orders[idx - 1] = {"side": "buy", "price": grid_levels[idx - 1], "qty": order_qty}

            # 记录权益
            equity_curve.append(EquityPoint(
                timestamp=ts_iso,
                equity=equity_at(close),
                cash=cash,
                position_value=position * close,
            ))

        # 最终清算：将剩余持仓按最后一根收盘价估值（不计入交易）
        return trades, equity_curve

    # -------- 趋势策略 --------

    def _run_trend(
        self,
        config: BacktestConfig,
        klines: list[dict],
        matcher: MatchingEngine,
    ) -> tuple[list[Trade], list[EquityPoint]]:
        """趋势策略回测（MA 交叉）。

        参数（config.params）：
        - fast_period: 快均线周期
        - slow_period: 慢均线周期
        - order_qty: 每次下单数量

        逻辑：
        - 按收盘价计算 SMA(fast) / SMA(slow)
        - 金叉（fast 上穿 slow）→ 市价买入
        - 死叉（fast 下穿 slow）→ 市价卖出（平仓）
        - 市价单按收盘价 ± 滑点成交
        """
        params = config.params
        fast_period = int(params.get("fast_period", params.get("fast_ma_period", 5)))
        slow_period = int(params.get("slow_period", params.get("slow_ma_period", 20)))
        order_qty = float(params.get("order_qty", 0))

        if fast_period >= slow_period or fast_period < 1 or order_qty <= 0:
            return [], []

        closes = [k["close"] for k in klines]

        cash = config.initial_capital
        position = 0.0
        avg_buy_price = 0.0
        last_signal: str | None = None

        trades: list[Trade] = []
        equity_curve: list[EquityPoint] = []

        def sma(idx: int, period: int) -> float | None:
            if idx + 1 < period:
                return None
            window = closes[idx + 1 - period: idx + 1]
            return sum(window) / period

        def equity_at(price: float) -> float:
            return cash + position * price

        # 初始权益点
        ts0_iso = datetime.fromtimestamp(klines[0]["ts"] / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        equity_curve.append(EquityPoint(
            timestamp=ts0_iso,
            equity=equity_at(closes[0]),
            cash=cash,
            position_value=0.0,
        ))

        for i, k in enumerate(klines):
            close = k["close"]
            ts_iso = datetime.fromtimestamp(k["ts"] / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")

            if i + 1 < slow_period:
                equity_curve.append(EquityPoint(
                    timestamp=ts_iso,
                    equity=equity_at(close),
                    cash=cash,
                    position_value=position * close,
                ))
                continue

            fast_ma = sma(i, fast_period)
            slow_ma = sma(i, slow_period)
            prev_fast = sma(i - 1, fast_period)
            prev_slow = sma(i - 1, slow_period)

            if None in (fast_ma, slow_ma, prev_fast, prev_slow):
                equity_curve.append(EquityPoint(
                    timestamp=ts_iso,
                    equity=equity_at(close),
                    cash=cash,
                    position_value=position * close,
                ))
                continue

            signal = None
            if prev_fast <= prev_slow and fast_ma > slow_ma:
                signal = "buy"
            elif prev_fast >= prev_slow and fast_ma < slow_ma:
                signal = "sell"

            if signal and signal != last_signal:
                if signal == "buy":
                    fill_price = matcher.match_market_buy(close)
                    cost = fill_price * order_qty
                    fee = matcher.calc_fee(fill_price, order_qty)
                    if cash >= cost + fee:
                        cash -= cost + fee
                        new_total = position + order_qty
                        if new_total > 0:
                            avg_buy_price = (avg_buy_price * position + fill_price * order_qty) / new_total
                        position = new_total
                        trades.append(Trade(
                            timestamp=ts_iso, side="buy", order_type="market",
                            price=fill_price, quantity=order_qty, fee=fee, pnl=0.0,
                        ))
                        last_signal = signal
                elif signal == "sell":
                    if position > 0:
                        sell_qty = min(order_qty, position)
                        fill_price = matcher.match_market_sell(close)
                        proceeds = fill_price * sell_qty
                        fee = matcher.calc_fee(fill_price, sell_qty)
                        cash += proceeds - fee
                        realized_pnl = (fill_price - avg_buy_price) * sell_qty - fee
                        position -= sell_qty
                        if position <= 1e-12:
                            position = 0.0
                            avg_buy_price = 0.0
                        trades.append(Trade(
                            timestamp=ts_iso, side="sell", order_type="market",
                            price=fill_price, quantity=sell_qty, fee=fee, pnl=realized_pnl,
                        ))
                        last_signal = signal

            equity_curve.append(EquityPoint(
                timestamp=ts_iso,
                equity=equity_at(close),
                cash=cash,
                position_value=position * close,
            ))

        return trades, equity_curve


# ============================================================
# 单例
# ============================================================

backtest_engine = BacktestEngine()
