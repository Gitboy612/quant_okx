# 桌面客户端方案 Spec（Qt 原生 QML 路线）

## Why
当前前端是 Vite + React 19 开发的 Web 端，用户通过浏览器访问 `http://127.0.0.1:8000`。现有打包方案（PyInstaller + Inno Setup）只是把后端打成 exe 后自动拉起浏览器，并非真正的桌面客户端——缺少独立窗口、原生标题栏、系统托盘、单实例等桌面级体验。用户希望做成类似 Adobe Creative Cloud / Microsoft 365 工作台 / QQ 桌面端这样的主流桌面应用，并明确选择 **Qt 原生 QML** 路线（方案 B）进行构建，以获得最小体积、最快性能与最流畅的原生动画。后端是 Python（FastAPI + uvicorn），用 PySide6 做壳可让后端在同一进程内以线程运行。

## 主流桌面应用前端技术栈对比

> 已选定 Qt 后，本节保留完整对比供溯源；纯原生方案（Flutter/MAUI）需重写前端且无 Python 优势，不适用。

### 1. Qt 原生 QML（本项目选定）
- **架构**：PySide6（Python 绑定）+ Qt Quick/QML 声明式 UI，Qt 原生场景图 GPU 加速渲染，无 Chromium 依赖
- **代表应用**：Telegram Desktop、OBS Studio、VLC、KDE 全家桶、WPS Office；经典版 QQ 桌面曾长期基于 Qt
- **安装包体积**：40-80MB（PySide6 QML 模块 + 嵌入式 mihomo.exe + 后端依赖；经 excludes 裁剪不含 QtWebEngine/Chromium）
- **内存占用**：低
- **UI 一致性**：✅ Qt 自绘，三端一致
- **动画/3D**：✅ QML 原生动画（`Behavior`/`NumberAnimation`/`Transition`，GPU 加速）+ `QtQuick3D` 替代 Three.js + `QtCharts` 替代 recharts
- **生态成熟度**：✅ Qt 30 年老牌框架，系统级 API（托盘、窗口、快捷键、文件对话框）极成熟
- **团队要求**：Python（已有）+ QML（需学习）
- **本项目的关键优势**：
  - **体积最小、启动/运行最快**：无 Chromium，40-80MB（裁剪后）
  - **动画最流畅**：QML 原生动画是强项，最契合 Adobe/M365/QQ 流畅感
  - **后端 Python 同进程线程**：FastAPI/uvicorn 作为 QThread 在同一进程内运行，无 sidecar
  - **真正原生集成**：托盘、快捷键、文件对话框为 Qt 原生
- **劣势**：
  - **前端 React 代码不可复用**：需用 QML 重写全部页面（约 8 个）与组件（10+）
  - 团队需熟悉 QML
  - 失去 React 生态（但 QML 生态对桌面 UI 足够）
  - 自动更新需自建（无 electron-updater 等现成方案）
  - Qt 许可证：PySide6 为 LGPL（可商用闭源，动态链接），PyQt6 为 GPL/商业双授权——**选 PySide6 规避 GPL**

### 2. QtWebEngine 混合（备选，方案 A）
- PySide6 + QWebEngineView 托管现有 React 前端，复用全部 `frontend/src/**`，体积 40–90MB
- 优点：工作量最低、保护 React 投资
- 缺点：仍带 Chromium，非纯原生
- 见附录 A 切换要点

### 3. Electron（备选）
- 自带 Chromium + Node.js，QQNT（最新版 QQ）、VS Code、Discord 同栈
- 缺点：Python 后端需子进程 sidecar、体积 50–150MB
- 见附录 B 切换要点

> **事实澄清**：经核实，最新版 QQ 桌面端（QQNT 架构）公开资料为 Electron 构建；经典版 QQ 桌面长期基于 Qt。本 Spec 按用户选择采用 Qt 原生 QML 路线，QQ 视觉风格 QML 完全可复刻。

### 4. Tauri 2.0 / Wails / 其他（不推荐）
- 系统 WebView 碎片化、需引入 Rust/Go 新语言；Flutter/MAUI 需重写前端且无 Python 优势

