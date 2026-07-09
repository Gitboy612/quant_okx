# Tasks

## 阶段一：核心框架（不可执行，仅为后续实现奠基）

- [x] Task 1: 创建 DSL 模块骨架目录结构
  - [x] SubTask 1.1: 创建 `backend/dsl/` 目录及 `__init__.py`
  - [x] SubTask 1.2: 创建 `backend/dsl/blocks/` 子目录及 `__init__.py`
  - [x] SubTask 1.3: 在 `requirements.txt` 确认 pydantic 版本（应已存在，无需新增依赖）

- [x] Task 2: 实现 Pydantic Schema（`backend/dsl/schema.py`）
  - [x] SubTask 2.1: 定义 `BlockRef` / `IndicatorRef` / `ConditionRef` / `ActionRef` / `EventRef` 基础模型
  - [x] SubTask 2.2: 定义 `Trigger`（mode=condition|event，含 condition/event/extra_condition 字段）
  - [x] SubTask 2.3: 定义 `Rule` / `BaseStrategyRef` / `StrategyDSL` 顶层模型
  - [x] SubTask 2.4: 编写单元测试验证序列化/反序列化（`backend/tests/test_dsl_schema.py`），覆盖 condition-trigger 与 event-trigger 两种 Rule 形态

- [x] Task 3: 实现注册表（`backend/dsl/registry.py`）
  - [x] SubTask 3.1: 实现 `Registry` 类（register/get/list/exists）
  - [x] SubTask 3.2: 实现 `@indicator` / `@condition` / `@action` / `@event` / `@base_strategy` 装饰器
  - [x] SubTask 3.3: 实例化五个全局注册表 `indicator_registry` / `condition_registry` / `action_registry` / `event_registry` / `base_strategy_registry`

## 阶段二：P0 积木库（最小可用集，覆盖用户示例）

> 积木完整清单见 spec.md「积木清单（金融技术视角）」章节，本期仅实现 P0 项。

- [x] Task 4: 实现 P0 指标库（`backend/dsl/blocks/indicators.py`）
  - [x] SubTask 4.1: 实现 `price_change_pct`（基于 window 起点价 vs 当前价，需缓存 ref_price 与时间戳）
  - [x] SubTask 4.2: 实现 `price_last`（最新成交价）
  - [x] SubTask 4.3: 实现 `position_qty` / `position_pnl`（调用 `client.get_positions`）
  - [x] SubTask 4.4: 实现 `account_equity`（调用 `client.get_balance`）
  - [x] SubTask 4.5: 实现 `rsi`（基于 K 线 close 序列，调用 `client.get_kline`）
  - [x] SubTask 4.6: 实现 `realized_pnl` / `unrealized_pnl`（从策略 STATE 读取）
  - [x] SubTask 4.7: 为每个指标声明 `param_schema` / `output_type` / `category` / `description` / `priority`（P0/P1/P2）

- [x] Task 5: 实现 P0 事件库（`backend/dsl/blocks/events.py`）
  - [x] SubTask 5.1: 实现 `on_tick`（订阅行情 tick，每 N 秒触发一次评估）
  - [x] SubTask 5.2: 实现 `on_order_filled`（订阅 OrderManager 的 filled 事件，可按 side/symbol 过滤）
  - [x] SubTask 5.3: 实现 `on_margin_warning`（轮询保证金率，低于阈值触发）
  - [x] SubTask 5.4: 实现 `on_interval`（定时器，每 N 秒触发）
  - [x] SubTask 5.5: 实现 `on_strategy_error`（订阅策略异常事件）
  - [x] SubTask 5.6: 为每个事件声明 `param_schema` / `category` / `description` / `priority`

- [x] Task 6: 实现 P0 条件库（`backend/dsl/blocks/conditions.py`）
  - [x] SubTask 6.1: 实现比较类 `gt` / `lt` / `abs_gt` / `abs_lt`
  - [x] SubTask 6.2: 实现逻辑组合 `and` / `or` / `not`（递归嵌套 ConditionRef）
  - [x] SubTask 6.3: 为每个条件声明输入类型期望（数值/bool）便于校验器类型检查

