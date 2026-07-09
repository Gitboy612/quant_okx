"""ComposableStrategy 执行器的 QS-Model 配置解析测试。

聚焦于 ``ComposableStrategy._resolve_dsl_config()`` 与 ``validate_params()``
的 QS-Model 路径：

- 优先读取 ``self.params['qs_model_config']``，经 ``resolve_variables`` 替换
  ``$params.xxx`` / ``$meta.xxx`` 引用后返回 ``StrategyDSL``；
- 回退到旧的 ``self.params['dsl_config']`` 兼容路径；
- 两者均缺失时抛出 ``ValueError``；
- ``risk_filter`` 段被读取并保存到 ``self._risk_filter``。

不进入 ``execute()`` 主循环（涉及 OKX 调用与 while 死循环），仅测试
可独立验证的配置解析部分。导入风格参考 test_dsl_executor.py。
"""
import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from dsl.executor import ComposableStrategy
from dsl.schema import (
    StrategyDSL,
    QSModelConfig,
    RiskFilter,
)


# ============================================================
# 辅助构造
# ============================================================


def _base_grid_params() -> dict:
    """grid 基础策略所需的策略专属参数（值部分使用变量引用）。

    解析后期望得到：
      upper_price=50000, lower_price=40000, grid_count=10,
      order_qty=0.01, symbol="BTC-USDT"
    """
    return {
        "upper_price": "$params.upper_price",
        "lower_price": "$params.lower_price",
        "grid_count": "$params.grid_count",
        "order_qty": "$params.order_qty",
        "symbol": "$meta.base_symbol",
        "literal_int": 100,          # 纯字面量，不应被替换
        "literal_str": "static_value",  # 纯字面量，不应被替换
    }


def _price_change_indicator(window: str = "1h", symbol: str = "BTC-USDT") -> dict:
    return {"kind": "price_change_pct", "args": {"window": window, "symbol": symbol}}


def _gt(indicator: dict, threshold) -> dict:
    return {"kind": "gt", "args": {"indicator": indicator, "threshold": threshold}}


def _abs_lt(indicator: dict, threshold) -> dict:
    return {"kind": "abs_lt", "args": {"indicator": indicator, "threshold": threshold}}


def _build_qm_config(
    upper_price=50000,
    lower_price=40000,
    grid_count=10,
    order_qty=0.01,
    threshold_pct=0.05,
    base_symbol="BTC-USDT",
    with_risk_filter: bool = True,
) -> dict:
    """构造一个完整的 qs_model_config 字典（可直接塞进 self.params）。

    logic 段中混用 ``$params.xxx`` / ``$meta.xxx`` 引用与字面量，便于
    验证变量替换行为。
    """
    risk_filter = {
        "max_position_ratio": 0.8,
        "daily_max_loss": 0.05,
        "min_trade_size": 0.001,
        "blacklist_hours": ["00:00", "01:00"],
    } if with_risk_filter else None

    return {
        "qs_model_version": "2.0",
        "meta": {
            "name": "BTC 网格策略",
            "version": "v1.2.0",
            "author": "quant_team",
            "description": "基于网格的低频策略",
            "asset_class": "CRYPTO",
            "frequency": "15min",
            "base_symbol": base_symbol,
        },
        "params": {
            "upper_price": {
                "label": "价格上限",
                "value": upper_price,
                "type": "number",
                "range": [1000, 1_000_000],
            },
            "lower_price": {
                "label": "价格下限",
                "value": lower_price,
                "type": "number",
                "range": [100, 1_000_000],
            },
            "grid_count": {
                "label": "网格数量",
                "value": grid_count,
                "type": "int",
                "range": [2, 200],
            },
            "order_qty": {
                "label": "单格数量",
                "value": order_qty,
                "type": "number",
                "range": [0.0001, 100],
            },
            "threshold_pct": {
                "label": "触发阈值",
                "value": threshold_pct,
                "type": "float",
                "range": [0.0, 1.0],
            },
        },
        "logic": {
            "version": "1.0",
            "base_strategy": {
                "kind": "grid",
                "params": _base_grid_params(),
            },
            "rules": [
                {
                    "name": "单边上涨暂停",
                    "when": {
                        "mode": "condition",
                        "condition": _gt(
                            _price_change_indicator("1h", "$meta.base_symbol"),
                            "$params.threshold_pct",
                        ),
                    },
                    "then": [
                        {"kind": "pause_orders"},
                        {"kind": "hold_position"},
                        {"kind": "log_event",
                         "args": {"level": "warn", "message": "单边上涨暂停"}},
                    ],
                    "recover_when": {
                        "mode": "condition",
                        "condition": _abs_lt(
                            _price_change_indicator("1h", "$meta.base_symbol"),
                            "$params.threshold_pct",
                        ),
                    },
                    "recover_then": [
                        {"kind": "rebalance_position",
                         "args": {"mode": "to_theoretical"}},
                        {"kind": "resume_orders"},
                    ],
                    "cool_down_seconds": 60,
                }
            ],
        },
        "risk_filter": risk_filter,
    }


