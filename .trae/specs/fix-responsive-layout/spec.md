# 全局响应式布局修复 + 弹窗溢出修复 Spec

## Why
策略管理界面的新建策略和自定义模板弹窗使用 `max-w-md`（448px）过窄，`grid-cols-2` 缺少 `min-w-0` 导致字段水平溢出出屏无法编辑；`Modal` 组件缺少垂直滚动和边距；`Dropdown` 的 `min-w-[120px]` 阻止窄屏收缩；侧边栏固定 260px 不适配窄屏；`body { overflow-x: hidden }` 隐藏了溢出症状但内容不可达。

## What Changes
- `Modal.tsx`：添加 `mx-4` 边距、`max-h-[85vh] overflow-y-auto` 垂直滚动兜底、`max-w-[calc(100vw-2rem)]` 防溢出
- `StrategiesPage.tsx`：新建策略和自定义模板弹窗均传 `wide` 属性（`max-w-2xl`）；参数定义 grid 添加 `min-w-0`；窄屏降级为 `grid-cols-1`
- `Dropdown.tsx`：移除 `min-w-[120px]` 硬限制，改为 `w-full`；选项面板添加 `max-h-60 overflow-y-auto`
- `Layout.tsx` + `Sidebar.tsx`：窄屏侧边栏收起为图标模式
- `index.css`：保留 `overflow-x: hidden` 但添加 `min-w-0` 到所有 flex/grid 子元素的全局规则

## Impact
- Affected specs: 无
- Affected code:
  - `components/Modal.tsx`
  - `components/Dropdown.tsx`
  - `components/Layout.tsx`
  - `components/Sidebar.tsx`
  - `pages/StrategiesPage.tsx`
  - `index.css`

## ADDED Requirements

### Requirement: 弹窗安全边距与滚动
系统 SHALL 确保所有弹窗在任何分辨率下不超出视口边界，且内容可垂直滚动。

#### Scenario: 窄屏弹窗
- **WHEN** 视口宽度小于弹窗 max-width
- **THEN** 弹窗两侧保留至少 1rem 边距
- **AND** 弹窗宽度不超过 `calc(100vw - 2rem)`

#### Scenario: 高内容弹窗
- **WHEN** 弹窗内容高度超过视口高度
- **THEN** 弹窗面板自身出现垂直滚动条
- **AND** 弹窗最大高度为 `85vh`

### Requirement: 策略弹窗加宽
系统 SHALL 使用宽弹窗（`max-w-2xl` = 672px）展示策略新建和自定义模板表单。

#### Scenario: 新建策略弹窗
- **WHEN** 用户打开新建策略弹窗
- **THEN** 弹窗宽度为 `max-w-2xl`
- **AND** 所有字段完整可见，不被截断

#### Scenario: 自定义模板弹窗
- **WHEN** 用户打开自定义模板弹窗
- **THEN** 弹窗宽度为 `max-w-2xl`
- **AND** 参数定义的 `grid-cols-2` 每列宽度足够编辑
- **AND** 窄屏（<640px）降级为单列布局

### Requirement: Grid 子元素防溢出
系统 SHALL 在所有 grid 和 flex 子元素上添加 `min-w-0`，防止内容撑破容器。

#### Scenario: 长文本输入
- **WHEN** grid 子元素中的 input 包含长文本（如 `0.000123456`）
- **THEN** input 内容可水平滚动或截断
- **AND** 不会将同行的其他列推出弹窗边界

### Requirement: Dropdown 自适应宽度
系统 SHALL 移除 Dropdown 触发按钮的 `min-w-[120px]` 硬限制，使其完全适应容器宽度。

#### Scenario: 窄容器中的 Dropdown
- **WHEN** Dropdown 放置在窄列（如 184px）中
- **THEN** Dropdown 按钮宽度等于容器宽度
- **AND** 选项列表同样不超出容器

#### Scenario: 多选项滚动
- **WHEN** Dropdown 选项超过 10 个
- **THEN** 选项面板出现垂直滚动条
- **AND** 最大高度为 240px

## MODIFIED Requirements
无。

## REMOVED Requirements
无。