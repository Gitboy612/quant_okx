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
import time
from typing import Any

from strategies.base_strategy import BaseStrategy
from dsl.schema import (
    StrategyDSL,
    Rule,
    ActionRef,
    ConditionRef,
    EventRef,
    IndicatorRef,
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


class ComposableStrategy(BaseStrategy):
    """可拼接策略执行器，作为 _strategy_map['composable'] 的实现。

    从 ``self.params['dsl_config']`` 读取 DSL 配置，编译为 FSM，按状态机
    驱动基础策略 Block（如 GridBlock）。本类只负责编排，具体行为由基础
    策略钩子与积木库实现。

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

    # ============================================================
    # 参数校验
    # ============================================================

    async def validate_params(self) -> bool:
        """校验 ``self.params['dsl_config']`` 配置合法性。"""
        config = self.params.get("dsl_config")
        if not config:
            return False
        try:
            result = DSLValidator().validate(config)
        except Exception:
            return False
        return result.valid

    # ============================================================
    # 主入口
    # ============================================================

    async def execute(self):
        """主入口：编译 DSL → 启动基础策略 → FSM 主循环。"""
        # 1. 读取并校验 DSL 配置
        config = self.params.get("dsl_config")
        if not config:
            self._record_event("error", "ComposableStrategy: 缺少 dsl_config 参数")
            return

        try:
            result = DSLValidator().validate(config)
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

        # 2. 编译为 FSM
        try:
            self._dsl = StrategyDSL.model_validate(config)
            self._fsm = FSMCompiler().compile(self._dsl)
        except Exception as e:
            self._record_event("error", f"ComposableStrategy: FSM 编译失败 {e}")
            return

        # 3. 构建 rule_name -> Rule 映射（用于冷却查询）
        self._rule_map = {rule.name: rule for rule in self._dsl.rules}

        # 4. 实例化基础策略 Block（GridBlock 等只接收策略专属参数）
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

        # 5. 启动：标记运行、刷新最新价、构建初始 ctx、挂初始网格、绑定事件
        self._running = True
        self._paused = False

        symbol = self._get_symbol()
        await self._refresh_price(symbol)

        ctx = self._build_context()
        try:
            await self._base_block.on_start(ctx)
        except Exception as e:
            self._record_event("error", f"ComposableStrategy: on_start 异常 {e}")

        # 绑定事件（缓存实例 + 调用 bind 注册回调）
        self._bind_events(ctx)

        self._record_event("started", "ComposableStrategy 已启动，进入 FSM 主循环")

        # 6. FSM 主循环
        tick_interval = float(self.params.get("tick_interval", 3.0))
        current_state = self._fsm.initial_state  # "RUNNING"

        try:
            while self._running:
                # 每个 tick 刷新最新价并构建新 ctx（清空指标缓存）
                await self._refresh_price(symbol)
                ctx = self._build_context()

                # RUNNING 状态下调用基础策略 on_tick
                if current_state == "RUNNING":
                    try:
                        await self._base_block.on_tick(ctx)
                    except Exception as e:
                        self._handle_error(ctx, f"on_tick 异常: {e}")

                # 检查当前状态的所有出边转换
                for transition in self._fsm.transitions_from(current_state):
                    # 冷却检查
                    if self._is_in_cooldown(transition, ctx):
                        continue

                    # guard 评估
                    try:
                        guard_passed = await self._evaluate_guard(transition, ctx)
                    except Exception as e:
                        self._handle_error(ctx, f"guard 评估异常: {e}")
                        continue

                    if not guard_passed:
                        continue

                    # guard 通过：执行动作
                    try:
                        await self._execute_actions(transition.actions, ctx)
                    except Exception as e:
                        self._handle_error(ctx, f"action 执行异常: {e}")

                    # 状态迁移
                    old_state = current_state
                    current_state = transition.to_state

                    # 进入新状态副作用
                    try:
                        await self._enter_state(current_state, ctx)
                    except Exception as e:
                        self._handle_error(ctx, f"enter_state 异常: {e}")

                    # 记录冷却
                    self._last_triggered[transition.rule_name] = ctx.tick_ts

                    # 日志
                    self._log_state_transition(
                        old_state, current_state, transition, ctx
                    )

                    # 每个 tick 只执行一个转换
                    break

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
        if self._dsl is not None:
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

    async def _refresh_price(self, symbol: str) -> None:
        """刷新 ``self._last_price``（最新成交价）。失败保留旧值。"""
        if not symbol:
            return
        try:
            data = await self.client.get_ticker(symbol)
            if data:
                self._last_price = float(data[0]["last"])
        except Exception:
            pass

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
        """依次执行动作列表。"""
        for action_ref in actions:
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
        """
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