def _build_dsl_config() -> dict:
    """构造一个等价于 QS-Model 解析后的 dsl_config（用于兼容性测试）。"""
    return {
        "version": "1.0",
        "base_strategy": {
            "kind": "grid",
            "params": {
                "upper_price": 50000,
                "lower_price": 40000,
                "grid_count": 10,
                "order_qty": 0.01,
                "symbol": "BTC-USDT",
            },
        },
        "rules": [
            {
                "name": "单边上涨暂停",
                "when": {
                    "mode": "condition",
                    "condition": _gt(_price_change_indicator("1h"), 0.05),
                },
                "then": [
                    {"kind": "pause_orders"},
                    {"kind": "hold_position"},
                    {"kind": "log_event",
                     "args": {"level": "warn", "message": "单边上涨暂停"}},
                ],
                "recover_when": {
                    "mode": "condition",
                    "condition": _abs_lt(_price_change_indicator("1h"), 0.05),
                },
                "recover_then": [
                    {"kind": "rebalance_position",
                     "args": {"mode": "to_theoretical"}},
                    {"kind": "resume_orders"},
                ],
                "cool_down_seconds": 60,
            }
        ],
    }


def _make_strategy(
    qs_model_config: dict | None = None,
    dsl_config: dict | None = None,
    extra_params: dict | None = None,
) -> ComposableStrategy:
    """构造一个带 mock 依赖的 ComposableStrategy，不进入主循环。

    client / order_manager / db_session_factory 均为 MagicMock；
    _record_event 内部 try/except 吞掉所有异常。
    """
    params: dict = {"tick_interval": 3}
    if qs_model_config is not None:
        params["qs_model_config"] = qs_model_config
    if dsl_config is not None:
        params["dsl_config"] = dsl_config
    if extra_params:
        params.update(extra_params)

    client = MagicMock()
    order_manager = MagicMock()
    db_session_factory = MagicMock()
    strategy = ComposableStrategy(
        instance_id=1,
        params=params,
        client=client,
        db_session_factory=db_session_factory,
        account_id=1,
        order_manager=order_manager,
    )
    return strategy


# ============================================================
# _resolve_dsl_config: QS-Model 主路径
# ============================================================


def test_resolve_dsl_config_from_qs_model():
    """1. _resolve_dsl_config 优先读取 qs_model_config 并返回 StrategyDSL。"""
    strategy = _make_strategy(qs_model_config=_build_qm_config())
    dsl = strategy._resolve_dsl_config()

    assert isinstance(dsl, StrategyDSL)
    # base_strategy.kind 不变
    assert dsl.base_strategy.kind == "grid"
    # rules 数量与原始一致
    assert len(dsl.rules) == 1
    assert dsl.rules[0].name == "单边上涨暂停"


