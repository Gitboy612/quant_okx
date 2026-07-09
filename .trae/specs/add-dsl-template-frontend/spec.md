# 前端策略管理接入 DSL 自定义模板 Spec

## Why

后端可拼接策略 DSL（积木式策略语言）已完整实现并通过 181 个测试，但前端策略管理页（[StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx)）尚未接入。当前"自定义模板"按钮（`NewTemplateModal`）只能定义参数字段（key/label/type/default），无法让投资人员通过"积木拼接"方式生成 `dsl_config`，DSL 能力对用户不可见。

需要让投资人员在前端通过可视化方式：选择基础策略 → 添加监测规则（when/then/recover_when/recover_then）→ 校验 → Dry-Run 预览 → 保存为 `strategy_type="composable"` 的模板 → 创建实例并启动。

## What Changes

- **修改**：后端 [routers/strategies.py](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/strategies.py) 的 `GET /templates` 和 `POST /templates` 响应增加 `dsl_config` 字段；`POST /templates` 创建时保存 `body.dsl_config` 到数据库；创建实例时把 `dsl_config` 注入 `params`（让 ComposableStrategy 能从 `self.params["dsl_config"]` 读取）
- **新增**：前端 `src/api/dsl.ts` 调用 `/api/dsl/blocks` / `/api/dsl/validate` / `/api/dsl/dry-run` 三个端点
- **新增**：前端 `src/types/dsl.ts` 定义 DSL 相关类型（BlockMeta / ValidationResult / DryRunResult / DslConfig 等）
- **新增**：前端 `src/components/DslEditor.tsx` 积木拼接编辑器组件
- **修改**：前端 [types/index.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/types/index.ts) 的 `StrategyTemplate` 增加 `dsl_config` 字段
- **修改**：前端 [api/strategies.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/api/strategies.ts) 的 `createTemplate` 增加 `dsl_config` 参数
- **修改**：前端 [StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx) 顶部新增"DSL 拼接模板"按钮，打开 DslEditor；创建实例时若模板含 `dsl_config`，自动设置 `strategy_type="composable"` 逻辑（实际由后端处理，前端只需把 dsl_config 透传）
- **不破坏**：现有"自定义模板"（参数定义式）按钮保留，DSL 拼接作为并列入口

## Impact

- 受影响代码：
  - 后端：[routers/strategies.py](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/strategies.py)（templates 接口补 dsl_config）
  - 前端：[StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx)、[types/index.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/types/index.ts)、[api/strategies.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/api/strategies.ts)
- 新增前端文件：`src/api/dsl.ts`、`src/types/dsl.ts`、`src/components/DslEditor.tsx`
- 依赖后端已实现的 DSL API（`/api/dsl/blocks` / `/api/dsl/validate` / `/api/dsl/dry-run`）和 `composable` 策略类型

## 设计原则

1. **沿用现有视觉风格**：深色背景 `#0C0C14` / `#14141A`，主色 `#00D4AA`，复用现有 `Modal` / `Dropdown` 组件
2. **积木清单动态拉取**：从 `/api/dsl/blocks` 获取，不硬编码；按 `category` 分组展示
3. **参数表单动态生成**：根据积木的 `param_schema` 自动渲染输入控件
4. **DSL 编辑器独立组件**：不污染 StrategiesPage，作为 Modal 打开
5. **校验前置**：保存模板前必须通过 `/api/dsl/validate`；Dry-Run 可选预览
6. **最小改动后端**：仅补 dsl_config 字段的读写，不重构现有 templates 接口

## ADDED Requirements

### Requirement: 后端 templates 接口暴露 dsl_config

系统 SHALL 在 `GET /api/strategies/templates` 和 `POST /api/strategies/templates` 的响应中包含 `dsl_config` 字段（`dict | null`），并在创建模板时把请求体的 `dsl_config` 持久化到数据库。

#### Scenario: 创建含 DSL 配置的模板
- **WHEN** 前端调用 `POST /api/strategies/templates` 传入 `{name, strategy_type:"composable", default_params, param_schema, dsl_config}`
- **THEN** 后端把 `dsl_config` 存入 `StrategyTemplate.dsl_config` 列
- **AND** 响应体含 `dsl_config` 字段

#### Scenario: 列出模板返回 dsl_config
- **WHEN** 前端调用 `GET /api/strategies/templates`
- **THEN** 每个模板对象含 `dsl_config` 字段（无 DSL 配置的模板该字段为 null）

### Requirement: 创建实例时注入 dsl_config

系统 SHALL 在创建策略实例时，若模板含 `dsl_config`，把它合并到实例 `params["dsl_config"]`，使 ComposableStrategy 能从 `self.params["dsl_config"]` 读取。

