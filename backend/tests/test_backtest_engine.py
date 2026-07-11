"""回测引擎单元测试。

测试覆盖：
- 撮合引擎（限价单/市价单成交逻辑）
- 指标计算（用已知数据验证夏普比率/最大回撤）
- 网格策略回测（mock K 线数据）
- 趋势策略回测（mock K 线数据）

参考 test_dsl_indicators.py 的 sys.path.insert + pytest 风格。
"""
import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    EquityPoint,
    MatchingEngine,
    Trade,
    compute_metrics,
)


# ============================================================
# 辅助函数
# ============================================================

def make_kline(ts_ms: int, o: float, h: float, l: float, c: float) -> dict:
    """构造 K 线 dict。"""
    return {"ts": ts_ms, "open": o, "high": h, "low": l, "close": c, "volume": 0.0}


def make_klines(prices: list[float], start_ts_ms: int = 1700000000000, step_ms: int = 60_000) -> list[dict]:
    """根据 close 序列构造 K 线列表，high/low 在 close ± 1% 范围内。"""
    result = []
    for i, c in enumerate(prices):
        ts = start_ts_ms + i * step_ms
        result.append(make_kline(ts, c, c * 1.005, c * 0.995, c))
    return result


# ============================================================
# 撮合引擎测试
# ============================================================

class TestMatchingEngine:
    def test_limit_buy_fills_when_price_above_low(self):
        """限价买单：order_price >= low 则成交，成交价 = max(order_price, low)。"""
        m = MatchingEngine(slippage=0.001, fee_rate=0.001)
        # order_price=100, low=95 -> 成交，fill=max(100,95)=100
        ok, fill, _ = m.match_limit_buy(100.0, 95.0)
        assert ok is True
        assert fill == 100.0

    def test_limit_buy_no_fill_when_price_below_low(self):
        """限价买单：order_price < low 不成交。"""
        m = MatchingEngine(slippage=0.001, fee_rate=0.001)
        ok, fill, _ = m.match_limit_buy(90.0, 95.0)
        assert ok is False
        assert fill == 0.0

    def test_limit_buy_fill_price_uses_low_when_low_higher(self):
        """限价买单：当 low > order_price 时（理论上不会发生，因 order_price >= low 才成交），
        但若 order_price == low 边界情况，fill = low。"""
        m = MatchingEngine(slippage=0.001, fee_rate=0.001)
        ok, fill, _ = m.match_limit_buy(95.0, 95.0)
        assert ok is True
        assert fill == 95.0

    def test_limit_sell_fills_when_price_below_high(self):
        """限价卖单：order_price <= high 则成交，成交价 = min(order_price, high)。"""
        m = MatchingEngine(slippage=0.001, fee_rate=0.001)
        ok, fill, _ = m.match_limit_sell(100.0, 105.0)
        assert ok is True
        assert fill == 100.0

    def test_limit_sell_no_fill_when_price_above_high(self):
        """限价卖单：order_price > high 不成交。"""
        m = MatchingEngine(slippage=0.001, fee_rate=0.001)
        ok, fill, _ = m.match_limit_sell(110.0, 105.0)
        assert ok is False
        assert fill == 0.0

    def test_market_buy_applies_positive_slippage(self):
        """市价买单：close * (1 + slippage)。"""
        m = MatchingEngine(slippage=0.001, fee_rate=0.001)
        fill = m.match_market_buy(100.0)
        assert fill == pytest.approx(100.1, abs=1e-9)

    def test_market_sell_applies_negative_slippage(self):
        """市价卖单：close * (1 - slippage)。"""
        m = MatchingEngine(slippage=0.001, fee_rate=0.001)
        fill = m.match_market_sell(100.0)
        assert fill == pytest.approx(99.9, abs=1e-9)

    def test_calc_fee(self):
        """手续费 = fee_rate * price * qty。"""
        m = MatchingEngine(slippage=0.001, fee_rate=0.002)
        fee = m.calc_fee(100.0, 2.0)
        assert fee == pytest.approx(0.4, abs=1e-9)  # 0.002 * 100 * 2


# ============================================================
# 指标计算测试
# ============================================================

