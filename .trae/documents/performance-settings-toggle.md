# SettingsPage 性能模式开关

## 概述
性能模式的基础设施已完成（Provider、7个文件的响应逻辑），仅剩 SettingsPage.tsx 的开关 UI 未添加。

## 当前状态
- `usePerformanceMode.tsx` - 已完成，提供 `performanceMode` / `togglePerformanceMode`
- `main.tsx` - 已完成，Provider 包裹
- `VideoBackground.tsx` - 已完成，perf mode 下暂停视频 + 透明度归零
- `ClickRipple.tsx` - 已完成，perf mode 下返回 null
- `App.tsx` - 已完成，跳过 motion.div
- `index.css` - 已完成，`.performance-mode` 隐藏动画
- `BlockchainBackground.tsx` - 已完成，perf mode 下大幅降频

**未完成：** `SettingsPage.tsx` - 缺少性能模式开关 UI

## 修改方案

### 文件：`frontend/src/pages/SettingsPage.tsx`

#### 1. 添加 import（第 8 行后）
```typescript
import { usePerformanceMode } from '../hooks/usePerformanceMode'
```

#### 2. 在组件内解构 hook（现有 useState 附近，约第 50 行）
```typescript
const { performanceMode, togglePerformanceMode } = usePerformanceMode()
```

#### 3. 在"常规设置"面板中插入开关（第 257 行 `<div className="space-y-4">` 内部，刷新间隔之前）
复用代理手动开关的 toggle 样式（relative button + translate-x 圆点），保持 UI 一致性。

```tsx
<div className="flex items-center justify-between">
  <div>
    <label className="text-sm text-[#EDF0F7]">性能模式</label>
    <p className="text-xs text-[#7B86A2] mt-0.5">开启后降低动画和背景效果，提升操作流畅度</p>
  </div>
  <button
    onClick={togglePerformanceMode}
    className={`relative w-10 h-5 rounded-full transition-colors ${
      performanceMode ? 'bg-[#00D4AA]' : 'bg-[rgba(0,212,170,0.08)]'
    }`}
  >
    <span
      className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
        performanceMode ? 'translate-x-5' : ''
      }`}
    />
  </button>
</div>
```

## 验证
- `npx tsc --noEmit` 编译检查
- 开关切换后：背景视频暂停/播放、星空粒子减少、点击涟漪消失、页面切换无动画
