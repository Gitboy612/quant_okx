"""可拼接策略 DSL 的 FSM（有限状态机）编译器。

按 spec.md「Requirement: 状态机执行模型」实现：将已校验的 StrategyDSL
编译为 FSM。每条 Rule 编译为一个或多个转换：

- 有 ``recover_when`` 的规则（触发-恢复对）生成 3 个转换::

      RUNNING --[when]--> PAUSED_<rule>
        action: then
      PAUSED_<rule> --[recover_when]--> REBALANCING_<rule>
        action: recover_then  (is_recovery=True)
      REBALANCING_<rule> --[always]--> RUNNING
        action: (空)  (is_recovery=True，resume 由基础策略 on_resume 钩子完成)

- 无 ``recover_when`` 的规则（一次性触发）生成 1 个转换::

      RUNNING --[when]--> RUNNING
        action: then

编译完成后做状态可达性检查：所有派生状态（PAUSED/REBALANCING）都必须
能沿转换回到 RUNNING，否则抛出 ``CompilerError``。

编译器为纯同步代码，假设输入已通过 ``DSLValidator.validate()`` 校验
（valid=True）。编译阶段只处理 schema 数据结构，不实例化积木，也不
导入积木库（执行器 Task 11 才需要）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from dsl.schema import StrategyDSL, Rule, Trigger, ActionRef


# ============================================================
# FSM 数据结构
# ============================================================


class FSMStateType(Enum):
    """FSM 状态类型。"""

    RUNNING = "running"
    PAUSED = "paused"
    REBALANCING = "rebalancing"


@dataclass
class FSMState:
    """FSM 中的一个状态。

    Attributes:
        name: 状态名，如 "RUNNING" / "PAUSED_单边上涨暂停" / "REBALANCING_单边上涨暂停"
        state_type: 状态类型
        rule_name: 派生状态对应的 rule.name；RUNNING 为 None
    """

    name: str
    state_type: FSMStateType
    rule_name: str | None = None


@dataclass
class Transition:
    """FSM 状态转换。

    Attributes:
        from_state: 起始状态名
        to_state: 目标状态名
        trigger: 触发器（含 condition/event/extra_condition）；
                 ``guard_kind="always"`` 的转换不会评估 trigger
        guard_kind: "condition" / "event" / "always"，供执行器判断如何评估
        actions: 迁移时执行的动作列表
        rule_name: 归属的规则名
        is_recovery: 是否为恢复转换（PAUSED→REBALANCING 与 REBALANCING→RUNNING）
    """

    from_state: str
    to_state: str
    trigger: Trigger
    guard_kind: str  # "condition" / "event" / "always"
    actions: list[ActionRef]
    rule_name: str
    is_recovery: bool = False


class CompilerError(Exception):
    """FSM 编译错误（如存在不可回到 RUNNING 的死锁状态）。"""


@dataclass
class FSM:
    """有限状态机：状态集合 + 转换集合 + 初始状态。

    Attributes:
        states: 状态名 -> FSMState
        transitions: 全部转换列表
        initial_state: 初始状态名，恒为 "RUNNING"
    """

    states: dict[str, FSMState] = field(default_factory=dict)
    transitions: list[Transition] = field(default_factory=list)
    initial_state: str = "RUNNING"

    def transitions_from(self, state_name: str) -> list[Transition]:
        """返回从指定状态出发的全部转换。"""
        return [t for t in self.transitions if t.from_state == state_name]

    def get_state(self, name: str) -> FSMState | None:
        """按名查找状态，不存在返回 None。"""
        return self.states.get(name)

    def find_unreachable_to_running(self) -> list[str]:
        """返回所有无法回到 RUNNING 的非 RUNNING 状态名。

        用于死锁检测：每个派生状态（PAUSED/REBALANCING）都必须存在一条
        到 RUNNING 的有向路径，否则执行器进入后无法退出。沿转换的
        ``from_state -> to_state`` 方向做 DFS 判断可达性。
        """
        adjacency: dict[str, list[str]] = {}
        for t in self.transitions:
            adjacency.setdefault(t.from_state, []).append(t.to_state)

        deadlocked: list[str] = []
        for state_name in self.states:
            if state_name == self.initial_state:
                continue
            if not self._can_reach(state_name, self.initial_state, adjacency):
                deadlocked.append(state_name)
        return deadlocked

    @staticmethod
    def _can_reach(start: str, target: str,
                   adjacency: dict[str, list[str]]) -> bool:
        """从 start 出发能否沿有向边到达 target（含 start==target）。"""
        if start == target:
            return True
        visited: set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node == target:
                return True
            if node in visited:
                continue
            visited.add(node)
            for nxt in adjacency.get(node, []):
                if nxt not in visited:
                    stack.append(nxt)
        return False


# ============================================================
# 编译器
# ============================================================


class FSMCompiler:
    """将 StrategyDSL 编译为 FSM。

    假设输入已通过 ``DSLValidator.validate()`` 校验（valid=True）。编译器
    不做重复校验，但做防御性的状态可达性检查。
    """

    def compile(self, dsl: StrategyDSL) -> FSM:
        """将 DSL 编译为 FSM。

        Args:
            dsl: 已校验通过的 StrategyDSL（也接受等价的 dict，会被解析）。

        Returns:
            编译产物 FSM。

        Raises:
            CompilerError: 存在无法回到 RUNNING 的死锁状态。
        """
        # 兼容 dict 输入（与 DSLValidator.validate 风格一致）
        if isinstance(dsl, dict):
            dsl = StrategyDSL.model_validate(dsl)

        fsm = FSM()
        # RUNNING 主状态始终存在
        fsm.states["RUNNING"] = FSMState(
            name="RUNNING",
            state_type=FSMStateType.RUNNING,
            rule_name=None,
        )

        for rule in dsl.rules:
            self._compile_rule(fsm, rule)

        # 防御性可达性检查
        self._check_reachability(fsm)

        return fsm

    # ------------------------------------------------------------
    # 规则编译
    # ------------------------------------------------------------

    def _compile_rule(self, fsm: FSM, rule: Rule) -> None:
        """将单条 Rule 编译为状态与转换，追加到 fsm。"""
        # guard_kind 直接取 when.mode：condition / event
        guard_kind = rule.when.mode

        if rule.recover_when is not None:
            # 触发-恢复对：2 个派生状态 + 3 个转换
            paused_name = f"PAUSED_{rule.name}"
            rebalancing_name = f"REBALANCING_{rule.name}"

            fsm.states[paused_name] = FSMState(
                name=paused_name,
                state_type=FSMStateType.PAUSED,
                rule_name=rule.name,
            )
            fsm.states[rebalancing_name] = FSMState(
                name=rebalancing_name,
                state_type=FSMStateType.REBALANCING,
                rule_name=rule.name,
            )

            # 转换 1（触发）：RUNNING --[when]--> PAUSED_<rule>，执行 then
            fsm.transitions.append(Transition(
                from_state="RUNNING",
                to_state=paused_name,
                trigger=rule.when,
                guard_kind=guard_kind,
                actions=list(rule.then),
                rule_name=rule.name,
                is_recovery=False,
            ))

            # 转换 2（恢复评估）：PAUSED_<rule> --[recover_when]--> REBALANCING_<rule>
            # recover_then 全部在此执行（含 rebalance_position / resume_orders 等）；
            # resume 的语义由执行器在进入 RUNNING 时调用基础策略 on_resume 钩子兜底。
            fsm.transitions.append(Transition(
                from_state=paused_name,
                to_state=rebalancing_name,
                trigger=rule.recover_when,
                guard_kind=rule.recover_when.mode,
                actions=list(rule.recover_then),
                rule_name=rule.name,
                is_recovery=True,
            ))

            # 转换 3（回到运行）：REBALANCING_<rule> --[always]--> RUNNING
            # 无条件迁移；guard_kind="always"，执行器不评估 trigger；
            # resume 由基础策略 on_resume 钩子完成，故无显式动作。
            fsm.transitions.append(Transition(
                from_state=rebalancing_name,
                to_state="RUNNING",
                trigger=rule.recover_when,
                guard_kind="always",
                actions=[],
                rule_name=rule.name,
                is_recovery=True,
            ))
        else:
            # 一次性触发：RUNNING --[when]--> RUNNING，执行 then，不离开主状态
            fsm.transitions.append(Transition(
                from_state="RUNNING",
                to_state="RUNNING",
                trigger=rule.when,
                guard_kind=guard_kind,
                actions=list(rule.then),
                rule_name=rule.name,
                is_recovery=False,
            ))

    # ------------------------------------------------------------
    # 可达性检查（SubTask 10.3）
    # ------------------------------------------------------------

    def _check_reachability(self, fsm: FSM) -> None:
        """检查所有派生状态都能回到 RUNNING，否则抛出 CompilerError。

        校验器已保证 recover_when 配对，正常情况下不会出现死锁；
        本检查为防御性兜底（如未来扩展支持更复杂的状态拓扑）。
        """
        deadlocked = fsm.find_unreachable_to_running()
        if deadlocked:
            raise CompilerError(
                "存在无法回到 RUNNING 的死锁状态: "
                f"{sorted(deadlocked)}（每条 recover_when 规则必须形成回到 RUNNING 的闭环）"
            )
