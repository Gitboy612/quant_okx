# Q-Studio 整体布局检查与优化方案

## 概述

对 Q-Studio 量化交易平台前端（React + Tailwind + Framer Motion）进行系统性布局检查和修复，解决 5 个具体 UI 问题，同时从全局和局部两个层面确保系统在不同分辨率下的一致性和可用性。

## 当前状态分析

**技术栈**: React 18 + TypeScript + Tailwind CSS v4 + Framer Motion + Recharts + Vite
**布局结构**: 固定左侧边栏(260px) + 顶栏(48px) + 主内容区(flex-1 overflow-y-auto)
**主题**: 深色太空主题，主色 `#00D4AA`，背景 `#050711`

### 问题 1: 登录页输入框位置偏上
- **文件**: `LoginPage.tsx` (L276)
- **现状**: 使用 `min-h-screen flex items-center justify-center`，理论上是居中的，但从截图看整体偏上
- **根因**: Logo 区域（3D Logo + 标题）高度过大，而外层容器仅使用 `min-h-screen`，当内容高度接近视口高度时，flex 居中的效果会被挤压，导致视觉上偏上
- **修复方向**: 将外层改为 `h-screen` 而非 `min-h-screen`，并确保 Logo + 表单 + footer 的总高度合理；给 form 容器增加 `my-auto` 或调整 padding 使其视觉居中

### 问题 2: 策略管理新建策略弹窗显示不全（最严重）
- **文件**: `StrategiesPage.tsx` (L479 Modal), `Modal.tsx`
- **现状**: Modal 使用 `max-h-[85vh] overflow-y-auto`，但 `wide` 模式下 `max-w-2xl`（672px）内容过多时，参数配置区域（grid-cols-2 + max-h-60 overflow-y-auto）加上交易对搜索下拉列表叠加后超出可视区域
- **根因**:
  1. Modal 的 `max-h-[85vh]` 和内部 `max-h-60` 参数滚动区没有协调好，当参数很多时（如网格策略有 5+ 个参数），内容溢出
  2. `Modal.tsx` L42 中同时设置了 `max-w-2xl` 和 `max-w-[calc(100vw-2rem)]`，后者被前者覆盖（Tailwind 中后面的 max-w 会覆盖前面的）
  3. 交易对下拉（`max-h-60`）是在 Modal 内部绝对定位展开的，如果 Modal 有 `overflow-y-auto`，下拉会被截断
- **修复方向**:
  1. Modal 组件：修复 max-w 冲突，将 `overflow-y-auto` 改为更精细的控制——header 固定、内容区滚动
  2. 新建策略弹窗：将参数配置区域从固定 `max-h-60` 改为弹性高度，使用 `overflow-y-auto` 配合 `flex-shrink-0`
  3. 交易对搜索下拉需要 portal 化或确保不被 Modal 的 overflow 截断

### 问题 3: 仪表盘盈亏曲线
- **文件**: `DashboardPage.tsx` (L285-297), `PnLChart.tsx`
- **需求变更**:
  1. 时间选项：移除 5分、30分，改为：1小时、1天、1周、1月、全部（共 5 个）
  2. 默认选中"全部"
  3. 选中时间即渲染从当前时间往前推该时段的数据
  4. Tooltip 中不显示 "pnl"，改为 "盈利 XXX" 或 "亏损 XXX"
- **修复方向**:
  1. `PnLChart.tsx`: 修改 `TimeRange` 类型，更新 `TIME_RANGE_DURATIONS`，新增 `1h` 和 `1mo`
  2. `DashboardPage.tsx`: 更新按钮渲染逻辑，默认值改为 `'all'`
  3. `PnLChart.tsx`: 自定义 Tooltip 的 `formatter`，根据 pnl 正负显示"盈利/亏损"

### 问题 4: 账户切换层级问题
- **文件**: `TopBar.tsx` (L32-36), `Dropdown.tsx`
- **现状**: 账户 Dropdown 在 TopBar 内部，TopBar 的 z-index 为 `z-10`，侧边栏为 `z-30`。Dropdown 展开时 `z-50`，但截图显示下拉列表被部分遮挡或层级不正确
- **根因**: TopBar 的 `relative z-10` 可能导致 Dropdown 的 `z-50` 在 stacking context 中受限（父级 z-10 创建了新的 stacking context，子级的 z-50 仅在该 context 内有效）
- **修复方向**: 将 TopBar 的 z-index 提高，或让 Dropdown 使用 portal 渲染到 body