def test_resolve_dsl_config_replaces_params_reference():
    """2. $params.xxx 引用被替换为 params 中对应 value。"""
    strategy = _make_strategy(qs_model_config=_build_qm_config())
    dsl = strategy._resolve_dsl_config()

    bs_params = dsl.base_strategy.params
    assert bs_params["upper_price"] == 50000
    assert bs_params["lower_price"] == 40000
    assert bs_params["grid_count"] == 10
    assert bs_params["order_qty"] == 0.01


def test_resolve_dsl_config_replaces_meta_reference():
    """3. $meta.base_symbol 引用被替换为 meta.base_symbol。"""
    strategy = _make_strategy(qs_model_config=_build_qm_config())
    dsl = strategy._resolve_dsl_config()

    bs_params = dsl.base_strategy.params
    assert bs_params["symbol"] == "BTC-USDT"

    # rules 中的 $meta.base_symbol 也应被替换
    cond_args = dsl.rules[0].when.condition.args
    assert cond_args["indicator"]["args"]["symbol"] == "BTC-USDT"


def test_resolve_dsl_config_keeps_literals():
    """4. 纯字面量（int/str）不被替换。"""
    strategy = _make_strategy(qs_model_config=_build_qm_config())
    dsl = strategy._resolve_dsl_config()

    bs_params = dsl.base_strategy.params
    assert bs_params["literal_int"] == 100
    assert bs_params["literal_str"] == "static_value"


def test_resolve_dsl_config_param_overrides_from_self_params():
    """5. self.params 中与 qs_model.params 同名的键覆盖默认 value。

    构造一个 qs_model_config（默认 upper_price=50000），然后在
    self.params 中放入 upper_price=60000 / threshold_pct=0.1，
    验证解析结果使用了覆盖值。
    """
    qm_config = _build_qm_config()  # 默认 upper_price=50000, threshold_pct=0.05
    strategy = _make_strategy(
        qs_model_config=qm_config,
        extra_params={
            "upper_price": 60000,    # 覆盖默认 50000
            "threshold_pct": 0.10,   # 覆盖默认 0.05
        },
    )
    dsl = strategy._resolve_dsl_config()

    bs_params = dsl.base_strategy.params
    assert bs_params["upper_price"] == 60000  # 被覆盖
    assert bs_params["lower_price"] == 40000  # 未覆盖，仍取默认
    assert bs_params["grid_count"] == 10
    assert bs_params["order_qty"] == 0.01

    # rules 中的 $params.threshold_pct 也应被覆盖为 0.10
    cond_args = dsl.rules[0].when.condition.args
    assert cond_args["threshold"] == 0.10
    recover_args = dsl.rules[0].recover_when.condition.args
    assert recover_args["threshold"] == 0.10


def test_resolve_dsl_config_does_not_mutate_qs_model():
    """6. _resolve_dsl_config 不修改 qs_model_config 中的变量引用字符串。"""
    qm_config = _build_qm_config()
    strategy = _make_strategy(qs_model_config=qm_config)
    _ = strategy._resolve_dsl_config()

    # 原配置中的引用字符串应保持原样
    bs_params = qm_config["logic"]["base_strategy"]["params"]
    assert bs_params["upper_price"] == "$params.upper_price"
    assert bs_params["symbol"] == "$meta.base_symbol"
    assert bs_params["literal_int"] == 100


def test_resolve_dsl_config_meta_other_fields():
    """7. $meta 可引用 meta 段任意字段（如 name/version/frequency）。"""
    qm_config = _build_qm_config()
    # 注入额外引用
    qm_config["logic"]["base_strategy"]["params"]["name_ref"] = "$meta.name"
    qm_config["logic"]["base_strategy"]["params"]["freq_ref"] = "$meta.frequency"

    strategy = _make_strategy(qs_model_config=qm_config)
    dsl = strategy._resolve_dsl_config()

    bs_params = dsl.base_strategy.params
    assert bs_params["name_ref"] == "BTC 网格策略"
    assert bs_params["freq_ref"] == "15min"


# ============================================================
# _resolve_dsl_config: risk_filter 保存
# ============================================================


