# Tasks

## 阶段一：后端 QS-Model 结构与积木元数据中文化

- [x] Task 1: 实现 QS-Model Pydantic 模型（`backend/dsl/schema.py`）
  - [x] SubTask 1.1: 定义 `StrategyMeta`（name/version/author/description/asset_class/frequency/base_symbol）
  - [x] SubTask 1.2: 定义 `ParamDefinition`（label/value/type/range/description/options/option_labels/unit）
  - [x] SubTask 1.3: 定义 `QSModelConfig`（qs_model_version/meta/params/logic/risk_filter），`logic` 字段复用现有 `StrategyDSL`
  - [x] SubTask 1.4: 实现变量引用解析函数 `resolve_variables(qs_model)`：将 `$params.xxx` / `$meta.xxx` 替换为实际值
  - [x] SubTask 1.5: 编写测试验证序列化/反序列化与变量引用解析

- [x] Task 2: 扩展积木元数据——为所有积木补 `label` 字段（`backend/dsl/blocks/`）
  - [x] SubTask 2.1: [indicators.py](file:///e:/quant_okx/backend/dsl/blocks/indicators.py) 8 个 P0 指标增加 `label`（如 position_pnl→"持仓盈亏"、price_change_pct→"涨跌幅"、rsi→"RSI"）
  - [x] SubTask 2.2: [conditions.py](file:///e:/quant_okx/backend/dsl/blocks/conditions.py) 7 个 P0 条件增加 `label` + `display_template`（如 gt→"大于"，display_template="{indicator} 大于 {threshold}"）
  - [x] SubTask 2.3: [actions.py](file:///e:/quant_okx/backend/dsl/blocks/actions.py) 7 个 P0 动作增加 `label`（如 place_order→"下单"、pause_orders→"暂停挂单"）
  - [x] SubTask 2.4: [events.py](file:///e:/quant_okx/backend/dsl/blocks/events.py) 5 个 P0 事件增加 `label`（如 on_tick→"行情更新"、on_order_filled→"订单成交"）

- [x] Task 3: 扩展积木 param_schema——枚举字段改 `select` + 时间窗口下拉（`backend/dsl/blocks/`）
  - [x] SubTask 3.1: indicators 中 `symbol` 参数增加 `label="交易对"`；`window` 参数改为 `type=select` + options=[1m/5m/15m/1h/4h/1d] + option_labels=[1分钟/5分钟/15分钟/1小时/4小时/1天]；`period` 增加 `label`
  - [x] SubTask 3.2: actions 中 `place_order` 的 `side` 改 select（options=[buy/sell], labels=[买入/卖出]）、`type` 改 select（options=[market/limit], labels=[市价/限价]）；`rebalance_position` 的 `mode` 改 select；`log_event` 的 `level` 改 select
  - [x] SubTask 3.3: events 中 `on_margin_warning` 的 `threshold` 增加 `unit="保证金率"`；`on_interval` 的 `seconds` 增加 `unit="秒"` + `label`
  - [x] SubTask 3.4: bases 中 `grid` 的 `symbol` 增加 label，`grid_mode` 改 select，`direction` 改 select

- [x] Task 4: 扩展 Registry 与 API 输出（`backend/dsl/registry.py` + `backend/routers/dsl.py`）
  - [x] SubTask 4.1: `Registry.list()` 输出项增加 `label` / `display_template` 字段
  - [x] SubTask 4.2: 确认 `GET /api/dsl/blocks` 响应包含新增字段
  - [x] SubTask 4.3: 编写测试验证新字段输出

## 阶段二：基础策略库扩充

- [x] Task 5: 精简 `grid` 基础策略参数（`backend/dsl/blocks/bases.py`）
  - [x] SubTask 5.1: `order_qty` 改为可选，默认 0.001
  - [x] SubTask 5.2: 新增可选 `grid_mode`（select，默认 arithmetic）和 `direction`（select，默认 neutral）
  - [x] SubTask 5.3: 为所有参数补 `label`

- [x] Task 6: 新增 `trend` 基础策略（`backend/dsl/blocks/bases.py`）
  - [x] SubTask 6.1: 实现 `TrendBlock` 类，注册 `@base_strategy("trend")`，label="双均线趋势"
  - [x] SubTask 6.2: param_schema: fast_period(int,1-50,默认5)/slow_period(int,5-200,默认20)/direction(select)/symbol
  - [x] SubTask 6.3: 实现生命周期钩子 on_start/on_tick/on_pause/on_resume/on_stop（金叉做多/死叉做空逻辑）
  - [x] SubTask 6.4: 参考传统 [trend_strategy.py](file:///e:/quant_okx/backend/strategies/trend_strategy.py) 复用其核心计算逻辑

- [x] Task 7: 新增 `rsi_strategy` 基础策略
  - [x] SubTask 7.1: 实现 `RsiBlock`，注册 `@base_strategy("rsi_strategy")`，label="RSI 超买超卖"
  - [x] SubTask 7.2: param_schema: period(int,6-30,默认14)/oversold(int,10-45,默认30)/overbought(int,55-90,默认70)/direction(select)/symbol
  - [x] SubTask 7.3: 实现钩子（RSI<超卖线买入，RSI>超买线卖出）

- [x] Task 8: 新增 `bollinger_bands` / `donchian` 基础策略（可并行）
  - [x] SubTask 8.1: `BollingerBlock` label="布林带"，参数 period/std_multiplier/direction/symbol，触下轨买入触上轨卖出
  - [x] SubTask 8.2: `DonchianBlock` label="唐奇安通道"，参数 entry_period/exit_period/direction/symbol，突破入场反向离场

- [x] Task 9: 新增 `dca` / `martingale` 基础策略（可并行）
  - [x] SubTask 9.1: `DcaBlock` label="定投策略"，参数 amount/frequency(select:daily/weekly/monthly)/day_of_week/symbol，定时定额买入
  - [x] SubTask 9.2: `MartingaleBlock` label="马丁格尔"，参数 initial_size/multiplier/max_levels/direction(select)/symbol，亏损加倍加仓

## 阶段三：模板哈希与数据模型

- [x] Task 10: 数据模型扩展（`backend/models/strategy.py` + `backend/schemas/strategy.py`）
  - [x] SubTask 10.1: `StrategyTemplate` 增加 `qs_model_config = Column(JSON, nullable=True)` 和 `logic_hash = Column(String, nullable=True, index=True)`
  - [x] SubTask 10.2: `StrategyInstance` 增加 `logic_hash = Column(String, nullable=True)`
  - [x] SubTask 10.3: `StrategyTemplateCreate` 增加 `qs_model_config` 可选字段
  - [x] SubTask 10.4: 保留 `dsl_config` 字段向后兼容（读取时若 qs_model_config 为空但 dsl_config 非空，自动包装为 QS-Model）

- [x] Task 11: 模板创建与哈希计算（`backend/routers/strategies.py`）
  - [x] SubTask 11.1: `create_template` 中，若 `body.qs_model_config` 非空，计算 `logic` 段的 SHA-256 存入 `logic_hash`
  - [x] SubTask 11.2: `create_template` 返回前查询是否已有相同 `logic_hash` 的模板，若有则在响应中附加 `duplicate_hint` 字段提示前端
  - [x] SubTask 11.3: `create_instance` 时，若模板含 `logic_hash`，写入实例的 `logic_hash` 字段
  - [x] SubTask 11.4: 编写测试覆盖哈希计算、去重提示、实例 logic_hash 快照

## 阶段四：执行器适配 QS-Model

- [x] Task 12: ComposableStrategy 读取 QS-Model 配置（`backend/dsl/executor.py`）
  - [x] SubTask 12.1: `execute()` 优先从 `params["qs_model_config"]` 读取，回退到 `params["dsl_config"]`（兼容）
  - [x] SubTask 12.2: 调用 `resolve_variables(qs_model)` 解析变量引用，得到最终 `StrategyDSL`
  - [x] SubTask 12.3: 实例 `params` 覆盖模板 `params` 段的 value 后再解析
  - [x] SubTask 12.4: 编写测试验证 QS-Model 配置的端到端执行

## 阶段五：前端类型与 API 扩展

- [x] Task 13: 前端类型扩展（`frontend/src/types/dsl.ts`）
  - [x] SubTask 13.1: `BlockMeta` 增加 `label?: string` / `display_template?: string`
  - [x] SubTask 13.2: `BlockParamSchema` 增加 `label?: string` / `option_labels?: string[]` / `unit?: string`
  - [x] SubTask 13.3: 新增 `QSModelMeta` / `ParamDefinition` / `QSModelConfig` 类型
  - [x] SubTask 13.4: `StrategyTemplate` 类型增加 `qs_model_config?: QSModelConfig | null` / `logic_hash?: string | null`（[types/index.ts](file:///e:/quant_okx/frontend/src/types/index.ts)）

- [x] Task 14: 前端 API 扩展（`frontend/src/api/strategies.ts`）
  - [x] SubTask 14.1: `createTemplate` 入参增加 `qs_model_config?: QSModelConfig`
  - [x] SubTask 14.2: 响应处理增加 `duplicate_hint` 字段透传

## 阶段六：DslEditor 全面重构

- [x] Task 15: 组件改名与品牌更新
  - [x] SubTask 15.1: [StrategiesPage.tsx](file:///e:/quant_okx/frontend/src/pages/StrategiesPage.tsx) 按钮"DSL 拼接模板"→"QS-Model 策略构建"
  - [x] SubTask 15.2: [DslEditor.tsx](file:///e:/quant_okx/frontend/src/components/DslEditor.tsx) Modal 标题、组件注释统一改为 QS-Model

- [x] Task 16: 积木选择中文化（`DslEditor.tsx` 的 BlockPicker）
  - [x] SubTask 16.1: 下拉项展示 `label` 而非 `kind`（label 为空时回退到 kind）
  - [x] SubTask 16.2: 选中后头部按钮也展示 label
  - [x] SubTask 16.3: 嵌套指标选择器同样展示 label

- [x] Task 17: 参数表单按类型渲染（`DslEditor.tsx` 的 BlockArgsForm）
  - [x] SubTask 17.1: `select` 类型渲染自定义 Dropdown（非原生 select），展示 `option_labels`，值为 `options`
  - [x] SubTask 17.2: `number` 类型展示 `label` + `unit` 后缀，支持 min/max/step
  - [x] SubTask 17.3: `string` 类型展示 `label`，placeholder 用 description
  - [x] SubTask 17.4: symbol 参数特殊处理：渲染为交易对下拉搜索组件（Task 18）

- [x] Task 18: 交易对下拉搜索组件
  - [x] SubTask 18.1: 抽取 StrategiesPage 中已有的交易对预设列表+搜索逻辑为独立组件 `SymbolPicker`
  - [x] SubTask 18.2: BlockArgsForm 遇到参数名为 `symbol` 时渲染 `SymbolPicker`
  - [x] SubTask 18.3: 基础策略区的 symbol 也用 SymbolPicker

- [x] Task 19: 规则交易对自动继承
  - [x] SubTask 19.1: 规则编辑器中，指标/动作的 symbol 参数自动取基础策略的 symbol 值
  - [x] SubTask 19.2: 编辑器中 symbol 字段隐藏或显示为"继承基础策略交易对"只读提示
  - [x] SubTask 19.3: 保存时规则级 symbol 自动填入基础策略 symbol

- [x] Task 20: 条件可视化展示
  - [x] SubTask 20.1: 简单条件（gt/lt/abs_gt/abs_lt）渲染为"[指标label] [运算符中文] [阈值输入]"水平布局
  - [x] SubTask 20.2: 运算符下拉展示中文（大于/小于/绝对值大于/绝对值小于）
  - [x] SubTask 20.3: 规则卡片头部用 display_template 渲染人类可读摘要
  - [x] SubTask 20.4: 嵌套 and/or/not 条件支持分组可视化（条件列表 + 添加子条件按钮）

- [x] Task 21: QS-Model 四段式编辑界面
  - [x] SubTask 21.1: 主编辑器分为四区：META 区（名称/作者/描述/基准交易对/频率）、PARAMS 区（可变参数定义列表）、LOGIC 区（原基础策略+规则）、RISK_FILTER 区（可选风控）
  - [x] SubTask 21.2: PARAMS 区支持增删参数定义，每项含 label/value/type/range
  - [x] SubTask 21.3: LOGIC 区参数值支持引用 $params.xxx / $meta.base_symbol（下拉选择已定义的参数或字面量）
  - [x] SubTask 21.4: RISK_FILTER 区可折叠，含 max_position_ratio/daily_max_loss/min_trade_size

- [x] Task 22: 保存逻辑与哈希去重提示
  - [x] SubTask 22.1: 保存时组装 QS-Model 配置调用 createTemplate
  - [x] SubTask 22.2: 若响应含 duplicate_hint，弹窗提示"已有相同逻辑模板 XXX，是否仍要创建"
  - [x] SubTask 22.3: 用户确认后强制创建（附加 force=true 参数）

## 阶段七：端到端验证

- [x] Task 23: 端到端验证
  - [x] SubTask 23.1: 验证按钮文案已改为"QS-Model 策略构建"
  - [x] SubTask 23.2: 验证积木下拉展示中文 label，无 gt/lt/position_pnl 等代码字段暴露
  - [x] SubTask 23.3: 验证交易对为下拉搜索，规则级自动继承
  - [x] SubTask 23.4: 验证时间窗口为下拉选择，买卖方向为下拉
  - [x] SubTask 23.5: 验证条件展示为人类可读中文文案
  - [x] SubTask 23.6: 验证基础策略下拉含 7 种策略
  - [x] SubTask 23.7: 验证保存模板时计算 logic_hash，重复逻辑有提示
  - [x] SubTask 23.8: 验证基于 QS-Model 模板创建实例并启动，策略按 FSM 逻辑运行
  - [x] SubTask 23.9: 验证旧 dsl_config 模板仍可正常加载运行（兼容）

# Task Dependencies

- Task 1（QS-Model 模型）→ Task 12（执行器适配）→ Task 23（端到端）
- Task 2 / Task 3 / Task 4（积木元数据）可并行，依赖现有积木代码
- Task 5 / Task 6 / Task 7 / Task 8 / Task 9（基础策略扩充）可并行，依赖 Task 4（Registry 支持 label）
- Task 10 / Task 11（数据模型+哈希）依赖 Task 1（QS-Model 结构）
- Task 13 / Task 14（前端类型+API）依赖 Task 4（后端字段确定）
- Task 15-22（DslEditor 重构）依赖 Task 13（前端类型）
- Task 23（端到端）依赖全部上游

可并行：
- Task 2 / Task 3 / Task 4 后端积木元数据三件套
- Task 5-9 基础策略扩充（5 个策略可并行实现）
- Task 10 / Task 11 数据模型与哈希
- Task 15-22 前端各子任务（部分可并行，如 16/17/18 互不依赖）
