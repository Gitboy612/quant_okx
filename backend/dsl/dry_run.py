"""可拼接策略 DSL 历史回放模拟器（Task 14）。

按 spec.md「Requirement: Dry-Run 模拟执行」实现：用历史 K 线数据回放
验证 DSL 配置。回放过程不实际下单，仅记录"如果在某时刻会触发某规则、
执行某动作"。

流程::

    config (dict)
      -> DSLValidator.validate        (静态校验，失败抛 ValueError)
      -> FSMCompiler.compile          (编译为 FSM)
      -> 拉取/注入 K 线               (OKX / candles 参数 / 模拟生成)
      -> 逐根 K 线回放                (构建 ctx → 评估 guard → 记录步骤)
      -> DryRunResult                 (完整时间轴)

关键设计：

- **_DryRunClient**：回放期间用作 ``ctx.client`` 的 mock 客户端。根据当前
  回放游标位置返回历史 K 线切片，使指标积木（如 ``price_change_pct``）能
  基于回放数据计算，而非请求实时行情。真实 OKX 客户端仅用于初始拉取 K 线。

- **不执行动作**：dry-run 只记录"会执行什么动作"（ActionRef.kind 列表），
  不调用 ``execute_action``、不下单、不撤单。

- **冷却**：与执行器一致，用 ``cool_down_seconds`` + tick_ts 差值判断，
  避免同一规则在连续 K 线上重复触发。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

from dsl.schema import StrategyDSL, Rule, Trigger, ActionRef, IndicatorRef
from dsl.compiler import FSM, Transition, FSMCompiler
from dsl.context import ExecutionContext
from dsl.validator import DSLValidator

# 导入积木库子模块以触发 @indicator / @condition / @event / @action /
# @base_strategy 装饰器注册（与 executor.py 保持一致，重复导入无副作用）。
import dsl.blocks.indicators  # noqa: F401
import dsl.blocks.conditions  # noqa: F401
import dsl.blocks.events  # noqa: F401
import dsl.blocks.actions  # noqa: F401
import dsl.blocks.bases  # noqa: F401

# 积木库入口函数
from dsl.blocks.indicators import compute_indicator
from dsl.blocks.conditions import evaluate_condition
from dsl.blocks.events import check_event


# ============================================================
# 数据结构
# ============================================================


@dataclass
class DryRunStep:
    """回放时间轴中的单步记录。

    Attributes:
        timestamp: ISO 格式时间戳（UTC）
        price: 当前 K 线收盘价
        state: 本步结束后的 FSM 状态（若本步发生转换则为新状态）
        indicator_values: {indicator_key: value} 本步计算的指标值
        triggered: 是否触发了规则转换
        rule_name: 触发的规则名（若触发）
        actions: 执行的动作 kind 列表（仅记录 kind，不实际执行）
        transition: 状态转换描述 "FROM -> TO"（若发生转换）
    """

    timestamp: str
    price: float
    state: str
    indicator_values: dict
    triggered: bool
    rule_name: str | None
    actions: list[str]
    transition: str | None


@dataclass
class DryRunResult:
    """回放结果。

    Attributes:
        steps: 完整时间轴
        total_ticks: 回放总步数（K 线根数）
        triggered_count: 触发转换的步数
        state_changes: 状态变更次数
        final_state: 回放结束时的 FSM 状态
    """

    steps: list[DryRunStep] = field(default_factory=list)
    total_ticks: int = 0
    triggered_count: int = 0
    state_changes: int = 0
    final_state: str = "RUNNING"


# ============================================================
# Dry-Run mock 客户端
# ============================================================


class _DryRunClient:
    """回放期间用作 ``ctx.client`` 的 mock 客户端。

    根据当前回放游标位置（``set_cursor``）返回历史 K 线切片，使指标积木
    能基于回放数据计算。所有方法签名与 ``OKXClient`` 对齐。

    K 线列表按时间正序存储（最早在前），``get_candles`` 返回最新在前的
    切片（与 OKX REST 返回格式一致），供指标积木直接消费。
    """

    def __init__(self, candles_chronological: list[list[str]]):
        # candles_chronological: 时间正序（最早在前），每根为 OKX 格式
        # [ts, o, h, l, c, vol, volCcy, volCcyConfirm, confirm]
        self._candles = candles_chronological
        self._cursor = 0

    def set_cursor(self, i: int) -> None:
        """设置当前回放位置（chronological 索引）。"""
        self._cursor = i

    async def get_candles(
        self, inst_id: str, bar: str = "1m", limit: str = "100"
    ) -> list[list[str]]:
        """返回截至当前游标的最近 N 根 K 线（最新在前）。"""
        n = int(limit) if limit else 100
        start = max(0, self._cursor - n + 1)
        end = self._cursor + 1
        slice_chrono = self._candles[start:end]
        return list(reversed(slice_chrono))  # OKX 格式：最新在前

    async def get_candles_history(
        self, inst_id: str, bar: str = None, after: str = None,
        before: str = None, limit: str = None,
    ) -> list[list[str]]:
        return await self.get_candles(inst_id, bar=bar or "1m", limit=limit or "100")

    async def get_ticker(self, inst_id: str) -> list[dict]:
        """返回当前游标处 K 线的收盘价作为最新价。"""
        if 0 <= self._cursor < len(self._candles):
            close = self._candles[self._cursor][4]
            return [{"last": str(close), "instId": inst_id}]
        return []

    async def get_positions(self) -> list:
        """dry-run 无持仓数据。"""
        return []

    async def get_balance(self) -> dict:
        """dry-run 无账户余额数据。"""
        return {"totalEq": "0"}


# ============================================================
# 模拟器
# ============================================================


class DryRunSimulator:
    """DSL 历史回放模拟器。

    用法::

        simulator = DryRunSimulator()  # 无 OKX 客户端，用模拟数据
        result = await simulator.run(config, "BTC-USDT", "1H", 100)

    或注入真实 OKX 客户端拉取历史 K 线::

        simulator = DryRunSimulator(okx_client)
        result = await simulator.run(config, "BTC-USDT", "1H", 100)

    或直接传入 K 线列表（测试用）::

        result = await simulator.run(config, "BTC-USDT", "1H", 100,
                                     candles=my_candles)
    """

    def __init__(self, okx_client: Any = None):
        """初始化模拟器。

        Args:
            okx_client: OKX 客户端实例，用于拉取历史 K 线。
                        传 None 时使用模拟数据（前端预览用）。
        """
        self._client = okx_client

    async def run(
        self,
        config: dict,
        symbol: str,
        bar: str = "1H",
        limit: int = 100,
        candles: list[list[str]] | None = None,
    ) -> DryRunResult:
        """执行历史回放。

        Args:
            config: DSL 配置字典
            symbol: 回放交易对（如 "BTC-USDT"）
            bar: K 线周期（如 "1H" / "5m" / "1D"）
            limit: 回放步数（K 线根数）
            candles: 可选，直接传入 K 线列表（时间正序，最早在前），
                     跳过 OKX 拉取。用于测试或离线回放。

        Returns:
            DryRunResult 含完整时间轴。

        Raises:
            ValueError: DSL 配置校验失败。
            CompilerError: FSM 编译失败（如死锁状态）。
        """
        # 1. 校验 config
        validation = DSLValidator().validate(config)
        if not validation.valid:
            msgs = "; ".join(
                f"[{e.layer}/{e.code}] {e.message}" for e in validation.errors
            )
            raise ValueError(f"DSL 配置校验失败: {msgs}")

        # 2. 编译为 FSM
        dsl = StrategyDSL.model_validate(config)
        fsm = FSMCompiler().compile(dsl)

        # 3. 拉取/注入 K 线（时间正序，最早在前）
        if candles is not None:
            candles_chrono = list(candles)
        elif self._client is not None:
            raw = await self._client.get_candles(
                inst_id=symbol, bar=bar, limit=str(limit)
            )
            # OKX 返回最新在前，反转为时间正序
            candles_chrono = list(reversed(raw or []))
        else:
            candles_chrono = self._generate_mock_candles(symbol, bar, limit)

        if not candles_chrono:
            return DryRunResult()

        # 4. 构建 dry-run mock 客户端（指标积木基于回放数据计算）
        dry_client = _DryRunClient(candles_chrono)

        # 5. 收集规则中引用的顶层指标（用于记录 indicator_values）
        indicator_refs = self._collect_indicator_refs(dsl)

        # 6. 构建 rule_name -> Rule 映射（冷却查询）
        rule_map: dict[str, Rule] = {rule.name: rule for rule in dsl.rules}
        last_triggered: dict[str, float] = {}  # rule_name -> tick_ts

        # 7. 逐根 K 线回放
        current_state = fsm.initial_state  # "RUNNING"
        steps: list[DryRunStep] = []
        triggered_count = 0
        state_changes = 0

        for i, candle in enumerate(candles_chrono):
            dry_client.set_cursor(i)

            # 解析 K 线：ts（毫秒）→ 秒，close 作为当前价
            try:
                ts_ms = int(float(candle[0]))
            except (IndexError, ValueError, TypeError):
                ts_ms = 0
            ts_sec = ts_ms / 1000.0
            try:
                close = float(candle[4])
            except (IndexError, ValueError, TypeError):
                close = 0.0

            # 构建 ExecutionContext（每 tick 重建，清空指标缓存）
            ctx = ExecutionContext(
                client=dry_client,
                order_manager=MagicMock(),
                symbol=symbol,
                tick_ts=ts_sec,
                current_price=close,
                kv_state={},
                active_rules=set(),
                indicator_cache={},
            )

            # 计算本步指标值（供记录；同时填充缓存供 guard 评估复用）
            indicator_values: dict[str, Any] = {}
            for key, ref in indicator_refs:
                try:
                    val = await compute_indicator(ref, ctx)
                    indicator_values[key] = val
                except Exception:
                    indicator_values[key] = None

            # 评估当前状态的所有出边转换
            step_triggered = False
            step_rule_name: str | None = None
            step_actions: list[str] = []
            step_transition: str | None = None

            for transition in fsm.transitions_from(current_state):
                # 冷却检查
                if self._is_in_cooldown(
                    transition, rule_map, last_triggered, ts_sec
                ):
                    continue

                # guard 评估
                try:
                    guard_passed = await self._evaluate_guard(transition, ctx)
                except Exception:
                    guard_passed = False

                if not guard_passed:
                    continue

                # guard 通过：记录规则名与动作 kind 列表（不实际执行）
                step_triggered = True
                step_rule_name = transition.rule_name
                step_actions = [a.kind for a in transition.actions]

                # 状态迁移
                old_state = current_state
                current_state = transition.to_state
                step_transition = f"{old_state} -> {current_state}"

                # 记录冷却
                last_triggered[transition.rule_name] = ts_sec
                triggered_count += 1
                if old_state != current_state:
                    state_changes += 1

                # 每个 tick 至多一个转换
                break

            # 生成 ISO 时间戳
            if ts_ms > 0:
                timestamp = datetime.fromtimestamp(
                    ts_sec, tz=timezone.utc
                ).isoformat()
            else:
                timestamp = datetime.now(timezone.utc).isoformat()

            steps.append(DryRunStep(
                timestamp=timestamp,
                price=close,
                state=current_state,
                indicator_values=indicator_values,
                triggered=step_triggered,
                rule_name=step_rule_name,
                actions=step_actions,
                transition=step_transition,
            ))

        return DryRunResult(
            steps=steps,
            total_ticks=len(steps),
            triggered_count=triggered_count,
            state_changes=state_changes,
            final_state=current_state,
        )

    # ============================================================
    # guard 评估（与执行器逻辑一致，但不执行动作）
    # ============================================================

    async def _evaluate_guard(
        self, transition: Transition, ctx: ExecutionContext
    ) -> bool:
        """评估转换的 guard。

        - ``guard_kind='condition'``: 调用 ``evaluate_condition(trigger.condition, ctx)``
        - ``guard_kind='event'``: 调用 ``check_event(trigger.event, ctx)``，非 None 即通过
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
            if trigger.event is None:
                return False
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
    # 冷却判断
    # ============================================================

    @staticmethod
    def _is_in_cooldown(
        transition: Transition,
        rule_map: dict[str, Rule],
        last_triggered: dict[str, float],
        tick_ts: float,
    ) -> bool:
        """判断转换所属规则是否处于冷却期。"""
        rule = rule_map.get(transition.rule_name)
        if rule is None or rule.cool_down_seconds <= 0:
            return False
        last = last_triggered.get(transition.rule_name)
        if last is None:
            return False
        return (tick_ts - last) < rule.cool_down_seconds

    # ============================================================
    # 指标引用收集（用于记录 indicator_values）
    # ============================================================

    def _collect_indicator_refs(
        self, dsl: StrategyDSL
    ) -> list[tuple[str, IndicatorRef]]:
        """收集 DSL 规则中条件直接引用的顶层指标（不递归 and/or/not）。

        返回 [(indicator_key, IndicatorRef), ...]，去重。
        """
        refs: list[tuple[str, IndicatorRef]] = []
        seen: set[str] = set()

        for rule in dsl.rules:
            for trigger in (rule.when, rule.recover_when):
                if trigger is None:
                    continue
                for cond in (trigger.condition, trigger.extra_condition):
                    if cond is None:
                        continue
                    ind = cond.args.get("indicator") if cond.args else None
                    if not isinstance(ind, dict):
                        continue
                    try:
                        ref = IndicatorRef(**ind)
                    except Exception:
                        continue
                    key = self._indicator_key(ref)
                    if key not in seen:
                        seen.add(key)
                        refs.append((key, ref))
        return refs

    @staticmethod
    def _indicator_key(ref: IndicatorRef) -> str:
        """生成可读的指标键，如 ``price_change_pct(symbol=BTC-USDT,window=1h)``。"""
        args_str = ",".join(
            f"{k}={v}" for k, v in sorted(ref.args.items())
        )
        return f"{ref.kind}({args_str})"

    # ============================================================
    # 模拟 K 线生成（无 OKX 客户端时的前端预览数据）
    # ============================================================

    def _generate_mock_candles(
        self, symbol: str, bar: str, limit: int
    ) -> list[list[str]]:
        """生成确定性模拟 K 线（价格从 100 开始，先涨后回落）。

        前半段每根 +6%（触发 ``gt(price_change_pct, 0.05)``），
        后半段每根 -3%（触发 ``abs_lt(price_change_pct, 0.05)`` 恢复）。

        返回时间正序（最早在前）的 K 线列表，OKX 格式。
        """
        base_ts = 1_700_000_000_000  # 毫秒时间戳
        bar_ms = self._bar_to_ms(bar)
        candles: list[list[str]] = []
        price = 100.0
        half = max(1, limit // 2)

        for i in range(limit):
            ts = str(base_ts + i * bar_ms)
            if i < half:
                change = 0.06  # +6%，触发暂停条件
            else:
                change = -0.03  # -3%，|change| < 5% 触发恢复
            open_price = price
            new_price = price * (1 + change)
            high = max(open_price, new_price)
            low = min(open_price, new_price)
            candle = [
                ts, str(open_price), str(high), str(low), str(new_price),
                "1", "1", "1", "1",
            ]
            candles.append(candle)
            price = new_price

        return candles

    @staticmethod
    def _bar_to_ms(bar: str) -> int:
        """将 OKX bar 周期转为毫秒。"""
        bar = (bar or "1H").strip()
        if not bar:
            return 3_600_000
        unit = bar[-1]
        try:
            num = int(bar[:-1])
        except ValueError:
            return 3_600_000
        if unit == "m":
            return num * 60_000
        if unit == "H":
            return num * 3_600_000
        if unit == "D":
            return num * 86_400_000
        if unit == "W":
            return num * 604_800_000
        return 3_600_000