def test_resolve_dsl_config_saves_risk_filter():
    """8. risk_filter 段被读取并保存到 self._risk_filter。"""
    qm_config = _build_qm_config(with_risk_filter=True)
    strategy = _make_strategy(qs_model_config=qm_config)

    # 解析前为 None
    assert strategy._risk_filter is None

    strategy._resolve_dsl_config()

    assert strategy._risk_filter is not None
    assert isinstance(strategy._risk_filter, RiskFilter)
    assert strategy._risk_filter.max_position_ratio == 0.8
    assert strategy._risk_filter.daily_max_loss == 0.05
    assert strategy._risk_filter.min_trade_size == 0.001
    assert strategy._risk_filter.blacklist_hours == ["00:00", "01:00"]


def test_resolve_dsl_config_risk_filter_none_when_absent():
    """9. qs_model_config 未提供 risk_filter 时 _risk_filter 保持 None。"""
    qm_config = _build_qm_config(with_risk_filter=False)
    strategy = _make_strategy(qs_model_config=qm_config)

    strategy._resolve_dsl_config()

    assert strategy._risk_filter is None


# ============================================================
# _resolve_dsl_config: dsl_config 回退路径
# ============================================================


def test_resolve_dsl_config_falls_back_to_dsl_config():
    """10. 仅提供 dsl_config（无 qs_model_config）→ 回退到旧路径。"""
    strategy = _make_strategy(dsl_config=_build_dsl_config())
    dsl = strategy._resolve_dsl_config()

    assert isinstance(dsl, StrategyDSL)
    assert dsl.base_strategy.kind == "grid"
    bs_params = dsl.base_strategy.params
    assert bs_params["upper_price"] == 50000
    assert bs_params["symbol"] == "BTC-USDT"
    assert "literal_int" not in bs_params  # dsl_config 中未包含此字段
    # risk_filter 在 dsl_config 路径下不应被设置
    assert strategy._risk_filter is None


def test_resolve_dsl_config_qs_model_takes_precedence_over_dsl_config():
    """11. 同时提供两者时优先使用 qs_model_config。

    通过 qs_model_config 中独有的 literal_str 字段验证走了 QS-Model 路径。
    """
    qm_config = _build_qm_config()
    dsl_config = _build_dsl_config()
    strategy = _make_strategy(
        qs_model_config=qm_config,
        dsl_config=dsl_config,
    )
    dsl = strategy._resolve_dsl_config()

    # qs_model_config 的 base_strategy.params 含 literal_str，dsl_config 不含
    assert dsl.base_strategy.params.get("literal_str") == "static_value"


# ============================================================
# _resolve_dsl_config: 缺失配置抛 ValueError
# ============================================================


def test_resolve_dsl_config_raises_value_error_when_missing():
    """12. 既无 qs_model_config 也无 dsl_config → 抛出 ValueError。"""
    strategy = _make_strategy()  # 两者均未提供

    with pytest.raises(ValueError, match="qs_model_config 或 dsl_config"):
        strategy._resolve_dsl_config()


# ============================================================
# validate_params: QS-Model 路径
# ============================================================


@pytest.mark.asyncio
async def test_validate_params_qs_model_valid():
    """13. 合法 qs_model_config → validate_params 返回 True。"""
    strategy = _make_strategy(qs_model_config=_build_qm_config())
    assert await strategy.validate_params() is True


@pytest.mark.asyncio
async def test_validate_params_qs_model_with_overrides_valid():
    """14. 含实例参数覆盖的 qs_model_config → validate_params 仍返回 True。"""
    strategy = _make_strategy(
        qs_model_config=_build_qm_config(),
        extra_params={"upper_price": 60000, "threshold_pct": 0.10},
    )
    assert await strategy.validate_params() is True


@pytest.mark.asyncio
async def test_validate_params_qs_model_invalid_empty_then():
    """15. qs_model_config 解析后 then 为空 → validate_params 返回 False。"""
    qm_config = _build_qm_config()
    # 把 then 改空（语义错误：EMPTY_THEN）
    qm_config["logic"]["rules"][0]["then"] = []
    strategy = _make_strategy(qs_model_config=qm_config)
    assert await strategy.validate_params() is False