- [x] Task 7: 实现 P0 动作库（`backend/dsl/blocks/actions.py`）
  - [x] SubTask 7.1: 实现 `pause_orders`（调用基础策略的 `on_pause` 钩子，撤挂单但保留持仓）
  - [x] SubTask 7.2: 实现 `resume_orders`（调用基础策略的 `on_resume`，重新挂网格）
  - [x] SubTask 7.3: 实现 `hold_position`（空动作，仅记录事件）
  - [x] SubTask 7.4: 实现 `rebalance_position`（计算理论持仓 vs 实际持仓差值，下一笔市价单抹平，参数 `mode: to_theoretical`）
  - [x] SubTask 7.5: 实现 `cancel_all` / `place_order`（基础动作）
  - [x] SubTask 7.6: 实现 `log_event`（写 StrategyEvent 表，参数 level/message/details）

- [x] Task 8: 改造基础策略为可钩子调用（`backend/dsl/blocks/bases.py`）
  - [x] SubTask 8.1: 在 [base_strategy.py](file:///e:/New%20folder%20(2)/quant_okx/backend/strategies/base_strategy.py) 增加可选钩子方法 `on_start` / `on_tick` / `on_order_filled` / `on_pause` / `on_resume` / `on_stop`，默认空实现
  - [x] SubTask 8.2: 在 `base_strategy_registry` 中注册 `grid`，包装为可独立调用钩子的 Block（不再走 `execute()` 主循环，而是被 `ComposableStrategy` 编排）
  - [x] SubTask 8.3: 为 `grid` Block 声明生命周期钩子清单与所需 OKX 接口

## 阶段三：编译器与执行器

- [x] Task 9: 实现静态校验器（`backend/dsl/validator.py`）
  - [x] SubTask 9.1: 结构校验（Pydantic 自动）+ 引用校验（所有 kind 在五个注册表中存在）
  - [x] SubTask 9.2: 类型校验（Condition 输入指标类型匹配）+ 语义校验（RECOVER_WHEN 必须配 WHEN、无死锁状态、Trigger mode 字段与 condition/event 字段一致）
  - [x] SubTask 9.3: 编写测试覆盖合法/非法配置（`backend/tests/test_dsl_validator.py`），含 event-trigger 与 condition-trigger 两类用例

- [x] Task 10: 实现 FSM 编译器（`backend/dsl/compiler.py`）
  - [x] SubTask 10.1: 定义 `State` / `Transition` / `FSM` 数据类
  - [x] SubTask 10.2: `compile(dsl)` 将每条 Rule 转换为 2~3 个 transition（区分 event-trigger 与 condition-trigger 的 guard 求值时机）
  - [x] SubTask 10.3: 状态可达性分析（确保所有 PAUSED/REBALANCING 状态都能回到 RUNNING）

- [x] Task 11: 实现 ComposableStrategy 执行器（`backend/dsl/executor.py`）
  - [x] SubTask 11.1: 继承 `BaseStrategy`，`execute()` 内编译 DSL 为 FSM
  - [x] SubTask 11.2: 主循环：每个 tick 计算指标缓存 → 评估当前状态出边 guard → 迁移状态 → 执行 action
  - [x] SubTask 11.3: 事件触发器的事件订阅与分发（OrderManager filled 事件、定时器事件、策略异常事件）
  - [x] SubTask 11.4: 指标缓存层（同 tick 内多个 condition 共用同一 indicator 结果）
  - [x] SubTask 11.5: 冷却时间 `cool_down_seconds` 强制等待，避免规则抖动

## 阶段四：集成与 API

- [x] Task 12: 数据模型与 Engine 集成
  - [x] SubTask 12.1: [models/strategy.py](file:///e:/New%20folder%20(2)/quant_okx/backend/models/strategy.py) 的 `StrategyTemplate` 增加 `dsl_config = Column(JSON, nullable=True)`
  - [x] SubTask 12.2: [schemas/strategy.py](file:///e:/New%20folder%20(2)/quant_okx/backend/schemas/strategy.py) 增加 `StrategyTemplateCreate.dsl_config` 可选字段
  - [x] SubTask 12.3: [strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py) `_strategy_map` 增加 `"composable": ComposableStrategy`
  - [x] SubTask 12.4: 数据库迁移脚本（如使用 Alembic，生成迁移；否则确认 SQLAlchemy `create_all` 自动建列）

- [x] Task 13: 实现 REST API（`backend/routers/dsl.py`）
  - [x] SubTask 13.1: `GET /api/dsl/blocks` 聚合五个注册表的 `list()` 输出，按 category 分组
  - [x] SubTask 13.2: `POST /api/dsl/validate` 调用 `DSLValidator` 返回错误列表
  - [x] SubTask 13.3: 在 [main.py](file:///e:/New%20folder%20(2)/quant_okx/backend/main.py) 注册新路由

## 阶段五：Dry-Run（可后置，本 spec 列出但不阻塞主流程）

- [x] Task 14: 实现历史回放模拟器（`backend/dsl/dry_run.py`）
  - [x] SubTask 14.1: 输入 DSL + 起止时间 + symbol，拉取 K 线序列
  - [x] SubTask 14.2: 按时间步进重放 tick，调用 FSM 编译产物评估 transition
  - [x] SubTask 14.3: 输出事件时间轴 JSON（每步：ts、indicator 值、是否触发、state、actions）
  - [x] SubTask 14.4: `POST /api/dsl/dry-run` 接口

## 阶段六：端到端验证

- [x] Task 15: 用用户示例端到端验证
  - [x] SubTask 15.1: 构造「网格 + 单边暂停恢复」DSL 配置
  - [x] SubTask 15.2: 调用 `/api/dsl/validate` 通过
  - [x] SubTask 15.3: 创建 StrategyTemplate（strategy_type="composable", dsl_config=<配置>）
  - [x] SubTask 15.4: 创建 StrategyInstance 并启动，观察事件日志符合预期
  - [x] SubTask 15.5: 调用 Dry-Run，验证历史回放事件序列合理

## 阶段七：P1 积木库扩展（后续，不阻塞 P0 上线）

- [ ] Task 16: 实现 P1 积木（见 spec.md 积木清单标注 P1 的项）
  - [ ] SubTask 16.1: 指标 P1：`price_change_abs` / `price_high` / `price_low` / `ma` / `ema` / `macd` / `boll` / `atr` / `volume` / `funding_rate` / `basis` / `position_margin_ratio` / `liquidation_price` / `account_available` 等
  - [ ] SubTask 16.2: 事件 P1：`on_kline_close` / `on_order_placed` / `on_position_opened` / `on_position_closed` / `on_liquidation_approaching` / `on_schedule` 等
  - [ ] SubTask 16.3: 条件 P1：`gte` / `lte` / `eq` / `cross_above` / `cross_below` / `in_range` / `out_range`
  - [ ] SubTask 16.4: 动作 P1：`open_position` / `close_position` / `reduce_position` / `hedge_position` / `set_stop_loss` / `adjust_leverage` / `send_alert` / `set_state` 等
  - [ ] SubTask 16.5: 基础策略 P1：将 `trend` / `arbitrage` / `advanced_grid_hedge` 改造为可钩子 Block 并注册

# Task Dependencies

- Task 1 → Task 2 → Task 3（Schema 与注册表是后续一切的基础）
- Task 3 → Task 4 / Task 5 / Task 6 / Task 7（四类积木库依赖注册表）
- Task 8 依赖 Task 3（基础策略改造需先有 `base_strategy_registry`）
- Task 9 依赖 Task 4 / Task 5 / Task 6 / Task 7（校验器需引用全部积木库）
- Task 10 依赖 Task 2 / Task 9（编译器依赖 Schema 与校验）
- Task 11 依赖 Task 10 / Task 8（执行器依赖编译器与基础策略钩子）
- Task 12 依赖 Task 11（Engine 集成依赖 ComposableStrategy）
- Task 13 依赖 Task 9 / Task 12（API 依赖校验器与数据模型）
- Task 14 依赖 Task 10（Dry-Run 依赖编译器）
- Task 15 依赖 Task 13 / Task 14（端到端依赖全部上游）
- Task 16 依赖 Task 15（P1 扩展在 P0 端到端验证通过后进行）

可并行：Task 4 / Task 5 / Task 6 / Task 7 在 Task 3 完成后可并行开发。