### 选型结论
| 维度 | Qt 原生 QML（选定） | QtWebEngine 混合 | Electron |
|---|---|---|---|
| 复用现有 React 前端 | ❌ 需 QML 重写 | ✅ | ✅ |
| 安装包体积 | **40-80MB** | 40–90MB | 50–150MB |
| 启动/运行性能 | **最优** | 中 | 较低 |
| 动画流畅度 | **最优（QML 原生）** | 中（JS 动画） | 中 |
| UI 渲染一致性 | ✅ Qt 自绘 | ✅ Chromium | ✅ Chromium |
| Python 后端集成 | ✅ 同进程线程 | ✅ 同进程线程 | ⚠️ 子进程 sidecar |
| 运行时复杂度 | **单 Python 运行时** | 单 Python 运行时 | Node+Python 双运行时 |
| 新语言门槛 | QML（需学） | 无 | 无 |
| 工作量 | 高（重写 UI） | 低 | 中 |
| 许可证 | LGPL(PySide6) | LGPL | MIT |

**选定 Qt 原生 QML**：用户明确选择，追求最小体积、最快性能、最流畅原生动画；接受前端重写成本。后端 Python 同进程线程运行消除 sidecar 复杂度。

## 前后端桥接策略

> 纯 QML 原生方案中，前后端通信采用 Qt 原生机制，**QWebChannel 主要服务于 QtWebEngine/Web 内容场景**，在纯 QML 中并非最佳。本 Spec 以 Qt 原生 signals/slots 为主，QWebChannel 作为可选桥接层（如未来嵌入 Web 内容时启用）。

### 主方案：Qt 原生 signals/slots（QML ↔ Python）
- **QML 调 Python**：通过 `QML_ELEMENT`/`@QmlElement` 注册 Python 类，或 `setContextProperty` 暴露 Python 对象，QML 直接调用方法
- **Python 主动推送 QML**：Python 对象 `emit` Qt signal，QML 用 `Connections`/`onSignal` 接收——这是 QML 原生最直接的双向通信，无需额外桥接层
- **数据请求**：QML 调用 Python 对象方法（同步返回或 async + signal 回调），Python 内部仍可走 FastAPI 路由逻辑复用

### QWebChannel 定位（备选，当前不启用）
- QWebChannel 设计用于 `QWebEngineView` 内 JS 与 Python 的桥接
- 纯 QML 方案无 WebEngine，用 QWebChannel 需额外引入 WebEngine 或 QML WebView，与"无 Chromium"初衷矛盾
- **若未来需在 QML 中嵌入 Web 内容（如 K 线图用 web 库）**，再启用 QWebChannel 桥接该 Web 子区域
- 当前一律用 QML 原生组件（QtCharts 等），不启用 QWebChannel

### 后端复用
- FastAPI 路由/服务层（`backend/routers/*`、`backend/services/*`、`backend/strategies/*`）完全复用
- QML 不走 HTTP，直接调 Python 服务层方法（通过注册的 Python 对象）；也可保留 uvicorn 在线程内跑，QML 走 HTTP/WS（兼容浏览器版）。**默认 QML 直接调 Python 对象**，避免本地 HTTP 开销

## UI 布局设计（参考 Adobe Cloud / Microsoft 365 / QQ）

> 目标：从现有"侧边栏 + 顶栏 + 表格"传统后台风格，升级为现代工作台风格。用 QML 原生重写。

### 参考设计语言抽取
- **Adobe Creative Cloud**：左侧分类侧边栏（Home/Apps/Files/Stock/Discover）+ 顶栏搜索与账户 + 主区应用卡片网格 + 深色主题
- **Microsoft 365 工作台（office.com）**：左上应用启动器 + 顶栏搜索与账户 + 左侧二级导航 + 主区"最近文件/模板"卡片网格 + 醒目"新建"按钮 + 浅色主题、圆角卡片、轻投影
- **QQ 桌面**：最左极窄图标导航轨（图标+头像，悬停提示）+ 中间列表面板 + 右侧详情区 + 扁平圆润、支持明暗

### 共性设计模式（本项目采用）
1. **最左极窄图标导航轨**（QQ 式）：80px 宽，图标 + 文字小标签；顶部用户头像（点击=账户/主题），底部设置。模块：仪表盘 / 策略 / 订单 / 持仓PnL / 账户 / 日志 / 监控 / 设置
2. **顶栏**（Adobe/M365 式）：全局搜索（策略/订单/币种）、账户切换器、通知铃铛（订单成交/策略触发/告警）、主题切换（明/暗）、最小化/最大化/关闭（自定义标题栏）
3. **主工作区 = 卡片优先的工作台**（Adobe/M365 式）：
   - 仪表盘：KPI 卡片行 + 行情概览卡 + 近期策略卡 + 快捷操作卡
   - 策略页：策略卡片网格（M365 文档卡式：名称/状态徽章/收益/操作），顶部醒目"新建策略"按钮
   - 账户页：账户卡片网格（余额/状态/操作）
   - 监控页：监控卡片网格
   - 订单/日志/PnL：表格但置于卡片容器内，配筛选侧栏