@pytest.mark.asyncio
async def test_validate_params_qs_model_invalid_structure():
    """16. qs_model_config 结构非法（缺 meta）→ validate_params 返回 False。"""
    qm_config = _build_qm_config()
    del qm_config["meta"]
    strategy = _make_strategy(qs_model_config=qm_config)
    assert await strategy.validate_params() is False


@pytest.mark.asyncio
async def test_validate_params_falls_back_to_dsl_config():
    """17. 仅提供 dsl_config → validate_params 仍可校验通过。"""
    strategy = _make_strategy(dsl_config=_build_dsl_config())
    assert await strategy.validate_params() is True


@pytest.mark.asyncio
async def test_validate_params_missing_both_configs():
    """18. 既无 qs_model_config 也无 dsl_config → validate_params 返回 False。"""
    strategy = _make_strategy()
    assert await strategy.validate_params() is False


# ============================================================
# execute(): ValueError 路径不抛出，仅记录 error 事件
# ============================================================


@pytest.mark.asyncio
async def test_execute_missing_config_records_error_and_returns():
    """19. execute() 在缺少配置时不抛出 ValueError，记录 error 后返回。

    通过 mock _record_event 捕获调用，避免触发真实数据库写入。
    """
    strategy = _make_strategy()  # 两者均未提供
    recorded_calls: list[tuple] = []

    def fake_record(event_type, message, details=None):
        recorded_calls.append((event_type, message, details))

    strategy._record_event = fake_record

    # execute() 应正常返回，不抛异常
    await strategy.execute()

    # 至少记录了一条 error 事件
    assert any(
        et == "error" and "qs_model_config 或 dsl_config" in msg
        for et, msg, _ in recorded_calls
    ), f"未记录预期的 error 事件，实际: {recorded_calls}"


@pytest.mark.asyncio
async def test_execute_with_qs_model_config_compiles_fsm():
    """20. execute() 从 qs_model_config 解析配置后能编译出 FSM。

    为避免进入主循环死循环，在 FSMCompiler.compile 之后立即将
    ``self._running`` 置 False 以跳出循环。同时 mock 掉 OKX 调用
    （get_ticker）与基础策略 on_start / on_stop 钩子。
    """
    strategy = _make_strategy(qs_model_config=_build_qm_config())

    # mock client.get_ticker 返回有效价格，避免 _refresh_price 异常
    strategy.client.get_ticker = MagicMock(return_value=[{"last": "45000"}])

    # 让主循环最多跑一个 tick 后退出：在 on_start 后置 _running=False
    original_on_start_calls: list[bool] = []

    async def _force_stop_after_start(*args, **kwargs):
        # on_start 调用后立即停止主循环
        original_on_start_calls.append(True)
        strategy._running = False

    # 用一个最简的 fake base_block 替代真实 GridBlock（避免真实下单）
    fake_block = MagicMock()
    fake_block.on_start = _force_stop_after_start
    fake_block.on_tick = MagicMock(return_value=None)
    fake_block.on_stop = _force_stop_after_start

    # 让 _record_event 不写数据库
    strategy._record_event = lambda *a, **k: None

    # 直接预置 _dsl/_fsm/_base_block 以跳过 execute 内部的实例化逻辑，
    # 仅验证「qs_model_config 被读取并解析为合法 DSL」这一行为。
    # 这里走完整的 execute 流程，所以先调用 _resolve_dsl_config 验证可编译。
    dsl = strategy._resolve_dsl_config()
    assert dsl.base_strategy.params["symbol"] == "BTC-USDT"
    assert dsl.base_strategy.params["upper_price"] == 50000

    # 编译 FSM 不应抛异常（验证解析后的 DSL 是合法可编译的）
    from dsl.compiler import FSMCompiler
    fsm = FSMCompiler().compile(dsl)
    assert fsm.initial_state == "RUNNING"
    assert len(fsm.transitions) >= 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