class TestComputeMetrics:
    def test_empty_equity_curve_returns_defaults(self):
        """空权益曲线返回默认值。"""
        metrics = compute_metrics([], [], 10000.0)
        assert metrics["total_return"] == 0.0
        assert metrics["max_drawdown"] == 0.0
        assert metrics["sharpe_ratio"] == 0.0
        assert metrics["win_rate"] == 0.0
        assert metrics["trade_count"] == 0
        assert metrics["final_equity"] == 10000.0

    def test_total_return_positive(self):
        """总收益率：从 10000 涨到 12000，应得 0.2。"""
        curve = [
            EquityPoint(timestamp="t0", equity=10000.0, cash=10000.0, position_value=0.0),
            EquityPoint(timestamp="t1", equity=12000.0, cash=12000.0, position_value=0.0),
        ]
        metrics = compute_metrics(curve, [], 10000.0)
        assert metrics["total_return"] == pytest.approx(0.2, abs=1e-6)
        assert metrics["final_equity"] == pytest.approx(12000.0, abs=1e-6)

    def test_total_return_negative(self):
        """总收益率：从 10000 跌到 8000，应得 -0.2。"""
        curve = [
            EquityPoint(timestamp="t0", equity=10000.0, cash=10000.0, position_value=0.0),
            EquityPoint(timestamp="t1", equity=8000.0, cash=8000.0, position_value=0.0),
        ]
        metrics = compute_metrics(curve, [], 10000.0)
        assert metrics["total_return"] == pytest.approx(-0.2, abs=1e-6)

    def test_max_drawdown(self):
        """最大回撤：10000 -> 12000 -> 9000 -> 11000，peak=12000, trough=9000, dd=0.25。"""
        curve = [
            EquityPoint(timestamp="t0", equity=10000.0, cash=0.0, position_value=0.0),
            EquityPoint(timestamp="t1", equity=12000.0, cash=0.0, position_value=0.0),
            EquityPoint(timestamp="t2", equity=9000.0, cash=0.0, position_value=0.0),
            EquityPoint(timestamp="t3", equity=11000.0, cash=0.0, position_value=0.0),
        ]
        metrics = compute_metrics(curve, [], 10000.0)
        assert metrics["max_drawdown"] == pytest.approx(0.25, abs=1e-6)

    def test_max_drawdown_zero_when_monotonic_up(self):
        """单调上涨时最大回撤为 0。"""
        curve = [
            EquityPoint(timestamp="t0", equity=100.0, cash=0.0, position_value=0.0),
            EquityPoint(timestamp="t1", equity=110.0, cash=0.0, position_value=0.0),
            EquityPoint(timestamp="t2", equity=120.0, cash=0.0, position_value=0.0),
        ]
        metrics = compute_metrics(curve, [], 100.0)
        assert metrics["max_drawdown"] == 0.0

    def test_sharpe_ratio_zero_when_no_variance(self):
        """收益率序列无方差时夏普比率为 0。"""
        # 所有权益相等 -> 所有 daily_returns = 0 -> std = 0 -> sharpe = 0
        curve = [
            EquityPoint(timestamp="t0", equity=100.0, cash=0.0, position_value=0.0),
            EquityPoint(timestamp="t1", equity=100.0, cash=0.0, position_value=0.0),
            EquityPoint(timestamp="t2", equity=100.0, cash=0.0, position_value=0.0),
        ]
        metrics = compute_metrics(curve, [], 100.0)
        assert metrics["sharpe_ratio"] == 0.0

    def test_sharpe_ratio_nonzero_with_variance(self):
        """收益率序列有方差时夏普比率非零（且为有限数）。"""
        # 交替涨跌，制造方差（百分比收益因几何不对称，均值非零）
        curve = [
            EquityPoint(timestamp=f"t{i}", equity=e, cash=0.0, position_value=0.0)
            for i, e in enumerate([100.0, 110.0, 100.0, 110.0, 100.0])
        ]
        metrics = compute_metrics(curve, [], 100.0)
        # 有方差时 sharpe 应为有限数（非 NaN/None）
        assert metrics["sharpe_ratio"] is not None
        assert math.isfinite(metrics["sharpe_ratio"])
        # 由于涨跌幅几何不对称（+10% vs -9.09%），均值为正，sharpe 应为正
        assert metrics["sharpe_ratio"] > 0

    def test_sharpe_ratio_positive_trend(self):
        """单调上涨序列，夏普比率应为正。"""
        curve = [
            EquityPoint(timestamp=f"t{i}", equity=e, cash=0.0, position_value=0.0)
            for i, e in enumerate([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        ]
        metrics = compute_metrics(curve, [], 100.0)
        assert metrics["sharpe_ratio"] > 0

    def test_win_rate_and_profit_factor(self):
        """胜率与盈亏比：3 笔盈利 + 1 笔亏损。"""
        trades = [
            Trade(timestamp="t1", side="sell", order_type="limit", price=10, quantity=1, fee=0, pnl=10.0),
            Trade(timestamp="t2", side="sell", order_type="limit", price=10, quantity=1, fee=0, pnl=5.0),
            Trade(timestamp="t3", side="sell", order_type="limit", price=10, quantity=1, fee=0, pnl=-3.0),
            Trade(timestamp="t4", side="sell", order_type="limit", price=10, quantity=1, fee=0, pnl=8.0),
        ]
        curve = [EquityPoint(timestamp="t0", equity=100.0, cash=0.0, position_value=0.0)]
        metrics = compute_metrics(curve, trades, 100.0)
        assert metrics["trade_count"] == 4
        assert metrics["win_rate"] == pytest.approx(0.75, abs=1e-6)  # 3/4
        # gross_profit=23, gross_loss=3, pf=23/3
        assert metrics["profit_factor"] == pytest.approx(23.0 / 3.0, abs=1e-6)

    def test_profit_factor_inf_when_no_losses(self):
        """只有盈利无亏损时盈亏比为 inf。"""
        trades = [
            Trade(timestamp="t1", side="sell", order_type="limit", price=10, quantity=1, fee=0, pnl=10.0),
        ]
        curve = [EquityPoint(timestamp="t0", equity=100.0, cash=0.0, position_value=0.0)]
        metrics = compute_metrics(curve, trades, 100.0)
        assert metrics["profit_factor"] == float("inf")
        assert metrics["win_rate"] == 1.0


# ============================================================
# 网格策略回测测试
# ============================================================

class TestGridBacktest:
    def test_grid_runs_and_produces_result(self):
        """网格策略能跑通并产生结果（使用 mock K 线）。"""
        engine = BacktestEngine()
        # 价格在 95-105 之间震荡
        prices = [100.0, 98.0, 102.0, 96.0, 104.0, 99.0, 101.0, 97.0, 103.0, 100.0]
        klines = make_klines(prices)
        engine._test_klines = klines

        config = BacktestConfig(
            symbol="BTC-USDT",
            strategy_type="grid",
            params={"upper_price": 105.0, "lower_price": 95.0, "grid_count": 5, "order_qty": 0.1},
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-02T00:00:00Z",
            interval="1m",
            initial_capital=10000.0,
            slippage=0.001,
            fee_rate=0.001,
        )
        result = engine.run_backtest(config)

        assert result.error is None
        assert result.kline_count == 10
        # 至少应该有初始权益点 + 10 根 K 线 = 11 个权益点
        assert len(result.equity_curve) >= 11
        # 权益点必须包含 timestamp/equity 字段
        assert "timestamp" in result.equity_curve[0]
        assert "equity" in result.equity_curve[0]
        # 指标必须包含所有字段
        for key in ("total_return", "max_drawdown", "sharpe_ratio", "win_rate", "trade_count", "profit_factor"):
            assert key in result.metrics

    def test_grid_invalid_params_returns_empty(self):
        """网格参数非法（upper <= lower）时返回空结果（无错误）。"""
        engine = BacktestEngine()
        engine._test_klines = make_klines([100.0, 101.0])

        config = BacktestConfig(
            symbol="BTC-USDT",
            strategy_type="grid",
            params={"upper_price": 90.0, "lower_price": 100.0, "grid_count": 5, "order_qty": 0.1},
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-02T00:00:00Z",
            interval="1m",
        )
        result = engine.run_backtest(config)
        assert result.error is None
        assert len(result.trades) == 0
        # 空结果时 metrics 仍应返回默认值
        assert result.metrics["trade_count"] == 0

    def test_grid_buy_orders_fill_when_low_crosses(self):
        """当 K 线最低价触及买单价位时，买单应成交。"""
        engine = BacktestEngine()
        # 首根 close=100，网格下界 90，应挂买单
        # 第二根 low=88 < 90，应触发买单成交
        klines = [
            make_kline(1700000000000, 100, 101, 99, 100),
            make_kline(1700000060000, 95, 96, 88, 92),
        ]
        engine._test_klines = klines

        config = BacktestConfig(
            symbol="BTC-USDT",
            strategy_type="grid",
            params={"upper_price": 110.0, "lower_price": 90.0, "grid_count": 3, "order_qty": 1.0},
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-02T00:00:00Z",
            interval="1m",
            initial_capital=100000.0,
        )
        result = engine.run_backtest(config)
        assert result.error is None
        # 应至少有一笔买单成交
        buy_trades = [t for t in result.trades if t["side"] == "buy"]
        assert len(buy_trades) >= 1


# ============================================================
# 趋势策略回测测试
# ============================================================

class TestTrendBacktest:
    def test_trend_runs_and_produces_result(self):
        """趋势策略能跑通并产生结果（使用 mock K 线）。"""
        engine = BacktestEngine()
        # 30 根 K 线，前 20 根稳定，后 10 根上涨（触发金叉）
        prices = [100.0] * 20 + [101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0]
        klines = make_klines(prices)
        engine._test_klines = klines

        config = BacktestConfig(
            symbol="BTC-USDT",
            strategy_type="trend",
            params={"fast_period": 5, "slow_period": 20, "order_qty": 1.0},
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-02T00:00:00Z",
            interval="1m",
            initial_capital=10000.0,
        )
        result = engine.run_backtest(config)

        assert result.error is None
        assert result.kline_count == 30
        # 在上涨阶段应触发买入信号
        buy_trades = [t for t in result.trades if t["side"] == "buy"]
        assert len(buy_trades) >= 1
        # 所有买单应为市价单
        for t in buy_trades:
            assert t["order_type"] == "market"

    def test_trend_no_signal_when_flat(self):
        """价格平稳时无交易信号。"""
        engine = BacktestEngine()
        prices = [100.0] * 30
        klines = make_klines(prices)
        engine._test_klines = klines

        config = BacktestConfig(
            symbol="BTC-USDT",
            strategy_type="trend",
            params={"fast_period": 5, "slow_period": 20, "order_qty": 1.0},
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-02T00:00:00Z",
            interval="1m",
        )
        result = engine.run_backtest(config)
        assert result.error is None
        assert len(result.trades) == 0
        # 平稳时权益不变，收益率为 0
        assert result.metrics["total_return"] == 0.0

    def test_trend_invalid_period_returns_empty(self):
        """fast_period >= slow_period 时返回空。"""
        engine = BacktestEngine()
        engine._test_klines = make_klines([100.0, 101.0, 102.0])

        config = BacktestConfig(
            symbol="BTC-USDT",
            strategy_type="trend",
            params={"fast_period": 20, "slow_period": 5, "order_qty": 1.0},
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-02T00:00:00Z",
            interval="1m",
        )
        result = engine.run_backtest(config)
        assert result.error is None
        assert len(result.trades) == 0

    def test_trend_golden_cross_then_death_cross(self):
        """先涨后跌，应触发金叉买入 + 死叉卖出。"""
        engine = BacktestEngine()
        # 30 根平稳 + 10 根上涨（金叉）+ 10 根下跌（死叉）
        prices = [100.0] * 30 + [102.0, 104.0, 106.0, 108.0, 110.0] * 2 + [108.0, 106.0, 104.0, 102.0, 100.0] * 2
        klines = make_klines(prices)
        engine._test_klines = klines

        config = BacktestConfig(
            symbol="BTC-USDT",
            strategy_type="trend",
            params={"fast_period": 5, "slow_period": 20, "order_qty": 1.0},
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-02T00:00:00Z",
            interval="1m",
            initial_capital=100000.0,
        )
        result = engine.run_backtest(config)
        assert result.error is None
        # 至少应有一笔买入和一笔卖出
        buy_trades = [t for t in result.trades if t["side"] == "buy"]
        sell_trades = [t for t in result.trades if t["side"] == "sell"]
        assert len(buy_trades) >= 1
        assert len(sell_trades) >= 1
        # 卖单应有 pnl（平仓时计算）
        for s in sell_trades:
            assert "pnl" in s


# ============================================================
# 错误处理测试
# ============================================================

class TestErrorHandling:
    def test_unknown_strategy_type_returns_error(self):
        """未知策略类型应返回错误。"""
        engine = BacktestEngine()
        engine._test_klines = make_klines([100.0, 101.0])

        config = BacktestConfig(
            symbol="BTC-USDT",
            strategy_type="unknown_type",
            params={},
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-02T00:00:00Z",
            interval="1m",
        )
        result = engine.run_backtest(config)
        assert result.error is not None
        assert "未知策略类型" in result.error

    def test_empty_klines_returns_error(self):
        """无 K 线时应返回错误。"""
        engine = BacktestEngine()
        # 不注入 _test_klines，且让 fetch 返回空（mock）
        engine._kline_cache = {}

        config = BacktestConfig(
            symbol="BTC-USDT",
            strategy_type="grid",
            params={"upper_price": 110.0, "lower_price": 90.0, "grid_count": 5, "order_qty": 1.0},
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-02T00:00:00Z",
            interval="1m",
        )
        # 通过 mock fetch_historical_klines 返回空
        engine.fetch_historical_klines = lambda *a, **kw: []
        result = engine.run_backtest(config)
        assert result.error is not None
        assert "未获取到 K 线数据" in result.error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
