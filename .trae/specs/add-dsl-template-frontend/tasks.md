# Tasks

## 阶段一：后端补丁（暴露 dsl_config）

- [x] Task 1: 后端 templates 接口暴露并保存 dsl_config
  - [x] SubTask 1.1: [routers/strategies.py](file:///e:/New%20folder%20(2)/quant_okx/backend/routers/strategies.py) 的 `GET /templates` 响应增加 `dsl_config` 字段
  - [x] SubTask 1.2: `POST /templates` 创建 `StrategyTemplate` 时保存 `body.dsl_config` 到数据库
  - [x] SubTask 1.3: `POST /templates` 响应增加 `dsl_config` 字段
  - [x] SubTask 1.4: 创建实例（`POST /instances`）时，若模板含 `dsl_config`，把它合并到 `instance.params["dsl_config"]`（参考 [strategy_engine.py](file:///e:/New%20folder%20(2)/quant_okx/backend/services/strategy_engine.py) 已有的合并逻辑，确认 routers/strategies.py 的 create_instance 是否也需要补）
  - [x] SubTask 1.5: 编写测试 `backend/tests/test_dsl_template_api.py` 覆盖：创建含 dsl_config 的模板、列出模板含 dsl_config、从 DSL 模板创建实例 params 含 dsl_config

## 阶段二：前端类型与 API

- [x] Task 2: 前端类型扩展与 DSL API 模块
  - [x] SubTask 2.1: [types/index.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/types/index.ts) 的 `StrategyTemplate` 增加 `dsl_config: Record<string, unknown> | null` 字段
  - [x] SubTask 2.2: [api/strategies.ts](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/api/strategies.ts) 的 `createTemplate` 入参增加 `dsl_config?: Record<string, unknown>` 字段
  - [x] SubTask 2.3: 新增 `src/types/dsl.ts` 定义类型：`BlockMeta` / `BlockCatalog` / `ValidationResult` / `ValidationError` / `DryRunStep` / `DryRunResult` / `DslConfig` / `Rule` / `Trigger` / `BlockRef`
  - [x] SubTask 2.4: 新增 `src/api/dsl.ts` 实现三个函数：`getBlocks()` 调用 `GET /api/dsl/blocks`、`validateDsl(config)` 调用 `POST /api/dsl/validate`、`dryRunDsl(request)` 调用 `POST /api/dsl/dry-run`

## 阶段三：DSL 编辑器组件

- [x] Task 3: 实现 DslEditor 组件（积木拼接界面）
  - [x] SubTask 3.1: 创建 `src/components/DslEditor.tsx` 主组件骨架，含三个区域：基础策略区、规则列表区、操作按钮区（校验/Dry-Run/保存）
  - [x] SubTask 3.2: 实现积木选择子组件 `BlockPicker`（从 BlockCatalog 按 category 分组下拉选择 kind）和参数表单子组件 `BlockArgsForm`（根据 param_schema 动态渲染输入控件）
  - [x] SubTask 3.3: 实现基础策略区：用 BlockPicker 选 base_strategy kind，用 BlockArgsForm 填参数
  - [x] SubTask 3.4: 实现规则列表区：每条规则为可折叠卡片，含 name/when/then/recover_when/recover_then/cool_down_seconds 字段编辑
  - [x] SubTask 3.5: 实现 when/recover_when 触发器编辑：mode 切换（condition/event）+ 对应积木选择（condition 用 BlockPicker 嵌套 indicator 选择；event 用 BlockPicker）+ 可选 extra_condition
  - [x] SubTask 3.6: 实现 then/recover_then 动作列表：可增删动作项，每项用 BlockPicker 选 action kind + BlockArgsForm 填参数
  - [x] SubTask 3.7: 实现校验按钮：调用 validateDsl，展示错误列表（含 layer/code/message/path），校验通过显示绿色提示
  - [x] SubTask 3.8: 实现 Dry-Run 预览按钮：调用 dryRunDsl，展示摘要卡片（总步数/触发次数/状态转换次数/最终状态）+ 可展开时间轴
  - [x] SubTask 3.9: 实现保存按钮：校验通过后调用 createTemplate 保存为 strategy_type="composable" 的模板，含 dsl_config
  - [x] SubTask 3.10: 组件 props 设计：`open: boolean` / `onClose: () => void` / `onSaved: () => void`，复用现有 Modal 组件作为容器

## 阶段四：StrategiesPage 集成

- [x] Task 4: StrategiesPage 接入 DSL 编辑器入口
  - [x] SubTask 4.1: [StrategiesPage.tsx](file:///e:/New%20folder%20(2)/quant_okx/frontend/src/pages/StrategiesPage.tsx) 顶部按钮区新增"DSL 拼接模板"按钮（与"自定义模板"并列，用 `Blocks` 图标）
  - [x] SubTask 4.2: 新增 `showDslEditor` state，点击按钮打开 DslEditor Modal
  - [x] SubTask 4.3: DslEditor 的 onSaved 回调调用 loadData 刷新模板列表

## 阶段五：端到端验证

- [x] Task 5: 端到端验证用户示例
  - [x] SubTask 5.1: 启动前后端，手动验证：点击"DSL 拼接模板"→ 选择 grid → 填参数 → 添加规则（单边上涨暂停）→ 校验通过 → 保存模板
  - [x] SubTask 5.2: 验证：用保存的 DSL 模板创建实例 → 启动 → 观察 FSM 状态转换日志
  - [x] SubTask 5.3: 验证：Dry-Run 预览展示合理的时间轴摘要

# Task Dependencies

- Task 1（后端补丁）无依赖，可立即开始
- Task 2（前端类型/API）无依赖，可与 Task 1 并行
- Task 3（DslEditor 组件）依赖 Task 2（需要类型和 API 模块）
- Task 4（StrategiesPage 集成）依赖 Task 3（需要 DslEditor 组件）
- Task 5（端到端验证）依赖 Task 1 / Task 4

可并行：Task 1 与 Task 2 可并行开发。
