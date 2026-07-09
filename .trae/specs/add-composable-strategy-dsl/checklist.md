# Checklist

## 语法框架设计自洽性

- [x] DSL 六类积木原语（BaseStrategy/Indicator/Condition/Event/Action/Rule）均有明确定义与示例
- [x] 用户示例（网格 + 单边行情暂停恢复）能完整表达为 DSL JSON 配置
- [x] DSL 顶层结构 `StrategyDSL` Pydantic 模型字段完整
- [x] `Trigger` 模型支持 condition / event / event+condition 三种触发模式
- [x] 统一积木形态 `{"kind", "args"}` 适用于所有积木类，便于前端递归渲染
- [x] 状态机执行模型清晰描述 RUNNING/PAUSED/REBALANCING 转换

## 语言选型合理性

- [x] 语言选型对比表覆盖至少 3 个候选（Python+Pydantic / Lark 文本 DSL / JS-TS / Lua 等）
- [x] 推荐方案（Python + Pydantic + JSON）给出充分理由并与现有后端技术栈一致
- [x] 文本 DSL 语法（Lark）作为二期可选方案明确标注非本 spec 范围

## 积木清单完整性（金融技术视角）

- [x] 指标库分 6 类（行情价格/技术指标/成交量/持仓账户/资金费率跨市场/策略状态）列出，每项标注 P0/P1/P2 优先级
- [x] 事件库分 6 类（行情/订单/持仓/账户/定时/策略生命周期）列出，kind 以 `on_` 前缀标识
- [x] 条件库分 6 类（比较/交叉/区间/趋势/逻辑/统计）列出
- [x] 动作库分 6 类（订单/持仓/策略控制/风控/通知/状态）列出
- [x] 基础策略库列出 grid/trend/arbitrage/advanced_grid_hedge 并标注 P0/P1/P2
- [x] 每个积木标注数据源（REST/WS/DB/STATE/CALC）便于评估实现成本
- [x] P0/P1/P2 分期汇总清晰，P0 集覆盖用户示例
- [x] 提供至少 5 个金融场景组合示例（单边暂停/保证金预警/RSI超买/资金费率套利/净值回撤保护）验证积木表达力

## 后端接口与类设计完整性

- [x] 新增目录结构 `backend/dsl/` 及子模块清晰，含 `events.py` 子模块
- [x] `Registry` 类与五个全局注册表（indicator/condition/action/event/base_strategy）定义
- [x] `@indicator` / `@condition` / `@action` / `@event` / `@base_strategy` 装饰器设计
- [x] `FSMCompiler` 将 Rule 编译为 transition 的逻辑描述，区分 event-trigger 与 condition-trigger
- [x] `ComposableStrategy` 继承 `BaseStrategy` 并作为 `_strategy_map["composable"]` 集成
- [x] `DSLValidator` 五层校验（结构/引用/类型/语义/资源）描述，含 Trigger mode 一致性校验
- [x] `DryRunner` 历史回放模拟器设计
- [x] `StrategyTemplate` 模型新增 `dsl_config` 字段（向后兼容）
- [x] REST API 三个端点（`GET /blocks` / `POST /validate` / `POST /dry-run`）定义

## 与现有架构兼容性

- [x] 现有四种硬编码策略（grid/trend/arbitrage/advanced_grid_hedge）继续工作，无需迁移
- [x] [strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py) 仅新增 `composable` 分发，不修改现有逻辑
- [x] [StrategyTemplate](file:///e:/New%20folder%20(2)/quant_okx/backend/models/strategy.py) 新增字段为 nullable，已有数据不受影响
- [x] BaseStrategy 增加的钩子方法默认空实现，不破坏现有子类

## P0 积木库最小可用集

- [x] 指标库 P0 至少包含：`price_last` / `price_change_pct` / `rsi` / `position_qty` / `position_pnl` / `account_equity` / `realized_pnl` / `unrealized_pnl`
- [x] 事件库 P0 至少包含：`on_tick` / `on_order_filled` / `on_margin_warning` / `on_interval` / `on_strategy_error`
- [x] 条件库 P0 至少包含：`gt` / `lt` / `abs_gt` / `abs_lt` / `and` / `or` / `not`
- [x] 动作库 P0 至少包含：`place_order` / `cancel_all` / `rebalance_position` / `hold_position` / `pause_orders` / `resume_orders` / `log_event`
- [x] 基础策略 P0 至少包含：`grid`
- [x] 每个积木声明 `param_schema` / `output_type` / `category` / `description` / `priority` 供前端展示

## 用户示例可验证性

- [x] 用户示例的 DSL JSON 配置完整出现在 spec 中（采用 Trigger 形态）
- [x] 用户示例的 FSM 编译产物（States + Transitions）伪表示完整
- [x] 用户示例的执行流程（RUNNING→PAUSED→REBALANCING→RUNNING）描述清晰

## 范围边界

- [x] 明确标注前端可视化编辑器不在本 spec 范围
- [x] 明确标注文本 DSL（Lark）解析器不在本 spec 范围
- [x] 明确标注 P1/P2 积木库扩展在后续 Task 16 实现，不阻塞 P0 上线