### 问题 5: 账户管理新增账户弹窗布局
- **文件**: `AccountsPage.tsx` (L125-170), `Modal.tsx`
- **现状**: 使用 `Modal wide`，表单字段 5 个 + 提示文字 + 按钮。从截图看布局偏紧，可能存在 padding 不足或字段间距不均匀的问题
- **修复方向**: 优化表单间距，确保 Modal 内容区域的 padding 和 spacing 一致

## 全局优化项

### 响应式布局
1. **Layout.tsx**: 侧边栏 260px 在小屏幕下应可折叠或响应式收缩
2. **主内容区**: 确保 `p-6` 在不同分辨率下合理
3. **Modal**: 在小屏幕下应全屏或接近全屏

### 统一性检查
1. 所有 Modal 使用统一的 padding、spacing、max-width 规范
2. 所有表单字段使用统一的 label 样式和 input 样式
3. Dropdown 组件在所有使用场景下层级一致

## 具体修改计划

### 1. `frontend/src/pages/LoginPage.tsx`
- 将外层容器从 `min-h-screen` 改为 `h-screen`，确保内容始终垂直居中
- 给 Logo 区域和表单区域之间增加弹性间距，使整体在任何视口高度下都居中

### 2. `frontend/src/components/Modal.tsx` (全局组件)
- 修复 max-w 冲突：移除重复的 `max-w-[calc(100vw-2rem)]`，改用 `mx-4` + 正确的 max-w
- 将 Modal 结构改为 header 固定 + body 滚动，避免 header 被滚动隐藏
- 增加 `overflow: visible` 给内容区（或使用 portal 给内部 dropdown）

### 3. `frontend/src/pages/StrategiesPage.tsx`
- 新建策略弹窗内容优化：参数区域高度弹性化，移除 `max-h-60` 限制改为 `flex-1 overflow-y-auto`
- 交易对下拉确保不被 Modal overflow 截断

### 4. `frontend/src/components/PnLChart.tsx`
- `TimeRange` 类型改为 `'1h' | '1d' | '1w' | '1mo' | 'all'`
- 更新 `TIME_RANGE_DURATIONS`：新增 1h (3600000) 和 1mo (30天)
- 自定义 Tooltip formatter：pnl >= 0 显示"盈利 $X.XX"，否则显示"亏损 $X.XX"

### 5. `frontend/src/pages/DashboardPage.tsx`
- 时间按钮更新：移除 5分/30分，改为 1小时/1天/1周/1月/全部
- 默认 timeRange 改为 `'all'`

### 6. `frontend/src/components/TopBar.tsx` + `frontend/src/components/Dropdown.tsx`
- TopBar z-index 从 `z-10` 提高到 `z-20`
- 或者在 Dropdown 组件中添加 portal 支持，确保下拉始终在最高层级

### 7. `frontend/src/pages/AccountsPage.tsx`
- 优化新增账户弹窗表单间距
- 统一与 Modal 改造后的样式

### 8. `frontend/src/index.css` (全局样式)
- 检查并确保所有 Modal 内容在不同分辨率下有合理的 max-height 和 overflow 行为

## 实施顺序

1. 先修改 `Modal.tsx`（全局组件，影响所有弹窗）
2. 修改 `PnLChart.tsx`（功能变更）
3. 修改 `DashboardPage.tsx`（功能变更 + 布局）
4. 修改 `StrategiesPage.tsx`（修复最严重的弹窗问题）
5. 修改 `TopBar.tsx` / `Dropdown.tsx`（修复层级问题）
6. 修改 `LoginPage.tsx`（居中问题）
7. 修改 `AccountsPage.tsx`（弹窗布局优化）
8. 全局 CSS 检查

## 验证步骤

1. 在 1920x1080、1366x768、1280x720 三个分辨率下逐页检查
2. 登录页：输入框在任意分辨率下垂直居中
3. 策略管理：新建策略弹窗完整显示所有字段，参数多时可滚动
4. 仪表盘：盈亏曲线时间选项正确，tooltip 显示中文盈亏
5. 账户切换：下拉不被遮挡
6. 账户管理：新增账户弹窗布局整齐
