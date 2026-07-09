# Checklist

## 选型研究
- [x] spec.md 含主流桌面技术栈对比（Qt 原生 QML / QtWebEngine 混合 / Electron / Tauri 等），含体积、一致性、生态、门槛、Python 集成、许可证
- [x] spec.md 明确选定 Qt 原生 QML 并给出理由（最小体积、最快性能、最流畅动画、Python 同进程、用户明确选择）
- [x] spec.md 引用真实参考案例（QQNT 实为 Electron、经典 QQ 为 Qt、Qt 代表 Telegram/OBS/WPS）
- [x] spec.md 事实澄清"最新版 QQ(QQNT) 为 Electron 构建、经典 QQ 为 Qt"
- [x] spec.md 附录 A/B 记录 QtWebEngine 与 Electron 切换要点

## 前后端桥接
- [x] spec.md 含"前后端桥接策略"章节，说明纯 QML 方案用 Qt 原生 signals/slots（@QmlElement 注册 + signal 推送）
- [x] spec.md 说明 QWebChannel 定位（服务 QtWebEngine 场景，纯 QML 当前不启用，未来嵌 Web 内容再启用）
- [x] spec.md 说明后端复用（routers/services/strategies/models 完全复用，QML 直调 Python 服务对象）

## UI 布局设计
- [x] spec.md 含"UI 布局设计"章节，参考 Adobe Cloud / M365 / QQ 三者并抽取共性设计语言
- [x] spec.md 明确新布局：80px 极窄图标轨 + 顶栏（搜索/账户/通知/主题/窗口控制）+ 卡片工作台 + 明暗主题
- [x] spec.md 提供现有 React 页面到 QML 文件的映射表
- [x] spec.md 列出 Three.js/recharts/framer-motion/Tailwind 的 QML 替代（QtQuick3D/QtCharts/QML 动画/QML 样式）

## 架构设计
- [x] spec.md 描述 PySide6 + QML 壳结构（QApplication/QQmlApplicationEngine/无边框自绘标题栏）
- [x] spec.md 描述后端同进程运行（QML 直调 Python，uvicorn 可选）
- [x] spec.md 列出受影响代码（desktop/* 新增、QuantOKX.spec、installer/build_installer.bat；frontend/ 保留为浏览器版）

## 需求完整性
- [x] ADDED Requirements 覆盖：PySide6+QML 外壳、后端同进程、QML↔Python 桥接、桌面级体验、工作台式 QML UI、打包
- [x] 每个 Requirement 至少含 1 个 Scenario（WHEN/THEN）
- [x] MODIFIED Requirements 说明对现有浏览器版的影响（不破坏、可并存）

## 任务可执行性
- [x] tasks.md 拆分为 7 个有序任务（壳/桥接/桌面体验/UI 框架/QML 页面/打包/验证）
- [x] tasks.md 标注任务依赖与可并行项
- [x] tasks.md 含验证任务（渲染、桌面体验、桥接、体积、共存）

## 风险与约束
- [x] 考虑 QML 重写成本（约 8 页面 + 10 组件）
- [x] 考虑单实例锁避免重复启动
- [x] 考虑 PyInstaller 打包 PySide6 + QML 资源（Qt 插件/datas/qrc）
- [x] 考虑许可证：选 PySide6(LGPL) 而非 PyQt6(GPL)
- [x] 考虑桌面端不含 QtWebEngine（体积目标 20–40MB）
- [x] 考虑与现有 PyInstaller+Inno Setup 浏览器版的并存（--target desktop/web）