4. **圆角卡片 + 轻投影 + 悬停抬升**：统一 QML 卡片组件
5. **明暗双主题**：QML 主题切换 + 持久化（`QtQuick.Controls` 主题 + 自定义 QML 样式）
6. **上下文二级面板**（QQ 式，可选）：图标轨与主区之间按需展开二级列表面板

### 现有页面 → QML 映射
| 现有 React 页面 | QML 实现 |
|---|---|
| LoginPage | `LoginPage.qml` 居中登录卡 |
| DashboardPage | `DashboardPage.qml` 工作台首页：KPI 卡行 + 行情卡 + 近期策略卡 + 快捷操作 |
| StrategiesPage | `StrategiesPage.qml` 策略卡片网格 + 醒目"新建策略" |
| OrdersPage | `OrdersPage.qml` 卡片容器内表格 + 筛选侧栏 |
| MonitoringPage | `MonitoringPage.qml` 监控卡片网格 |
| AccountsPage | `AccountsPage.qml` 账户卡片网格 |
| PnL（持仓） | `PnlPage.qml` 卡片容器内表格 + QtCharts 图表卡 |
| LogsPage / ApiLogsPage | `LogsPage.qml` 卡片容器内表格 + 筛选侧栏 |
| SettingsPage | `SettingsPage.qml` M365 设置风格：左分区 + 右内容 |

### Three.js/图表/动画的 QML 替代
- Three.js 3D 区块链背景 → `QtQuick3D`（或简化为 QML `ParticleSystem`/`Canvas` 粒子背景）
- recharts 图表 → `QtCharts`（QML `ChartView`：折线/柱状/饼图）
- framer-motion 动画 → QML 原生（`Behavior`/`NumberAnimation`/`SpringAnimation`/`Transition`）
- Tailwind/CSS → QML 样式（`QtQuick.Controls` 主题 + 自定义 QML 组件 + `QtQuick.Shapes` 圆角）

## What Changes
- 新增 **PySide6 + QML 桌面壳**：`desktop/` 目录下 `main.py`（QApplication + QQmlApplicationEngine）、`backend_thread.py`（QThread 跑 uvicorn，可选）、`qml_bridge.py`（注册 Python 对象到 QML）、`tray.py`、`single_instance.py`
- 新增 **QML UI 全套**：`desktop/qml/` 下 `main.qml`、各 `*Page.qml`、组件 `*.qml`（IconRail/TopBar/WorkspaceCard/ThemeToggle/KpiCard/StatusBadge/DataTable）
- 新增 **QML ↔ Python 桥接**：用 `@QmlElement` 注册服务对象，QML 直接调 Python 方法；Python 通过 signal 主动推送（订单/告警）到 QML
- **复用后端**：`backend/routers/*`、`backend/services/*`、`backend/strategies/*`、`backend/models/*` 完全复用；QML 通过注册的 Python 服务对象调用业务逻辑
- **BREAKING（桌面端）**：桌面端 UI 用 QML 全新实现，不复用 `frontend/src/**`；现有 `frontend/`（Vite+React）仅保留为浏览器版
- 修改 **打包流程**：PyInstaller 打包 PySide6 + QML 资源 + 后端，复用 Inno Setup 流水线；桌面端安装包不含 QtWebEngine

## Impact
- Affected specs: `add-deployment-packaging`（桌面客户端打包与现有 Inno Setup 流水线衔接）
- Affected code:
  - 新增 `desktop/main.py`：Qt 应用入口（QApplication、QQmlApplicationEngine 加载 main.qml、无边框窗口）
  - 新增 `desktop/backend_thread.py`：QThread 封装 uvicorn（可选，若 QML 走 HTTP；默认 QML 直调 Python 则不启 uvicorn）
  - 新增 `desktop/qml_bridge.py`：用 `@QmlElement` 注册服务对象（AccountService/StrategyService/OrderService 等），暴露方法与 signals
  - 新增 `desktop/tray.py`：QSystemTrayIcon + QMenu
  - 新增 `desktop/single_instance.py`：QLocalSocket/QLocalServer 单实例锁
  - 新增 `desktop/qml/main.qml` 及全部 `*Page.qml`、组件 `*.qml`
  - 新增 `desktop/qml/theme/`：明暗主题 QML 样式
  - 新增 `desktop/requirements.txt`：PySide6、PySide3D、QtCharts（PySide6 已含 QtQuick3D/QtCharts 模块）
  - 新增 `desktop/resources.qrc`：QML 资源文件（图标、字体）
  - 修改 `QuantOKX.spec`（PyInstaller）：增加 desktop 入口分支，含 PySide6 hidden imports、QML/datas、Qt 插件
  - 修改 `installer/build_installer.bat`：增加 `--target desktop` 分支
  - 现有 `frontend/`（Vite+React）保留为浏览器版，不受影响