#### Scenario: 从 DSL 模板创建实例
- **WHEN** 前端用含 `dsl_config` 的模板创建实例
- **THEN** 后端创建的 `StrategyInstance.params` 含 `dsl_config` 键
- **AND** 启动该实例时 `ComposableStrategy.execute()` 能正确读取并编译 DSL

### Requirement: 前端 DSL 积木拼接编辑器

系统 SHALL 提供可视化 DSL 编辑器组件 `DslEditor`，让投资人员通过表单拼接积木生成 `dsl_config`：

1. **基础策略区**：下拉选择基础策略 `kind`（从 `base_strategies` 清单），动态渲染其参数表单
2. **规则列表区**：可增删改多条规则，每条规则含：
   - `name`：规则名输入框
   - `when`：触发器（mode 切换 condition/event + 积木选择 + extra_condition 可选）
   - `then`：动作列表（可增删，每个动作选 kind + 填 args）
   - `recover_when`：可选恢复触发器（同 when 结构）
   - `recover_then`：可选恢复动作列表
   - `cool_down_seconds`：冷却时间输入框
3. **校验按钮**：调用 `POST /api/dsl/validate`，展示错误列表（含 layer/code/message/path）
4. **Dry-Run 预览按钮**：调用 `POST /api/dsl/dry-run`，展示时间轴摘要（总步数/触发次数/状态转换次数/最终状态）
5. **保存按钮**：校验通过后调用 `createTemplate` 保存为 `strategy_type="composable"` 的模板

#### Scenario: 投资人员拼接用户示例
- **WHEN** 投资人员在 DslEditor 中选择基础策略 `grid`，填入 upper_price/lower_price/grid_count/order_qty/symbol
- **AND** 添加规则 `单边上涨暂停`，when 选 condition `gt(price_change_pct(window=1h, symbol=BTC-USDT), 0.05)`，then 选 `pause_orders + hold_position + log_event`
- **AND** recover_when 选 `abs_lt(price_change_pct(window=1h, symbol=BTC-USDT), 0.05)`，recover_then 选 `rebalance_position(to_theoretical) + resume_orders`
- **AND** 点击校验，返回 valid=true
- **AND** 点击保存，模板创建成功
- **THEN** 模板列表出现新模板，`dsl_config` 字段非空
- **AND** 用该模板创建实例并启动，策略按 FSM 逻辑运行

### Requirement: StrategiesPage 接入 DSL 入口

系统 SHALL 在 [StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx) 顶部按钮区新增"DSL 拼接模板"按钮，与现有"自定义模板"并列。点击打开 DslEditor Modal。

#### Scenario: 用户进入 DSL 拼接流程
- **WHEN** 用户点击"DSL 拼接模板"按钮
- **THEN** 打开 DslEditor Modal
- **AND** 编辑器初始为空配置（默认基础策略 grid + 空规则列表）

## DSL 编辑器交互细节

### 积木选择控件

每个积木槽位（indicator / condition / action / event）的编辑器结构：

```
[积木下拉选择（按 category 分组）] [参数表单（根据 param_schema 动态生成）]
```

- 积木下拉用现有 `Dropdown` 组件，options 按 category 分组（用 optgroup 或分组 label）
- 选中积木后，根据其 `param_schema` 动态渲染参数输入控件
- `param_schema` 字段格式（后端返回）：`{param_name: {type, required, default, min, max, description, ...}}`
- 参数类型映射：`string` → 文本框、`number` → 数字框、`bool` → 开关、`select` → 下拉
- 嵌套引用：condition 的 `args.indicator` 是 IndicatorRef，点击"选择指标"打开嵌套积木选择器

### 规则列表交互

- 每条规则为一个可折叠卡片（默认展开）
- 卡片头部显示规则名 + 触发条件摘要
- 卡片含"删除规则"按钮
- 列表底部"添加规则"按钮

### 校验与错误展示

- 点击"校验配置"按钮调用 `/api/dsl/validate`
- 校验通过：显示绿色"校验通过"提示
- 校验失败：在编辑器底部显示错误列表，每条含 layer 标签 + message + path
- 点击错误项可跳转到对应规则（高亮）

### Dry-Run 预览

- 点击"Dry-Run 预览"按钮调用 `/api/dsl/dry-run`
- 展示摘要卡片：总步数、触发次数、状态转换次数、最终状态
- 可展开查看时间轴（每步：时间、价格、状态、是否触发、动作列表）
- Dry-Run 是可选步骤，不阻塞保存

## 范围说明

本 spec 仅覆盖**前端策略管理接入 DSL 自定义模板功能**。以下不在本 spec 范围：

- DSL 引擎本身（已在 `add-composable-strategy-dsl` spec 完成）
- 前端可视化拖拽编辑器（节点连线式 UI，本 spec 用表单拼接，足够覆盖用户示例）
- 文本 DSL 语法编辑器（Lark，二期）
- P1/P2 积木库扩展（Task 16，后续）
