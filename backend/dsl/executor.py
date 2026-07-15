"""可拼接策略 DSL 的 ComposableStrategy 执行器（Task 11）。

按 spec.md「Requirement: 状态机执行模型」实现：将已校验的 DSL 配置编译为
FSM，按状态机驱动基础策略 Block。本模块是 DSL 流水线的最后一环：

    dsl_config (dict)
      -> DSLValidator.validate        (静态校验)
      -> FSMCompiler.compile          (编译为 FSM)
      -> ComposableStrategy.execute   (本模块：FSM 主循环)

执行器每个 tick：
  1. 构建 ExecutionContext（清空指标缓存，刷新当前价）
  2. 若处于 RUNNING 状态，调用基础策略 on_tick
  3. 遍历当前状态的所有出边转换：
     - 冷却检查（rule.cool_down_seconds）
     - guard 评估（condition / event / always + extra_condition）
     - 通过则执行 actions、迁移状态、触发状态进入副作用、记录冷却
  4. 每个 tick 至多执行一次转换

事件处理：启动时遍历 FSM 中所有 guard_kind="event" 的转换，实例化事件类
并调用 bind(ctx) 注册回调（push 型事件如 on_order_filled 在此把回调挂到
OrderManager）。实例按 rule_name 缓存，guard 评估时优先复用缓存实例的
check(ctx) 以保留跨 tick 状态（队列 / 上次触发时间）；缓存不存在时回退到
无状态的 check_event（便于测试 mock）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

import httpx

from strategies.base_strategy import BaseStrategy
from dsl.schema import (
    StrategyDSL,
    Rule,
    ActionRef,
    ConditionRef,
    EventRef,
    IndicatorRef,
    QSModelConfig,
    RiskFilter,
    resolve_variables,
)
from dsl.compiler import (
    FSM,
    FSMState,
    FSMStateType,
    Transition,
    FSMCompiler,
)
from dsl.context import ExecutionContext
from dsl.validator import DSLValidator
from dsl.registry import base_strategy_registry, event_registry

# 导入积木库子模块触发 @indicator/@condition/@event/@action/@base_strategy
# 装饰器注册。重复导入无副作用。
from dsl.blocks import indicators as _indicators_mod  # noqa: F401
from dsl.blocks import conditions as _conditions_mod  # noqa: F401
from dsl.blocks import events as _events_mod  # noqa: F401
from dsl.blocks import actions as _actions_mod  # noqa: F401
from dsl.blocks import bases as _bases_mod  # noqa: F401  触发 grid 注册

# 积木库入口函数（按名导入，便于测试 patch dsl.executor.<name>）
from dsl.blocks.indicators import compute_indicator  # noqa: F401
from dsl.blocks.conditions import evaluate_condition
from dsl.blocks.events import check_event
from dsl.blocks.actions import execute_action


# FSM 编译缓存：logic_hash -> FSM（进程级共享）。
# FSM 为编译产物（states/transitions 编译后不再修改），不含实例运行态，
# 可安全跨实例复用，避免同 logic_hash 的多个实例每次启动都重复编译。
_fsm_cache: dict[str, FSM] = {}


class ComposableStrategy(BaseStrategy):
    """可拼接策略执行器，作为 _strategy_map['composable'] 的实现。

    优先从 ``self.params['qs_model_config']`` 读取 QS-Model 四段式配置
    （meta/params/logic/risk_filter），经 ``resolve_variables`` 解析
    ``$params.xxx`` / ``$meta.xxx`` 变量引用后编译为 FSM；若未提供则
    回退到旧的 ``self.params['dsl_config']`` 兼容路径。FSM 编译完成后
    按状态机驱动基础策略 Block（如 GridBlock）。本类只负责编排，具体
    行为由基础策略钩子与积木库实现。

    注意：基础策略 Block（GridBlock 等）不继承 BaseStrategy，构造时只接收
    策略专属参数（upper_price/lower_price/...），client/order_manager 等
    依赖通过 ExecutionContext 在每个钩子调用时传入。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # —— DSL 编译产物 ——
        self._dsl: StrategyDSL | None = None
        self._fsm: FSM | None = None
        self._base_block: Any = None
        # rule_name -> Rule，用于查询 cool_down_seconds
        self._rule_map: dict[str, Rule] = {}
        # rule_name -> Event 实例（push 型事件 bind 时注册回调、check 时复用）
        self._event_instances: dict[str, Any] = {}
        # rule_name -> 上次触发的 tick_ts（冷却记录）
        self._last_triggered: dict[str, float] = {}
        # 策略级 KV 状态（跨 tick 持久，跨规则共享）
        self._kv_state: dict[str, Any] = {}
        # 处于触发态的规则名集合（用于 rule_active 指标）
        self._active_rules: set[str] = set()
        # 缓存的最新价（每个 tick 刷新，供 on_start / 指标复用）
        self._last_price: float = 0.0
        # 当前 FSM 状态名（用于 _enter_state 检测自环转换，
        # 自环不触发生命周期钩子 on_pause/on_resume/on_stop）
        self._current_state: str | None = None
        # 最近一次 tick 的 ExecutionContext（供 push 型回调如
        # on_order_filled 在非 tick 时机复用）
        self._latest_ctx: ExecutionContext | None = None
        # QS-Model 风控段（若提供），供后续风控逻辑读取
        self._risk_filter: RiskFilter | None = None
        # 当日已实现盈亏基线（按 UTC 日期重置，用于 daily_max_loss 检查）
        self._daily_pnl_baseline: float = 0.0
        self._daily_reset_date: str = ""
        # Bug 5: 账户权益缓存（5 秒过期），避免风控/下单/持仓估值重复调用 API
        self._cached_equity: float = 0.0
        self._cached_equity_ts: float = 0.0
        # —— 主循环网络韧性（Task 5）——
        # 连续网络错误计数：达到 _max_consecutive_errors 后自动停止
        self._consecutive_errors: int = 0
        # 当前退避延迟（秒），网络错误时指数倍增，上限 30s
        self._backoff_delay: float = 1.0
        # 触发自动停止的连续网络错误阈值
        self._max_consecutive_errors: int = 10

    # ============================================================
    # 参数校验
    # ============================================================

    async def validate_params(self) -> bool:
        """校验 ``self.params['qs_model_config']`` 或 ``dsl_config`` 合法性。

        - 若提供 ``qs_model_config``：解析为 ``QSModelConfig``，解析变量后
          将 ``logic`` 段交给 ``DSLValidator`` 校验；
        - 否则回退到旧的 ``dsl_config`` 路径，直接交给 ``DSLValidator``。
        - 两者都缺失则返回 False。
        """
        qs_model_config = self.params.get("qs_model_config")
        dsl_config = self.params.get("dsl_config")
        if not qs_model_config and not dsl_config:
            return False

        try:
            if qs_model_config is not None:
                qs_model = QSModelConfig.model_validate(qs_model_config)
                # 收集 self.params 中与 qs_model.params 同名的实例参数覆盖
                param_overrides: dict[str, Any] = {}
                for key in qs_model.params:
                    if key in self.params:
                        param_overrides[key] = self.params[key]
                dsl = resolve_variables(qs_model, param_overrides)
                config_to_validate = dsl.model_dump()
            else:
                config_to_validate = dsl_config

            result = DSLValidator().validate(config_to_validate)
        except Exception:
            return False
        return result.valid

    # ============================================================
    # 主入口
    # ============================================================

    def _resolve_dsl_config(self) -> StrategyDSL:
        """从 ``self.params`` 解析出最终可执行的 ``StrategyDSL``。

        - 优先读取 ``qs_model_config``：解析为 ``QSModelConfig``，收集
          ``self.params`` 中与 ``qs_model.params`` 同名的实例参数作为
          ``param_overrides``，调用 ``resolve_variables`` 替换
          ``$params.xxx`` / ``$meta.xxx`` 引用；同时把 ``risk_filter``
          保存到 ``self._risk_filter`` 供后续风控逻辑读取。
        - 回退到旧的 ``dsl_config``：直接 ``StrategyDSL.model_validate``。
        - 两者均缺失则抛出 ``ValueError``。

        Returns:
            解析后的 ``StrategyDSL`` 对象。

        Raises:
            ValueError: 既未提供 ``qs_model_config`` 也未提供 ``dsl_config``。
            pydantic.ValidationError: 配置格式不合法。
        """
        qs_model_config = self.params.get("qs_model_config")
        dsl_config = self.params.get("dsl_config")

        if qs_model_config:
            qs_model = QSModelConfig.model_validate(qs_model_config)
            # 模板 base_symbol 为空时，用实例级 symbol 兜底，
            # 确保 $meta.base_symbol 引用能解析为实际交易对
            instance_symbol = self.params.get("symbol", "")
            if not qs_model.meta.base_symbol and instance_symbol:
                qs_model.meta.base_symbol = instance_symbol
            # 收集实例参数覆盖（self.params 中与 qs_model.params 同名的键）
            param_overrides: dict[str, Any] = {}
            for key in qs_model.params:
                if key in self.params:
                    param_overrides[key] = self.params[key]
            # 保存 risk_filter 供后续风控逻辑读取
            if qs_model.risk_filter is not None:
                self._risk_filter = qs_model.risk_filter
                self._record_event(
                    "info",
                    "ComposableStrategy: 已加载 QS-Model risk_filter",
                    {
                        "max_position_ratio": qs_model.risk_filter.max_position_ratio,
                        "daily_max_loss": qs_model.risk_filter.daily_max_loss,
                        "min_trade_size": qs_model.risk_filter.min_trade_size,
                    },
                )
            return resolve_variables(qs_model, param_overrides)

        if dsl_config:
            return StrategyDSL.model_validate(dsl_config)

        raise ValueError("策略缺少 qs_model_config 或 dsl_config")

    async def execute(self):
        """主入口：解析配置 → 校验 → 编译 FSM → 启动基础策略 → FSM 主循环。"""
        # 1. 解析配置（QS-Model 优先，回退到 dsl_config）
        try:
            self._dsl = self._resolve_dsl_config()
        except ValueError as e:
            self._record_event("error", f"ComposableStrategy: {e}")
            return
        except Exception as e:
            self._record_event(
                "error", f"ComposableStrategy: 配置解析失败 {e}"
            )
            return

        # 2. 校验 DSL（用解析后的 dsl 做 schema + 语义校验）
        try:
            result = DSLValidator().validate(self._dsl.model_dump())
        except Exception as e:
            self._record_event("error", f"ComposableStrategy: 校验异常 {e}")
            return
        if not result.valid:
            self._record_event(
                "error",
                "ComposableStrategy: dsl_config 校验失败",
                {"errors": [e.__dict__ for e in result.errors]},
            )
            return

        # 3. 编译为 FSM（带 logic_hash 缓存：同 logic_hash 复用，避免重复编译）
        try:
            logic_hash = self.params.get("logic_hash")
            if not logic_hash:
                # 实例未携带预计算的 logic_hash，现场基于解析后的 DSL 计算
                # （QSModelConfig.logic 不存在于已解析的 StrategyDSL 上，回退到整个 dsl）
                logic_source = getattr(self._dsl, "logic", None) or self._dsl
                logic_data = (
                    logic_source.model_dump()
                    if hasattr(logic_source, "model_dump")
                    else logic_source
                )
                logic_hash = hashlib.sha256(
                    json.dumps(
                        logic_data, sort_keys=True, ensure_ascii=False
                    ).encode("utf-8")
                ).hexdigest()
            cached = _fsm_cache.get(logic_hash)
            if cached is not None:
                self._fsm = cached
            else:
                self._fsm = FSMCompiler().compile(self._dsl)
                _fsm_cache[logic_hash] = self._fsm
        except Exception as e:
            self._record_event("error", f"ComposableStrategy: FSM 编译失败 {e}")
            return

        # 4. 构建 rule_name -> Rule 映射（用于冷却查询）
        self._rule_map = {rule.name: rule for rule in self._dsl.rules}

        # 5. 实例化基础策略 Block（GridBlock 等只接收策略专属参数）
        #    无基础策略（纯规则策略，kind=None）时跳过实例化与生命周期调用
        if self._dsl.base_strategy is not None and self._dsl.base_strategy.kind is not None:
            base_kind = self._dsl.base_strategy.kind
            base_cls = base_strategy_registry.get(base_kind)
            if base_cls is None:
                self._record_event(
                    "error", f"ComposableStrategy: 未知基础策略 kind {base_kind}"
                )
                return
            try:
                self._base_block = base_cls(**self._dsl.base_strategy.params)
            except Exception as e:
                self._record_event(
                    "error", f"ComposableStrategy: 基础策略实例化失败 {e}"
                )
                return

        # 6. 启动：标记运行、刷新最新价、构建初始 ctx、挂初始网格、绑定事件
        self._running = True
        self._paused = False

        # Bug 4: 恢复 realized_pnl 与 daily_pnl_baseline，避免重启后风控基线丢失
        self._restore_realized_pnl_from_db()
        self._load_daily_baseline()

        symbol = self._get_symbol()
        # 启动阶段刷新价格：用 5s 超时包裹，避免 OKX 客户端内部重试阻塞 FSM 主循环启动。
        # 超时/失败时使用 0.0 兜底价进入 FSM（主循环每 tick 会重新刷新）。
        try:
            await asyncio.wait_for(self._refresh_price(symbol), timeout=5.0)
        except asyncio.TimeoutError:
            self._record_event(
                "warn",
                f"ComposableStrategy: 启动刷新价格超时(5s)，使用兜底价 {self._last_price} 进入 FSM",
            )
        except Exception as e:
            self._record_event("warn", f"ComposableStrategy: 启动刷新价格失败: {e}")

        ctx = self._build_context()
        if self._base_block is not None:
            # on_start 含网络下单，用 10s 超时包裹避免 OKX 客户端内部重试阻塞 FSM 启动
            try:
                await asyncio.wait_for(self._base_block.on_start(ctx), timeout=10.0)
            except asyncio.TimeoutError:
                self._record_event(
                    "warn",
                    "ComposableStrategy: on_start 超时(10s)，跳过初始挂单，FSM 主循环继续",
                )
            except Exception as e:
                self._record_event("error", f"ComposableStrategy: on_start 异常 {e}")

        # 绑定事件（缓存实例 + 调用 bind 注册回调）
        self._bind_events(ctx)

        self._record_event("started", "ComposableStrategy 已启动，进入 FSM 主循环")

        # 7. FSM 主循环
        tick_interval = float(self.params.get("tick_interval", 3.0))
        current_state = self._fsm.initial_state  # "RUNNING"
        self._current_state = current_state

        try:
            while self._running:
                should_stop = False
                network_error_this_tick = False
                try:
                    # 每个 tick 刷新最新价并构建新 ctx（清空指标缓存）
                    # _refresh_price 不再抛出网络错误，内部计数并返回 False。
                    # 用 5s 超时包裹，避免 OKX 客户端内部重试阻塞单 tick。
                    try:
                        await asyncio.wait_for(self._refresh_price(symbol), timeout=5.0)
                    except asyncio.TimeoutError:
                        if self._handle_network_error(asyncio.TimeoutError("refresh_price timeout")):
                            break
                        network_error_this_tick = True
                    if not self._running:
                        break  # _refresh_price 触发自动停止
                    ctx = self._build_context()
                    self._latest_ctx = ctx

                    # 风控检查（daily_max_loss / stop_loss / take_profit）
                    if not await self._check_risk_filters(ctx):
                        break

                    # RUNNING 状态下调用基础策略 on_tick
                    if current_state == "RUNNING":
                        try:
                            if self._base_block is not None:
                                # on_tick 含网络操作，用 5s 超时避免 OKX 内部重试阻塞
                                try:
                                    await asyncio.wait_for(
                                        self._base_block.on_tick(ctx), timeout=5.0
                                    )
                                except asyncio.TimeoutError:
                                    if self._handle_network_error(
                                        asyncio.TimeoutError("on_tick timeout")
                                    ):
                                        should_stop = True
                                    else:
                                        network_error_this_tick = True
                        except Exception as e:
                            # 网络错误：计数但不跳过条件求值（使用缓存价）
                            if self._is_network_error(e):
                                if self._handle_network_error(e):
                                    should_stop = True
                                else:
                                    network_error_this_tick = True
                            else:
                                self._handle_error(ctx, f"on_tick 异常: {e}")

                    if should_stop:
                        break

                    # 检查当前状态的所有出边转换
                    for transition in self._fsm.transitions_from(current_state):
                        # 冷却检查
                        if self._is_in_cooldown(transition, ctx):
                            continue

                        # guard 评估
                        try:
                            guard_passed = await self._evaluate_guard(transition, ctx)
                        except Exception as e:
                            if self._is_network_error(e):
                                if self._handle_network_error(e):
                                    should_stop = True
                                    break
                                network_error_this_tick = True
                                continue
                            self._handle_error(ctx, f"guard 评估异常: {e}")
                            continue

                        if not guard_passed:
                            continue

                        # guard 通过：执行动作
                        action_failed = False
                        try:
                            await self._execute_actions(transition.actions, ctx)
                        except Exception as e:
                            if self._is_network_error(e):
                                if self._handle_network_error(e):
                                    should_stop = True
                                    break
                                network_error_this_tick = True
                                action_failed = True
                            else:
                                self._handle_error(ctx, f"action 执行异常: {e}")
                                action_failed = True

                        if action_failed:
                            continue  # 不迁移状态，继续下一条转换

                        # 状态迁移
                        old_state = current_state
                        current_state = transition.to_state

                        # 进入新状态副作用
                        try:
                            await self._enter_state(current_state, ctx)
                        except Exception as e:
                            if self._is_network_error(e):
                                if self._handle_network_error(e):
                                    should_stop = True
                                    break
                                network_error_this_tick = True
                            else:
                                self._handle_error(ctx, f"enter_state 异常: {e}")

                        # 记录冷却
                        self._last_triggered[transition.rule_name] = ctx.tick_ts

                        # 日志
                        self._log_state_transition(
                            old_state, current_state, transition, ctx
                        )

                        # 每个 tick 只执行一个转换
                        break

                    if should_stop:
                        break

                    # tick 无网络错误：重置网络错误计数与退避
                    if not network_error_this_tick:
                        self._consecutive_errors = 0
                        self._backoff_delay = 1.0

                except (httpx.HTTPError, OSError, ConnectionError) as e:
                    if self._handle_network_error(e):
                        break
                    await asyncio.sleep(self._backoff_delay)
                    continue
                except Exception as e:
                    # 按错误消息识别网络错误（WinError / timeout / connection 等）
                    if not self._is_network_error(e):
                        raise
                    if self._handle_network_error(e):
                        break
                    await asyncio.sleep(self._backoff_delay)
                    continue

                if network_error_this_tick:
                    await asyncio.sleep(self._backoff_delay)
                else:
                    await asyncio.sleep(tick_interval)
        finally:
            # 停止处理：调用基础策略 on_stop 清理
            try:
                if self._base_block is not None:
                    stop_ctx = self._build_context()
                    await self._base_block.on_stop(stop_ctx)
            except Exception as e:
                self._record_event("error", f"ComposableStrategy: on_stop 异常 {e}")
            self._record_event("stopped", "ComposableStrategy 已停止")

    # ============================================================
    # 上下文构建
    # ============================================================

    def _get_symbol(self) -> str:
        """从已编译的 DSL 或原始 dsl_config 字典中提取主交易对。"""
        if self._dsl is not None and self._dsl.base_strategy is not None and self._dsl.base_strategy.kind is not None:
            return self._dsl.base_strategy.params.get("symbol", "")
        config = self.params.get("dsl_config") or {}
        base = config.get("base_strategy") or {}
        sym = (base.get("params") or {}).get("symbol", "")
        return sym or self.params.get("symbol", "")

    def _build_context(self) -> ExecutionContext:
        """构建当前 tick 的 ExecutionContext（含清空指标缓存）。

        - kv_state / active_rules 跨 tick 持久（复用实例属性引用）
        - indicator_cache 每 tick 重建为空 dict（同 tick 内复用）
        - tick_ts 取当前时间，current_price 取缓存的最新价
        """
        return ExecutionContext(
            client=self.client,
            order_manager=self.order_manager,
            base_strategy=self._base_block,
            strategy=self,
            instance_id=self.instance_id,
            account_id=self.account_id or 0,
            symbol=self._get_symbol(),
            tick_ts=time.time(),
            current_price=self._last_price,
            kv_state=self._kv_state,
            active_rules=self._active_rules,
            indicator_cache={},  # 每 tick 清空
            db_session_factory=self.db_session_factory,
            realized_pnl=self._realized_pnl,
        )

    async def _refresh_price(self, symbol: str) -> bool:
        """刷新 ``self._last_price``（最新成交价）。

        网络错误不再向上抛出（避免跳过条件求值），而是记录错误计数并返回 False。
        主循环依据返回值决定是否退避，但条件求值仍然继续（使用上次缓存价）。
        非网络错误保留旧值并返回 False。

        Returns:
            True 表示刷新成功；False 表示刷新失败（网络或非网络错误）。
        """
        if not symbol:
            return False
        try:
            data = await self.client.get_ticker(symbol)
            if data:
                self._last_price = float(data[0]["last"])
                return True
        except Exception as e:
            if self._is_network_error(e):
                # 网络错误：计数但不跳过条件求值
                if self._handle_network_error(e):
                    return False
            # 非网络错误：保留旧值
        return False

    # ============================================================
    # guard 评估
    # ============================================================

    async def _evaluate_guard(
        self, transition: Transition, ctx: ExecutionContext
    ) -> bool:
        """评估转换的 guard。

        - ``guard_kind='condition'``: 调用 ``evaluate_condition(trigger.condition, ctx)``
        - ``guard_kind='event'``: 优先复用缓存的事件实例 ``check(ctx)``（保留
          push 型事件跨 tick 状态）；缓存不存在时回退到无状态的
          ``check_event(trigger.event, ctx)``，非 None 即通过
        - ``guard_kind='always'``: 直接通过

        guard 通过后若 ``trigger.extra_condition`` 非空，还需其为 True。
        """
        gk = transition.guard_kind
        trigger = transition.trigger

        if gk == "condition":
            if trigger.condition is None:
                return False
            guard_passed = await evaluate_condition(trigger.condition, ctx)
        elif gk == "event":
            payload = None
            inst = self._event_instances.get(transition.rule_name)
            if inst is not None:
                # 复用缓存实例（保留队列 / 上次触发时间等跨 tick 状态）
                payload = await inst.check(ctx)
            else:
                if trigger.event is None:
                    return False
                # 无状态回退（便于测试 mock；push 型事件此路径无法保留状态）
                payload = await check_event(trigger.event, ctx)
            guard_passed = payload is not None
        elif gk == "always":
            guard_passed = True
        else:
            guard_passed = False

        if not guard_passed:
            return False

        # extra_condition 二次过滤（event AND condition 组合）
        if trigger.extra_condition is not None:
            return await evaluate_condition(trigger.extra_condition, ctx)
        return True

    # ============================================================
    # 动作执行
    # ============================================================

    async def _execute_actions(
        self, actions: list[ActionRef], ctx: ExecutionContext
    ) -> None:
        """依次执行动作列表。place_order 动作在下单前会做风控检查。"""
        for action_ref in actions:
            # 下单前风控检查（max_position_ratio / min_trade_size）
            if action_ref.kind == "place_order":
                if not await self._check_order_risk(ctx, action_ref):
                    continue
            await execute_action(action_ref, ctx)

    # ============================================================
    # 状态进入副作用
    # ============================================================

    async def _enter_state(
        self, state_name: str, ctx: ExecutionContext
    ) -> None:
        """状态进入副作用：

        - 进入 PAUSED: 调用 ``base_block.on_pause(ctx)``
        - 进入 REBALANCING: 无特殊钩子
        - 进入 RUNNING: 调用 ``base_block.on_resume(ctx)``

        自环转换（old_state == new_state，如无 recover_when 的规则产生的
        RUNNING→RUNNING）仅执行 transition 上绑定的 actions（在调用方完成），
        不触发生命周期钩子，避免每 tick 重复 on_resume → on_start 爆炸挂单。
        """
        old_state = self._current_state
        if old_state == state_name:
            # 自环转换：不触发生命周期钩子
            return
        self._current_state = state_name

        state_type = self._resolve_state_type(state_name)

        if state_type == FSMStateType.PAUSED:
            if self._base_block is not None:
                await self._base_block.on_pause(ctx)
        elif state_type == FSMStateType.RUNNING:
            if self._base_block is not None:
                await self._base_block.on_resume(ctx)
        # REBALANCING: 无特殊钩子

    def _resolve_state_type(self, state_name: str) -> FSMStateType | None:
        """从 FSM 查询状态类型；FSM 未设置时按名称前缀推断（便于测试）。"""
        if self._fsm is not None:
            state = self._fsm.get_state(state_name)
            if state is not None:
                return state.state_type
        # 回退推断（测试场景下 _fsm 可能未设置）
        if state_name == "RUNNING":
            return FSMStateType.RUNNING
        if state_name.startswith("PAUSED"):
            return FSMStateType.PAUSED
        if state_name.startswith("REBALANCING"):
            return FSMStateType.REBALANCING
        return None

    # ============================================================
    # 冷却
    # ============================================================

    def _is_in_cooldown(
        self, transition: Transition, ctx: ExecutionContext
    ) -> bool:
        """判断转换所属规则是否处于冷却期。

        从 ``self._rule_map`` 取 Rule 的 ``cool_down_seconds``，与
        ``self._last_triggered`` 中记录的上次触发 tick_ts 比较。
        """
        rule = self._rule_map.get(transition.rule_name)
        if rule is None or rule.cool_down_seconds <= 0:
            return False
        last = self._last_triggered.get(transition.rule_name)
        if last is None:
            return False
        return (ctx.tick_ts - last) < rule.cool_down_seconds

    # ============================================================
    # 事件订阅
    # ============================================================

    def _bind_events(self, ctx: ExecutionContext) -> None:
        """遍历 FSM 中所有 event-triggered 转换，实例化事件并调用 ``bind(ctx)``。

        实例按 ``rule_name`` 缓存到 ``self._event_instances``，供
        ``_evaluate_guard`` 复用以保留 push 型事件的跨 tick 状态（队列 /
        上次触发时间）。

        同时为基础策略 Block 注册 OrderManager "filled" 回调，把订单成交
        事件转发给 ``base_block.on_order_filled``（接通反向挂单）。
        """
        if self._fsm is None:
            return
        for transition in self._fsm.transitions:
            if transition.guard_kind != "event":
                continue
            if transition.trigger.event is None:
                continue
            # 同一 rule_name 只缓存首个 event 转换的实例（P0 足够）
            if transition.rule_name in self._event_instances:
                continue
            ref = transition.trigger.event
            cls = event_registry.get(ref.kind)
            if cls is None:
                self._record_event("warn", f"未知事件 kind: {ref.kind}，跳过 bind")
                continue
            try:
                inst = cls(**ref.args)
                inst.bind(ctx)
                self._event_instances[transition.rule_name] = inst
            except Exception as e:
                self._record_event(
                    "warn", f"事件 bind 失败 kind={ref.kind}: {e}"
                )

        # 接通基础策略的 on_order_filled 回调（Task 5.1）
        if self._base_block is not None and hasattr(self._base_block, "on_order_filled"):
            self.order_manager.on("filled", self._on_order_filled_cb)

    def _on_order_filled_cb(self, order):
        """OrderManager filled 回调：转发给基础策略的 on_order_filled 钩子。

        返回协程（由 OrderManager._trigger_callbacks 通过
        asyncio.ensure_future 调度），使用最近一次 tick 的 ctx。
        """
        if self._base_block is None:
            return
        ctx = self._latest_ctx if self._latest_ctx is not None else self._build_context()
        return self._base_block.on_order_filled(order, ctx)

    # ============================================================
    # 日志与异常
    # ============================================================

    def _log_state_transition(
        self,
        old_state: str,
        new_state: str,
        transition: Transition,
        ctx: ExecutionContext,
    ) -> None:
        """记录一次 FSM 状态转换。"""
        self._record_event(
            "fsm_transition",
            f"FSM 转换: {old_state} -> {new_state} (rule={transition.rule_name})",
            {
                "old_state": old_state,
                "new_state": new_state,
                "rule_name": transition.rule_name,
                "guard_kind": transition.guard_kind,
                "is_recovery": transition.is_recovery,
                "tick_ts": ctx.tick_ts,
                "price": ctx.current_price,
            },
        )

    def _handle_error(self, ctx: ExecutionContext, message: str) -> None:
        """主循环异常处理：记录事件 + 设置 error flag 触发 on_strategy_error。

        不直接退出主循环（除非是致命错误）；on_strategy_error 事件积木通过
        检测 ``ctx.kv_state['_strategy_error_flag']`` 一次性消费此 flag。
        """
        self._record_event("error", f"ComposableStrategy: {message}")
        ctx.kv_state["_strategy_error_flag"] = True
        ctx.kv_state["_strategy_error_msg"] = message

    @staticmethod
    def _is_network_error(exc: BaseException) -> bool:
        """判断异常是否为网络错误。

        先按异常类型匹配（``httpx.HTTPError`` / ``OSError`` /
        ``ConnectionError``），再按错误消息关键词匹配（winerror /
        timeout / connection），覆盖 OKX SDK 抛出的非 httpx 类型但
        携带网络错误信息的异常（如 WinError 64 / 10054）。
        """
        if isinstance(exc, (httpx.HTTPError, OSError, ConnectionError)):
            return True
        msg = str(exc).lower()
        return any(kw in msg for kw in ("winerror", "timeout", "connection"))

    def _handle_network_error(self, exc: BaseException) -> bool:
        """主循环网络错误退避处理（Task 5）。

        递增 ``_consecutive_errors``，``_backoff_delay`` 指数倍增
        （1s→2s→4s→8s→16s，上限 30s），记录事件。连续错误达到
        ``_max_consecutive_errors`` 时调用 ``stop()``、标记实例
        ``error`` 状态并记录 "连续网络错误超限，自动停止"。

        Returns:
            True 表示已达到阈值、主循环应 break；False 表示退避后继续。
        """
        self._consecutive_errors += 1
        self._backoff_delay = min(self._backoff_delay * 2, 30.0)
        self._record_event(
            "error",
            f"ComposableStrategy: 网络异常 (第{self._consecutive_errors}次)，"
            f"退避 {self._backoff_delay}s: {str(exc)[:200]}",
        )
        if self._consecutive_errors >= self._max_consecutive_errors:
            self._record_event("error", "连续网络错误超限，自动停止")
            self.stop()
            try:
                self.update_status("error")
            except Exception:
                pass
            return True
        return False

    # ============================================================
    # 风控（Task 5）
    # ============================================================

    async def _check_risk_filters(self, ctx: ExecutionContext) -> bool:
        """每 tick 风控检查（daily_max_loss / stop_loss / take_profit）。

        返回 True 表示正常继续，False 表示已触发风控停止。
        ``risk_filter`` 为 None 时跳过所有检查（SubTask 5.4）。
        """
        if self._risk_filter is None:
            return True

        rf = self._risk_filter

        # 5.1 daily_max_loss: 累计当日已实现亏损达阈值
        if rf.daily_max_loss is not None:
            daily_pnl = self._get_daily_realized_pnl()
            if daily_pnl < 0:
                equity = await self._get_account_equity()
                if equity > 0 and abs(daily_pnl) / equity >= rf.daily_max_loss:
                    await self._trigger_risk_stop(ctx, "daily_max_loss", {
                        "daily_realized_pnl": daily_pnl,
                        "equity": equity,
                        "threshold": rf.daily_max_loss,
                    })
                    return False

        # 5.2 stop_loss / take_profit: 未实现盈亏率触发阈值
        # 用 5s 超时包裹 get_positions，避免 OKX 客户端内部重试阻塞条件求值。
        # 超时返回 None（无持仓），跳过风控，让条件求值继续。
        if rf.stop_loss is not None or rf.take_profit is not None:
            try:
                upl_ratio = await asyncio.wait_for(
                    self._get_unrealized_pnl_ratio(ctx), timeout=5.0
                )
            except asyncio.TimeoutError:
                upl_ratio = None
            if upl_ratio is not None:
                if rf.stop_loss is not None and upl_ratio <= -abs(rf.stop_loss):
                    await self._trigger_risk_stop(ctx, "stop_loss", {
                        "upl_ratio": upl_ratio,
                        "threshold": rf.stop_loss,
                    })
                    return False
                if rf.take_profit is not None and upl_ratio >= abs(rf.take_profit):
                    await self._trigger_risk_stop(ctx, "take_profit", {
                        "upl_ratio": upl_ratio,
                        "threshold": rf.take_profit,
                    })
                    return False

        return True

    async def _check_order_risk(
        self, ctx: ExecutionContext, action_ref: ActionRef
    ) -> bool:
        """下单前风控检查（max_position_ratio / min_trade_size）。

        返回 True 允许下单，False 拒绝。``risk_filter`` 为 None 时跳过。
        """
        if self._risk_filter is None:
            return True

        rf = self._risk_filter
        qty = action_ref.args.get("qty")

        # min_trade_size: 订单量不得小于最小交易量
        if rf.min_trade_size is not None and isinstance(qty, (int, float)) \
                and not isinstance(qty, bool):
            if qty < rf.min_trade_size:
                self._record_event(
                    "risk_rejected",
                    f"下单被风控拒绝: 订单量 {qty} 小于最小交易量 {rf.min_trade_size}",
                    {"qty": qty, "min_trade_size": rf.min_trade_size,
                     "symbol": ctx.symbol},
                )
                return False

        # max_position_ratio: 下单后持仓占比不得超过上限
        if rf.max_position_ratio is not None:
            price = ctx.current_price
            if price > 0 and isinstance(qty, (int, float)) \
                    and not isinstance(qty, bool):
                equity = await self._get_account_equity()
                if equity > 0:
                    current_pos_value = await self._get_position_value(ctx, price)
                    new_pos_value = current_pos_value + abs(qty) * price
                    ratio = new_pos_value / equity
                    if ratio > rf.max_position_ratio:
                        self._record_event(
                            "risk_rejected",
                            f"下单被风控拒绝: 持仓占比 {ratio:.4f} 超过上限 "
                            f"{rf.max_position_ratio}",
                            {"current_pos_value": current_pos_value,
                             "order_value": abs(qty) * price,
                             "equity": equity, "ratio": ratio,
                             "max_position_ratio": rf.max_position_ratio},
                        )
                        return False

        return True

    async def _trigger_risk_stop(
        self, ctx: ExecutionContext, reason: str, details: dict
    ) -> None:
        """触发风控：close_all（撤销所有订单）+ stop_strategy + log_event。"""
        symbol = ctx.symbol
        # close_all: 撤销所有挂单
        try:
            cancelled = await self.order_manager.cancel_all(symbol)
            details["cancelled"] = cancelled
        except Exception as e:
            self._record_event("error", f"风控平仓异常: {e}")
        # log_event
        self._record_event(
            "risk_triggered",
            f"风控触发: {reason}，策略停止",
            {"reason": reason, **details},
        )
        # stop_strategy
        self._running = False

    # ------------------------------------------------------------
    # 风控辅助：账户 / 持仓信息查询
    # ------------------------------------------------------------

    async def _get_account_equity(self) -> float:
        """获取账户总权益（Bug 5: 5 秒缓存，避免每 tick 重复调用 API）。

        风控检查 / 下单风控 / 持仓估值复用同一缓存值，缓存过期后刷新。
        失败时返回上次缓存值（若有），避免返回 0 误触发风控。
        """
        now = time.time()
        if self._cached_equity_ts > 0 and (now - self._cached_equity_ts) < 5.0:
            return self._cached_equity
        try:
            balance = await asyncio.wait_for(self.client.get_balance(), timeout=5.0)
            data = balance.get("data", []) if isinstance(balance, dict) else []
            if data:
                equity = float(data[0].get("totalEq", 0) or 0)
                self._cached_equity = equity
                self._cached_equity_ts = now
                return equity
        except (asyncio.TimeoutError, Exception):
            pass
        return self._cached_equity

    async def _get_unrealized_pnl_ratio(
        self, ctx: ExecutionContext
    ) -> float | None:
        """获取当前 symbol 的未实现盈亏率。无持仓返回 None。"""
        symbol = ctx.symbol
        if not symbol:
            return None
        try:
            positions = await ctx.client.get_positions()
            for pos in positions:
                inst_id = (pos.get("instId") if isinstance(pos, dict)
                           else getattr(pos, "instId", None))
                if inst_id == symbol:
                    ratio = (pos.get("uplRatio") if isinstance(pos, dict)
                             else getattr(pos, "uplRatio", None))
                    if ratio is not None:
                        return float(ratio)
                    # fallback: 用 upl / margin 计算
                    upl = (pos.get("upl") if isinstance(pos, dict)
                           else getattr(pos, "upl", None))
                    margin = (pos.get("margin") if isinstance(pos, dict)
                              else getattr(pos, "margin", None))
                    if upl is not None and margin and float(margin) > 0:
                        return float(upl) / float(margin)
                    break
        except Exception:
            pass
        return None

    async def _get_position_value(
        self, ctx: ExecutionContext, price: float
    ) -> float:
        """获取当前 symbol 的持仓价值（按给定价格估算）。"""
        symbol = ctx.symbol
        if not symbol:
            return 0.0
        try:
            positions = await asyncio.wait_for(
                ctx.client.get_positions(), timeout=5.0
            )
            for pos in positions:
                inst_id = (pos.get("instId") if isinstance(pos, dict)
                           else getattr(pos, "instId", None))
                if inst_id == symbol:
                    pos_val = (pos.get("pos") if isinstance(pos, dict)
                               else getattr(pos, "pos", "0"))
                    return abs(float(pos_val or 0)) * price
        except (asyncio.TimeoutError, Exception):
            pass
        return 0.0

    def _get_daily_realized_pnl(self) -> float:
        """返回当日已实现盈亏（按 UTC 日期重置基线）。"""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._daily_reset_date:
            self._daily_reset_date = today
            self._daily_pnl_baseline = self._realized_pnl
            # Bug 4: 日期切换时持久化新基线，避免重启丢失
            self._save_daily_baseline()
        return self._realized_pnl - self._daily_pnl_baseline

    # ------------------------------------------------------------
    # Bug 4: daily_pnl_baseline 持久化（system_settings 表）
    # ------------------------------------------------------------

    def _daily_baseline_setting_key(self) -> str:
        return f"composable_daily_pnl_baseline_{self.instance_id}"

    def _restore_realized_pnl_from_db(self):
        """从最新 PnlRecord 恢复已实现盈亏（重启后），与 daily 基线配合使用。"""
        try:
            from models.pnl import PnlRecord
            db = self.db_session_factory()
            try:
                latest_pnl = db.query(PnlRecord).filter(
                    PnlRecord.strategy_instance_id == self.instance_id
                ).order_by(PnlRecord.recorded_at.desc()).first()
                if latest_pnl:
                    self.restore_realized_pnl(latest_pnl.realized_pnl or 0)
            finally:
                db.close()
        except Exception:
            pass

    def _load_daily_baseline(self):
        """Bug 4: 从 system_settings 表恢复 daily_pnl_baseline。

        启动时读取持久化的基线：若存储日期 == 当日则直接恢复；
        否则（跨天或首次启动）用当前 realized_pnl 重置并写回。
        """
        from datetime import datetime, timezone
        try:
            from models.system_settings import SystemSetting
            db = self.db_session_factory()
            try:
                s = db.query(SystemSetting).filter(
                    SystemSetting.key == self._daily_baseline_setting_key()
                ).first()
                if s and s.value:
                    data = json.loads(s.value)
                    stored_date = data.get("date", "")
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    if stored_date == today:
                        self._daily_pnl_baseline = float(data.get("baseline", 0.0))
                        self._daily_reset_date = stored_date
                        return
                # 跨天或无记录：重置基线
                self._daily_reset_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                self._daily_pnl_baseline = self._realized_pnl
                self._save_daily_baseline()
            finally:
                db.close()
        except Exception as e:
            self._record_event("warn", f"恢复 daily_pnl_baseline 失败: {e}")

    def _save_daily_baseline(self):
        """Bug 4: 持久化 daily_pnl_baseline 到 system_settings 表。"""
        from datetime import datetime, timezone
        try:
            from models.system_settings import SystemSetting
            db = self.db_session_factory()
            try:
                value = json.dumps({
                    "date": self._daily_reset_date,
                    "baseline": self._daily_pnl_baseline,
                })
                s = db.query(SystemSetting).filter(
                    SystemSetting.key == self._daily_baseline_setting_key()
                ).first()
                if s:
                    s.value = value
                    s.updated_at = datetime.now(timezone.utc)
                else:
                    s = SystemSetting(key=self._daily_baseline_setting_key(), value=value)
                    db.add(s)
                db.commit()
            finally:
                db.close()
        except Exception:
            pass
