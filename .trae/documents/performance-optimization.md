# 性能优化计划 — 设置页面添加性能模式开关

## 方案

在系统设置页面添加「性能模式」开关，开启后降低所有动画效果开销。所有视觉效果保留，但通过一个全局 Context 控制渲染强度。

## 实现步骤

### 1. 新建 `hooks/usePerformanceMode.tsx`

- `PerformanceModeProvider`：管理 `performanceMode: boolean` 状态
- 默认 `false`（全部效果开启）
- 持久化到 `localStorage`（刷新后保持用户选择）
- 暴露 `usePerformanceMode()` → `{ performanceMode, togglePerformanceMode }`

### 2. 修改 `src/components/VideoBackground.tsx`

- 读取 `usePerformanceMode()`
- 性能模式开启时：`video.pause()` + 显示纯色背景
- 关闭时：`video.play()` + 正常显示
- 用 `useEffect` 监听 `performanceMode` 变化

### 3. 修改 `src/components/BlockchainBackground.tsx`

- 读取 `usePerformanceMode()`
- 性能模式开启时：
  - 星星 600 → 100，不绘制 twinkle
  - dots 25 → 5
  - 代币间连线阈值 280 → 150
  - Canvas `style={{ opacity: 0.5 }}`（进一步降低）
  - 不绘制连线上的数据包动画
  - 不绘制代币脉冲光环
  - 不绘制代币 glow（只保留圆形 + 图标）
- 关闭时：全部恢复原始数量

### 4. 修改 `src/components/ClickRipple.tsx`

- 读取 `usePerformanceMode()`
- 性能模式开启时：移除全局 click 监听 + 停止 rAF 循环（完全不渲染）
- 关闭时：恢复

### 5. 修改 `src/App.tsx`

- 读取 `usePerformanceMode()`
- 性能模式开启时：`PageCard` 不添加动画 variants（直接渲染 children，无 Framer Motion 包装）
- 关闭时：正常 3D 卡片动画

### 6. 修改 `src/index.css`

- 添加 `.performance-mode` CSS class
- `.performance-mode .scan-line::before` → `display: none`
- `.performance-mode .cinema-beams` → `display: none`
- `.performance-mode .cinema-particles` → `display: none`

### 7. 修改 `src/main.tsx`

- 用 `PerformanceModeProvider` 包裹最外层
- 根据 `performanceMode` 在 `<html>` 或 `<body>` 上添加/移除 `.performance-mode` class

### 8. 修改 `src/pages/SettingsPage.tsx`

- 在「常规设置」面板顶部添加性能模式开关（toggle switch）
- 开关说明：「开启后降低动画和背景效果，提升操作流畅度」
- 使用 `usePerformanceMode()` 的 `togglePerformanceMode`

## 文件变更清单

| 文件 | 操作 |
|------|------|
| `src/hooks/usePerformanceMode.tsx` | **新建** |
| `src/main.tsx` | 添加 Provider + 动态 class |
| `src/components/VideoBackground.tsx` | 响应性能模式 |
| `src/components/BlockchainBackground.tsx` | 响应性能模式 |
| `src/components/ClickRipple.tsx` | 响应性能模式 |
| `src/App.tsx` | 响应性能模式 |
| `src/index.css` | 添加 .performance-mode 规则 |
| `src/pages/SettingsPage.tsx` | 添加性能模式开关 UI |

## 验证
- TypeScript 编译零错误
- 性能模式关闭：所有效果正常运行
- 性能模式开启：视频暂停、星空减少、涟漪消失、CSS 动画停止
- 刷新页面后性能模式设置保持（localStorage）
- 设置页开关 UI 正常
