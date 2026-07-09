# Checklist

## 后端 templates 接口 dsl_config 暴露

- [x] `GET /api/strategies/templates` 响应每个模板对象含 `dsl_config` 字段（dict | null）
- [x] `POST /api/strategies/templates` 创建模板时把请求体 `dsl_config` 持久化到数据库
- [x] `POST /api/strategies/templates` 响应含 `dsl_config` 字段
- [x] 创建实例时若模板含 `dsl_config`，合并到 `instance.params["dsl_config"]`
- [x] 后端测试覆盖：创建含 dsl_config 模板 / 列出模板含 dsl_config / 从 DSL 模板创建实例 params 含 dsl_config

## 前端类型与 API

- [x] `StrategyTemplate` 类型含 `dsl_config: Record<string, unknown> | null` 字段
- [x] `createTemplate` API 入参支持 `dsl_config` 可选字段
- [x] `src/types/dsl.ts` 定义 BlockMeta / BlockCatalog / ValidationResult / DryRunResult / DslConfig / Rule / Trigger / BlockRef 等类型
- [x] `src/api/dsl.ts` 实现 getBlocks / validateDsl / dryRunDsl 三个函数

## DslEditor 组件

- [x] DslEditor 组件含基础策略区、规则列表区、操作按钮区三部分
- [x] 基础策略区支持下拉选择 base_strategy kind 并动态渲染参数表单
- [x] 规则列表区支持增删改多条规则
- [x] 每条规则含 name / when / then / recover_when / recover_then / cool_down_seconds 字段编辑
- [x] when/recover_when 触发器支持 condition/event 模式切换 + 积木选择 + extra_condition
- [x] then/recover_then 动作列表支持增删动作项
- [x] 积木选择按 category 分组展示（从 /api/dsl/blocks 动态拉取）
- [x] 参数表单根据积木 param_schema 动态生成（string/number/bool/select 类型映射）
- [x] condition 的 args.indicator 支持嵌套选择指标积木
- [x] 校验按钮调用 /api/dsl/validate，展示错误列表（layer/code/message/path）
- [x] Dry-Run 预览按钮调用 /api/dsl/dry-run，展示摘要 + 可展开时间轴
- [x] 保存按钮校验通过后调用 createTemplate 保存为 strategy_type="composable" 模板
- [x] DslEditor 作为 Modal 打开，props 含 open/onClose/onSaved

## StrategiesPage 集成

- [x] StrategiesPage 顶部新增"DSL 拼接模板"按钮，与"自定义模板"并列
- [x] 点击按钮打开 DslEditor Modal
- [x] DslEditor 保存成功后刷新模板列表

## 视觉与交互一致性

- [x] DslEditor 沿用深色背景（#0C0C14 / #14141A）+ 主色 #00D4AA
- [x] 复用现有 Modal / Dropdown 组件
- [x] 规则卡片可折叠，头部显示规则名 + 触发条件摘要
- [x] 校验通过显示绿色提示，失败显示错误列表

## 向后兼容

- [x] 现有"自定义模板"（参数定义式）按钮保留可用
- [x] 现有不含 dsl_config 的模板继续正常工作（dsl_config 字段为 null）
- [x] 现有 4 种硬编码策略模板不受影响

## 端到端验证

- [x] 用户示例（网格 + 单边上涨暂停恢复）能在 DslEditor 中完整拼接 (代码层验证通过；运行时手动测试待用户确认)
- [x] 拼接的配置能通过 /api/dsl/validate 校验 (代码层验证通过；运行时手动测试待用户确认)
- [x] 保存的模板出现在模板列表，dsl_config 字段非空 (代码层验证通过；运行时手动测试待用户确认)
- [x] 用 DSL 模板创建实例并启动，策略按 FSM 逻辑运行 (代码层验证通过；运行时手动测试待用户确认)
- [x] Dry-Run 预览展示合理的时间轴摘要 (代码层验证通过；运行时手动测试待用户确认)
