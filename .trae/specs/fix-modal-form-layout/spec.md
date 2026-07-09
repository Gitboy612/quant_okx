# 新增弹窗布局重构 Spec

## Why
`/strategies`（新建策略、自定义模板）和 `/accounts`（添加账户）的新增弹窗当前存在两个问题：
1. `Modal.tsx` 在面板上设置了 `maxHeight: 85vh`，并在 body 上使用 `overflow-y-auto`，导致表单内容稍多就出现垂直滚动条，违背表单一屏可见的预期。
2. `StrategiesPage` 的 `NewTemplateModal` 内层又套了一个 `max-h-[70vh] overflow-y-auto`，造成双重滚动容器，且与外层 `85vh` 限制叠加使布局错乱、视觉上未居中。

`Modal` 容器本身已使用 `flex items-center justify-center` 做了水平+垂直居中，滚动条出现时挤压内容宽度、且面板高度被锁定在 85vh，导致整体观感"未居中"。根本解法是让这两个表单不出现滚动条：通过新增 `scrollable` 开关关闭 Modal 的滚动兜底，同时压缩表单的纵向尺寸使其在常规视口内一屏可见。

## What Changes
- `Modal.tsx`：新增 `scrollable?: boolean` prop（默认 `true` 保持兼容）。当 `scrollable={false}` 时：
  - 移除面板 `maxHeight: 85vh` 限制
  - body 不再添加 `overflow-y-auto`，仅保留内边距
  - 面板 `overflow` 由 `hidden` 调整为可见区域裁剪，不产生滚动条
- `AccountsPage.tsx`：添加账户弹窗传入 `scrollable={false}`；表单从单列 `space-y-4` 改为双列紧凑布局（API Key / Secret Key 同行、Passphrase / 交易模式 同行），整体纵向高度下降
- `StrategiesPage.tsx`：
  - 新建策略弹窗传入 `scrollable={false}`；将"策略模板/绑定账户"、"策略名称/市场类型"改为双列布局，参数配置区保持 `sm:grid-cols-2`，整体压缩 `space-y-4` → `space-y-3`
  - `NewTemplateModal` 传入 `scrollable={false}`，并删除内层 `max-h-[70vh] overflow-y-auto pr-1` 双重滚动容器

## Impact
- Affected specs: `fix-responsive-layout`（前者引入了滚动兜底，本变更通过 prop 覆盖这两个表单的行为，不回滚全局规则）
- Affected code:
  - `frontend/src/components/Modal.tsx`
  - `frontend/src/pages/AccountsPage.tsx`
  - `frontend/src/pages/StrategiesPage.tsx`

## ADDED Requirements

### Requirement: Modal 可关闭滚动兜底
系统 SHALL 通过 `scrollable` prop 控制 Modal 是否启用垂直滚动兜底，默认启用以保持向后兼容。

#### Scenario: 关闭滚动
- **WHEN** 调用方传入 `scrollable={false}`
- **THEN** 面板不设置 `maxHeight` 限制
- **AND** body 容器不添加 `overflow-y-auto`
- **AND** 不出现垂直滚动条

#### Scenario: 默认行为保持
- **WHEN** 调用方未传入 `scrollable` 或传入 `true`
- **THEN** 面板维持 `maxHeight: 85vh`、body 维持 `overflow-y-auto`
- **AND** 其他已有弹窗行为不变

### Requirement: 新增弹窗表单一屏可见
`/strategies` 新建策略弹窗、`/accounts` 添加账户弹窗 SHALL 在常规桌面视口（≥720p）下不出现垂直滚动条，所有字段一屏可见。

#### Scenario: 添加账户弹窗
- **WHEN** 用户在 `/accounts` 打开"添加 OKX 账户"弹窗
- **THEN** 弹窗水平+垂直居中于视口
- **AND** 表单内容（账户名称、API Key、Secret Key、Passphrase、交易模式、提交按钮）全部可见
- **AND** 弹窗 body 不出现垂直滚动条

#### Scenario: 新建策略弹窗
- **WHEN** 用户在 `/strategies` 打开"新建策略"弹窗
- **THEN** 弹窗水平+垂直居中于视口
- **AND** 模板/账户/名称/市场类型/交易对/参数配置/提交按钮在常规参数数量下全部可见
- **AND** 弹窗 body 不出现垂直滚动条

#### Scenario: 自定义模板弹窗
- **WHEN** 用户在 `/strategies` 打开"创建自定义策略模板"弹窗
- **THEN** 弹窗水平+垂直居中于视口
- **AND** 不存在内层 `max-h-[70vh]` 二次滚动容器
- **AND** 弹窗 body 不出现垂直滚动条

### Requirement: 表单紧凑双列布局
为降低纵向高度，新增弹窗内的相关字段 SHALL 采用双列网格布局。

#### Scenario: 账户表单双列
- **WHEN** 渲染添加账户表单
- **THEN** API Key 与 Secret Key 位于同一行双列
- **AND** Passphrase 与交易模式位于同一行双列
- **AND** 账户名称（顶部）和提交按钮（底部）保持整行

#### Scenario: 新建策略表单双列
- **WHEN** 渲染新建策略表单
- **THEN** 策略模板与绑定账户位于同一行双列
- **AND** 策略名称与市场类型位于同一行双列
- **AND** 交易对搜索框保持整行（含下拉浮层）
- **AND** 参数配置区维持 `grid-cols-1 sm:grid-cols-2`

## MODIFIED Requirements
无。

## REMOVED Requirements
无。