## ADDED Requirements

### Requirement: PySide6 + QML 桌面外壳
系统 SHALL 提供基于 PySide6 + Qt Quick/QML 的桌面外壳，以独立原生窗口运行，效果对标 Adobe Cloud / M365 / QQ 桌面端。

#### Scenario: 启动桌面客户端
- **WHEN** 用户双击桌面客户端可执行文件
- **THEN** 弹出独立应用窗口（非浏览器），加载 QML 主界面，显示自定义标题栏与应用图标

#### Scenario: 原生渲染与动画
- **WHEN** 应用运行
- **THEN** UI 由 Qt 原生场景图 GPU 加速渲染，QML 原生动画流畅，无 Chromium 依赖

### Requirement: 后端同进程运行
系统 SHALL 在 Qt 应用同一进程内运行后端业务逻辑；FastAPI/uvicorn 可选地在 QThread 内启动（仅当 QML 走 HTTP 时）。

#### Scenario: QML 直调后端（默认）
- **WHEN** QML 需要数据
- **THEN** 通过 `@QmlElement` 注册的 Python 服务对象直接调用业务方法，无本地 HTTP 开销

#### Scenario: 退出清理
- **WHEN** 用户退出应用
- **THEN** 若启用了 uvicorn 线程，`server.should_exit=True` 优雅停止并 `QThread.wait()`；QML 引擎安全销毁

### Requirement: QML ↔ Python 桥接
系统 SHALL 通过 Qt 原生 signals/slots 实现 QML 与 Python 双向通信，Python 可主动推送事件到 QML。

#### Scenario: QML 调用 Python
- **WHEN** QML 触发操作（如新建策略）
- **THEN** 调用注册的 Python 服务对象方法，返回结果或通过 signal 回调

#### Scenario: Python 主动推送
- **WHEN** 订单成交/策略触发/告警发生
- **THEN** Python 服务对象 emit signal，QML `Connections` 接收并更新 UI/弹桌面通知

### Requirement: 桌面级体验
系统 SHALL 提供系统托盘、最小化到托盘、单实例锁、自定义标题栏、明暗主题。

#### Scenario: 关闭最小化到托盘
- **WHEN** 用户点击窗口关闭按钮
- **THEN** 窗口隐藏到系统托盘；托盘右键菜单提供"显示/退出"

#### Scenario: 单实例
- **WHEN** 已运行实例时再次启动
- **THEN** 已有窗口聚焦恢复，不启动第二实例

#### Scenario: 自定义标题栏
- **WHEN** 窗口显示
- **THEN** 无边框窗口 + QML 自绘标题栏（应用名、最小化/最大化/关闭），支持拖动与边缘缩放

### Requirement: 工作台式 QML UI
系统 SHALL 采用"极窄图标轨 + 顶栏 + 卡片工作台"QML 布局，参考 Adobe Cloud / M365 / QQ 设计语言。

#### Scenario: 图标导航轨
- **WHEN** 应用显示
- **THEN** 最左 80px QML 图标轨：顶部用户头像，模块图标（仪表盘/策略/订单/持仓/账户/日志/监控/设置），底部设置；悬停显示文字提示

#### Scenario: 顶栏
- **WHEN** 进入主工作区
- **THEN** QML 顶栏含全局搜索、账户切换器、通知铃铛、主题切换、窗口控制按钮

#### Scenario: 卡片工作台
- **WHEN** 进入仪表盘/策略/账户/监控页
- **THEN** 主区以 QML 卡片网格呈现（圆角+轻投影+悬停抬升），策略/账户页顶部有醒目"新建"按钮

#### Scenario: 明暗主题
- **WHEN** 用户切换主题
- **THEN** QML 全应用切换明/暗主题并持久化

