# Q-Studio UI 升级计划（修订版）

## 概览

五个改动方向：14 代币节点 + 拖拽、星空背景、账户层级修复、Q-Studio Logo（真实PNG图片）、图标整合。

---

## 任务 1：14 代币节点 + 拖拽 + 透明度控制

**文件**: `components/BlockchainBackground.tsx`

### 当前状态
- 8 个代币（BTC/ETH/AVAX/LINK/SOL/HYPE/OKB/BNB），使用 `assets/` 下的真实圆形图标
- 节点默认完全不透明，无拖拽功能
- 已有资源：`ada.png, doge.png, trx.png, usdt.png, xrp.png, xlm.jpg` 可直接使用

### 改动点
1. **扩展 TOKEN_CONFIG**：新增 ADA（#0033AD）、DOGE（#C2A633）、TRX（#FF0013）、USDT（#26A17B）、XRP（#00AAE4）、XLM（#14B6E7），含 price/change24h/marketCap 数据
2. **降低默认透明度**：节点 resting opacity 从 1.0 → 0.30，渐入目标值改为 0.30
3. **悬停高亮**：hover 时 opacity 平滑过渡到 1.0，增强发光半径和边框亮度
4. **拖拽交互**：
   - 新增 `dragStateRef`（active/token/offsetX/offsetY）
   - mousedown 拾取节点（检测半径 1.8x），mousemove 跟随移动，mouseup 释放
   - 拖拽期间暂停节点漂移动画（`!token.dragging` guard）
   - 拖拽 vs 点击判断：移动距离 < 5px 视为点击（固定 tooltip），否则为拖拽结束
   - 释放后赋予微小随机漂移速度恢复运动
   - cursor 状态：hover → `grab`，dragging → `grabbing`
5. **空间参数调整**：baseRadius 20→18，分布距离略微增大避免拥挤
6. **事件重构**：移除 click 监听，改为 mousedown/mousemove/mouseup 组合

---

## 任务 2：星空背景 — 向后漂移

**文件**: `components/BlockchainBackground.tsx`（同文件，星空绘制在代币图层之前）

### 设计
- 300 颗星星，4 个深度层（近处大/快/亮，远处小/慢/暗）
- 从屏幕中心附近生成，沿径向向外漂移，超出边缘后重置到中心
- 速度 0.08~0.12 px/帧（约 5~7 px/秒），极慢防止晕眩
- 颜色：冷白偏蓝 `rgba(200, 220, 255, brightness)`

### 数据结构
```
Star { x, y, z(深度0~1), speed, size(0.3~1.5), brightness(0.15~0.7) }
```

### 绘制顺序
星空（最底）→ 连线 → dots → 代币节点（最上）

---

## 任务 3：账户切换层级修复

### 当前问题
- `Layout.tsx` 维护 `selectedAccountId` 传给 `TopBar`
- `DashboardPage.tsx` 独立维护自己的 `selectedAccountId` + `accounts` + Dropdown
- 两个账户选择器完全独立，互不影响

### 方案：React Context

**新建** `hooks/useSelectedAccount.tsx`：
- `SelectedAccountProvider`：统一管理 accounts 列表 + selectedAccountId
- 在 Provider 内调用 `listAccounts` API，自动选中第一个账户
- `useSelectedAccount()` hook 暴露 { accounts, selectedAccountId, selectAccount }

**修改 `Layout.tsx`**：
- 移除本地 `selectedAccountId` state
- 用 `SelectedAccountProvider` 包裹 Layout 内容
- 从 Context 读取 selectedAccountId 传给 TopBar

**修改 `TopBar.tsx`**：
- 移除内部 `listAccounts` API 调用
- 从 `useSelectedAccount()` 获取 accounts 列表

**修改 `DashboardPage.tsx`**：
- 移除独立的 `accounts` state、`selectedAccountId` state、`handleAccountChange`
- 改用 `useSelectedAccount()` 获取共享状态
- 移除页面内的账户 Dropdown（TopBar 已有）
- 新增 useEffect 监听 `selectedAccountId` 变化触发 loadAssets

---

## 任务 4：Q-Studio Logo — 专业 PNG 图片

**新建**: `assets/qstudio-logo.jpg`（已生成，256x256 透明背景）

**修改** `components/Sidebar.tsx`：
- 移除当前的文字 Q（`<span>Q</span>`）
- 改用 `<img src={new URL('../assets/qstudio-logo.jpg', import.meta.url).href} alt="Q-Studio" className="w-7 h-7" />`

**修改** `pages/LoginPage.tsx`：
- 移除当前的文字 Q（`<span>Q</span>`）
- 改用 `<img src={new URL('../assets/qstudio-logo.jpg', import.meta.url).href} alt="Q-Studio" className="w-12 h-12" />`

### Logo 设计说明
- 字母 Q，尾巴形成上涨趋势线 + 小箭头末端
- Q 圆形内含六边形区块链网络节点 + 微弱连线
- 颜色：主色 #00D4AA（渐变到 #00B894），深色底 #050711
- 风格：现代金融科技，简洁几何，高端扁平化
- 尺寸适配：Sidebar 28x28，LoginPage 48x48

---

## 文件变更清单

| 文件 | 操作 | 任务 |
|------|------|------|
| `assets/qstudio-logo.jpg` | **新建**（已生成） | 4 |
| `components/BlockchainBackground.tsx` | 大幅修改 | 1, 2 |
| `hooks/useSelectedAccount.tsx` | **新建** | 3 |
| `components/Layout.tsx` | 修改 | 3 |
| `components/TopBar.tsx` | 修改 | 3 |
| `pages/DashboardPage.tsx` | 修改 | 3 |
| `components/Sidebar.tsx` | 修改 | 4 |
| `pages/LoginPage.tsx` | 修改 | 4 |

## 执行顺序
1. 任务 4（Logo，使用已生成的 PNG，快速替换）
2. 任务 3（账户层级修复，架构改动优先）
3. 任务 1+2（合并开发，同文件 BlockchainBackground.tsx）

## 验证
- TypeScript 编译零错误
- 14 个代币图标全部正确渲染（圆形裁剪）
- 拖拽功能：拾取→移动→释放，click vs drag 正确区分
- 星空持续向后漂移，速度舒适不晕眩
- TopBar 账户切换同步影响 DashboardPage 数据加载
- Logo 在 Sidebar（28x28）和 LoginPage（48x48）正确显示
- Logo 视觉清晰，在小尺寸下可识别