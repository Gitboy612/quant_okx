# Tasks

- [x] Task 1: 盈亏曲线时间模式调整与时间轴重构
  - [x] 在 `PnLChart.tsx` 中移除 `'1h'`，更新 `TimeRange` 类型为 `'24h' | '7d' | '30d' | 'all'`
  - [x] 重写窗口计算逻辑：24h=滚动`[now-24h, now]`；7d=`[今日-7 00:00, 今日24:00]`；30d=`[今日-30 00:00, 今日24:00]`；all=null（保持原逻辑）
  - [x] 实现桶生成：24h按时桶(24个)，7d/30d按日桶(8/31个)
  - [x] 实现数据填充算法：`lastValue=0`；按桶时间顺序遍历，桶内有记录则更新 `lastValue` 为最后记录的 total_pnl，桶值=`lastValue`（策略启动前=0，启动后间隙=沿用）
  - [x] X轴标签适配：24h显示"HH:00"，7d/30d显示"MM/DD"
  - [x] 全0数据时渲染0线占位，不再返回空状态
  - [x] "全部"模式保持现有过滤逻辑不变
  - [x] 保留数据点超过50个时水平滚动逻辑

- [x] Task 2: Dashboard时间模式按钮更新
  - [x] 在 `DashboardPage.tsx` 中更新按钮列表为 `['24h', '7d', '30d', 'all']`
  - [x] 更新按钮文字：过去24小时、过去7天、过去30天、全部
  - [x] 保持默认 `timeRange` 为 `'all'`

- [x] Task 3: 开场动画Logo统一与3D特效
  - [x] 在 `LoginPage.tsx` 的 `OpeningAnimation` 中，将Logo容器替换为 Logo3D 视觉语言（圆角18、深色渐变背景、青色边框、多层box-shadow、drop-shadow）
  - [x] 添加3D翻转入场：framer-motion `animate` rotateY -180°→0°，外层 `perspective: 800px`，配合 scale 与 opacity 过渡
  - [x] 添加灯光扫过：径向高光 div 沿Logo表面横向移动（新增 `@keyframes logo-light-sweep`）
  - [x] 在 `index.css` 中新增 logo 扫光 keyframe
  - [x] 保留影院光束/粒子/底部反射阴影/呼吸光晕背景
  - [x] 在 `.performance-mode` 下禁用扫光特效（与现有禁用规则一致）

# Task Dependencies
- Task 2 依赖 Task 1（按钮 key 需与 TimeRange 类型一致，先完成 Task 1）
- Task 3 独立，可与 Task 1/2 并行