#### Scenario: 图表与 3D 背景
- **WHEN** 显示 PnL 图表或仪表盘 3D 背景
- **THEN** 用 QtCharts（ChartView）与 QtQuick3D 实现，流畅渲染

### Requirement: 桌面客户端打包
系统 SHALL 通过 PyInstaller 打包 PySide6 + QML 资源 + 后端，复用 Inno Setup 生成 Windows 安装包，不含 QtWebEngine。

#### Scenario: 打包
- **WHEN** 开发者执行 `installer/build_installer.bat --target desktop`
- **THEN** PyInstaller 打包 Qt 壳 + QML 资源 + 后端为单 exe（40–80MB，不含 QtWebEngine/Chromium），Inno Setup 生成安装包

## MODIFIED Requirements

### Requirement: 打包流水线
`installer/build_installer.bat` 修改如下：
- `--target desktop`：构建 Qt QML 桌面客户端（PySide6 + QML + 后端）
- 默认 `--target web`：保持现有 PyInstaller + Inno Setup 浏览器版
- 两种产物独立分发；桌面端不含 QtWebEngine/Chromium

## 附录 A：QtWebEngine 混合方案（方案 A）切换要点
> 若未来想复用 React 前端、降低重写成本，可切换至此方案。
- PySide6 + QWebEngineView 加载 `frontend/dist/index.html`
- 端口注入用 URL query 参数（`index.html?port=8000`），前端 `URLSearchParams` 读取
- 前后端桥接用 QWebChannel（此时 QWebChannel 才是合适的）
- 体积 40–90MB（含 Chromium）
- 现有 `frontend/src/**` 全复用，仅调 baseURL
- QtWebEngine 依赖需加入 PyInstaller datas

## 附录 B：Electron 方案切换要点
> 若未来想用 QQNT 同栈、获得 electron-updater 现成方案。
- BrowserWindow 加载 dist，主进程 spawn Python sidecar
- 需端口探测、崩溃重启、退出清理
- electron-builder 打 nsis 包，体积 50–150MB
- UI 布局（图标轨+工作台）与壳无关，React 改造结果可复用

## 体积说明

> 本节诚实记录体积目标的演进，避免后续验证/复盘时口径漂移。

**原目标 20-40MB 过于乐观**。在 PySide6 + QML 桌面端实际打包过程中，体积构成如下：

| 组成 | 体积估算 | 说明 |
|---|---|---|
| PySide6 QML 模块（QtQuick / QtCharts / QtQuick3D）的 qmldir + dll | 约 30-50MB | QML 运行时必需，无法裁剪 |
| 嵌入式 mihomo.exe（代理内核） | 约 10-30MB | `backend/bin/mihomo.exe` 随包分发 |
| Python 运行时 + 后端依赖（FastAPI / uvicorn / sqlalchemy / cryptography 等） | 约 20-30MB | 后端复用 web 版依赖 |
| **合计** | **约 60-110MB** | 裁剪前 |

**经 excludes 裁剪后预计 40-80MB**：
- 在 `QuantOKX-Desktop.spec` 的 `excludes` 中显式排除 QtWebEngine（Chromium 内核，本项目纯 QML 不用）、QtMultimedia / QtPdf / QtSvg / QtSql / QtTest / QtDesigner / QtHelp / QtBluetooth / QtNfc / QtPositioning / QtLocation / QtSensors / QtSerialPort / QtWebChannel / QtWebSockets / QtXml 等不用的 Qt 模块
- `collect_submodules('PySide6')` 改为显式列出实际用到的子模块（QtCore/QtGui/QtWidgets/QtQml/QtQuick/QtQuickControls2/QtQuickLayouts/QtQuickTemplates2/QtQuick3D/QtQuick3DUtils/QtCharts/QtChartsQml/QtNetwork + shiboken6）
- `collect_data_files('PySide6')` 保留全量（QML 模块的 qmldir 必需，否则运行时 `import QtQuick` 报 "module not found"）
- 主要靠 excludes 裁 Python 绑定层 + 不用的 Qt 模块 dll 来减体积

**如需进一步瘦身**：
- 将 mihomo.exe 改为首次启动按需下载（可减 10-30MB）
- 启用 UPX 压缩 Qt dll（`upx=True`），但需自行验证运行时无加载失败 / 杀软误报
- 拆分 Charts / Quick3D 模块为可选插件（若对应页面未访问时不加载）
