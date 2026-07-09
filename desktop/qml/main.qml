// QuantOKX 桌面客户端主 QML（Task 5：业务页面导航）
//
// 三段式布局：
//   ┌──────────────────────────────────────────────┐
//   │ 标题栏 40px（应用名 + 最小化/最大化/关闭）     │  ← 窗口控制
//   ├──────┬───────────────────────────────────────┤
//   │ 图标 │ TopBar 56px（搜索 + 账户 + 通知 + 主题） │  ← 功能区
//   │ 轨   ├───────────────────────────────────────┤
//   │ 80px │ StackView 主工作区（Task 5 业务页面）   │
//   └──────┴───────────────────────────────────────┘
//
// 登录态：未登录时隐藏 IconRail/TopBar，仅显示 LoginPage；
//         登录后显示三段式布局，按 currentModule 切换页面。
// 主题：property string theme 跟随 ThemeToggle / SettingsPage 切换；
//       颜色属性 colors 随主题重算，各组件/页面用注入的 colors。

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt.labs.settings 1.0
import "components"
import "pages"

ApplicationWindow {
    id: root
    visible: true
    title: "QuantOKX"
    // 无边框窗口：标题栏由 QML 自绘
    flags: Qt.FramelessWindowHint
    width: 1280
    height: 800
    minimumWidth: 1024
    minimumHeight: 640

    // 主题持久化：QSettings 自动落到 HKCU\Software\QuantOKX\QuantOKX（Windows）
    Settings {
        id: appSettings
        category: "ui"
        // theme 默认 "dark"；启动时从 QSettings 读取上次选择
        property string theme: "dark"
    }

    // ===== 主题与颜色 =====
    // root.theme 初值来自 appSettings.theme（QSettings）；root.theme 变化时回写落盘
    property string theme: appSettings.theme
    onThemeChanged: appSettings.theme = theme

    // 当前选中模块（IconRail 跟踪）
    property string currentModule: "dashboard"

    // 登录态：启动时根据 authService.isAuthenticated() 初始化
    property bool isLoggedIn: false

    // 统一颜色板：各组件由 root.colors 注入
    readonly property var colors: theme === "dark" ? ({
        bg:        "#1e1e2e",   // 窗口背景
        rail:      "#15151f",   // 图标轨
        titleBar:  "#181825",   // 标题栏
        card:      "#2a2a3a",   // 卡片
        fg:        "#e4e4ef",   // 文字主
        fgSec:     "#9999aa",   // 文字次
        accent:    "#6366f1",   // accent（紫蓝）
        border:    "#33334a",   // 边框
        hover:     "#33334a",   // 悬停
        btnHover:  "#313244",   // 标题栏按钮悬停
        btnCloseHover: "#f04438"// 关闭按钮悬停
    }) : ({
        bg:        "#f5f5f7",
        rail:      "#ffffff",
        titleBar:  "#ffffff",
        card:      "#ffffff",
        fg:        "#1a1a2e",
        fgSec:     "#666677",
        accent:    "#6366f1",
        border:    "#e5e5ea",
        hover:     "#ececec",
        btnHover:  "#ececec",
        btnCloseHover: "#f04438"
    })

    color: colors.bg

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ===== 第一行：标题栏（40px，窗口控制）=====
        Rectangle {
            id: titleBar
            Layout.fillWidth: true
            Layout.preferredHeight: 40
            color: root.colors.titleBar

            // 标题栏拖动移动窗口
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                onPressed: (mouse) => {
                    if (mouse.button === Qt.LeftButton) {
                        root.startSystemMove()
                    }
                }
                onDoubleClicked: (mouse) => {
                    if (mouse.button === Qt.LeftButton) {
                        root.toggleMaximize()
                    }
                }
            }

            // 应用名 Label
            Label {
                anchors.left: parent.left
                anchors.leftMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                text: "QuantOKX"
                color: root.colors.fg
                font.pixelSize: 14
                font.bold: true
            }

            // 右侧窗口控制按钮组
            RowLayout {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 0

                TitleBarButton {
                    implicitWidth: 46
                    implicitHeight: 40
                    iconType: "minimize"
                    normalColor: root.colors.titleBar
                    hoverColor: root.colors.btnHover
                    iconColor: root.colors.fg
                    onClicked: root.showMinimized()
                }

                TitleBarButton {
                    implicitWidth: 46
                    implicitHeight: 40
                    iconType: "maximize"
                    isMaximized: (root.visibility === Window.Maximized
                                  || root.visibility === Window.FullScreen)
                    normalColor: root.colors.titleBar
                    hoverColor: root.colors.btnHover
                    iconColor: root.colors.fg
                    onClicked: root.toggleMaximize()
                }

                TitleBarButton {
                    implicitWidth: 46
                    implicitHeight: 40
                    iconType: "close"
                    normalColor: root.colors.titleBar
                    hoverColor: root.colors.btnCloseHover
                    iconColor: root.colors.fg
                    hoverIconColor: "#ffffff"
                    onClicked: Qt.quit()
                }
            }
        }

        // ===== 第二行：主工作区 = 图标轨 + (顶栏 + StackView) =====
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // 图标轨：仅登录后显示
            IconRail {
                id: iconRail
                Layout.fillHeight: true
                Layout.preferredWidth: 80
                colors: root.colors
                currentModule: root.currentModule
                visible: root.isLoggedIn
                onNavClicked: function(module) {
                    root.navigate(module)
                }
                onAccountClicked: console.log("[TopBar] 账户中心点击")
            }

            ColumnLayout {
                Layout.fillHeight: true
                Layout.fillWidth: true
                spacing: 0

                // 顶栏：仅登录后显示
                TopBar {
                    id: topBar
                    Layout.fillWidth: true
                    Layout.preferredHeight: 56
                    colors: root.colors
                    theme: root.theme
                    visible: root.isLoggedIn
                    onThemeSwitched: function(t) { root.theme = t }
                    onSearchSubmitted: function(text) {
                        console.log("[TopBar] 搜索提交: " + text)
                    }
                    onAccountSwitcherClicked: console.log("[TopBar] 账户切换器")
                    onNotificationClicked: console.log("[TopBar] 通知点击")
                }

                // 主工作区 StackView（Task 5：按模块切换业务页面）
                StackView {
                    id: stackView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    // 初始页在 Component.onCompleted 中根据登录态决定
                    initialItem: loginPageComp
                }
            }
        }
    }

    // ===== 页面 Component 定义 =====
    // 登录页（全屏，无 IconRail/TopBar）
    Component {
        id: loginPageComp
        LoginPage {
            // colors 通过 navigate/初始化时用 Qt.binding 注入，保证主题切换跟随
        }
    }

    Component { id: dashboardPageComp;   DashboardPage {} }
    Component { id: strategiesPageComp;  StrategiesPage {} }
    Component { id: ordersPageComp;      OrdersPage {} }
    Component { id: pnlPageComp;         PnlPage {} }
    Component { id: accountsPageComp;    AccountsPage {} }
    Component { id: logsPageComp;        LogsPage {} }
    Component { id: monitoringPageComp;  MonitoringPage {} }
    Component { id: settingsPageComp;    SettingsPage {} }

    // ===== 监听当前页面的业务信号（登录成功 / 退出登录 / 主题切换）=====
    // ignoreUnknownSignals: 不同页面信号不同，未定义的信号忽略，避免告警
    Connections {
        target: stackView.currentItem
        ignoreUnknownSignals: true
        // LoginPage 登录成功
        function onLoginSuccess() {
            root.handleLoginSuccess()
        }
        // SettingsPage 退出登录
        function onLogoutRequested() {
            root.handleLogout()
        }
        // SettingsPage 主题切换
        function onThemeSwitched(t) {
            root.theme = t
        }
        // 各页面的快捷操作信号（当前仅日志，后续可接弹窗）
        function onNewStrategyRequested() {
            console.log("[main] 新建策略请求")
        }
        function onNewAccountRequested() {
            console.log("[main] 新建账户请求")
        }
    }

    // ===== 全局快捷键 Ctrl+K 唤起搜索 =====
    Shortcut {
        sequence: "Ctrl+K"
        onActivated: {
            if (topBar) topBar.focusSearch()
        }
    }

    // ===== 导航：按 module 切换 StackView 页面 =====
    function navigate(module) {
        root.currentModule = module
        var comp = null
        switch (module) {
            case "dashboard":  comp = dashboardPageComp;  break
            case "strategy":   comp = strategiesPageComp; break
            case "orders":     comp = ordersPageComp;     break
            case "pnl":        comp = pnlPageComp;        break
            case "accounts":   comp = accountsPageComp;   break
            case "logs":       comp = logsPageComp;       break
            case "monitoring": comp = monitoringPageComp; break
            case "settings":   comp = settingsPageComp;   break
        }
        if (!comp) return
        stackView.replace(comp)
        // 注入颜色板（用 binding 保证主题切换时跟随 root.colors 更新）
        if (stackView.currentItem) {
            stackView.currentItem.colors = Qt.binding(function() { return root.colors })
            // 设置页需要 theme 属性同步
            if (module === "settings") {
                stackView.currentItem.theme = Qt.binding(function() { return root.theme })
            }
        }
    }

    // ===== 登录成功：进 Dashboard =====
    // 用 Qt.callLater 延迟导航，避免在 LoginPage 信号处理过程中销毁自身页面
    function handleLoginSuccess() {
        Qt.callLater(function() {
            root.isLoggedIn = true
            root.currentModule = "dashboard"
            root.navigate("dashboard")
        })
    }

    // ===== 退出登录：回登录页 =====
    function handleLogout() {
        Qt.callLater(function() {
            root.isLoggedIn = false
            root.currentModule = "dashboard"
            stackView.replace(loginPageComp)
            if (stackView.currentItem) {
                stackView.currentItem.colors = Qt.binding(function() { return root.colors })
            }
        })
    }

    // ===== 显示登录页（注入颜色板绑定）=====
    function showLoginPage() {
        stackView.replace(loginPageComp)
        if (stackView.currentItem) {
            stackView.currentItem.colors = Qt.binding(function() { return root.colors })
        }
    }

    // ===== 启动初始化：根据登录态决定初始页 =====
    Component.onCompleted: {
        var authed = false
        try {
            authed = authService.isAuthenticated()
        } catch (e) {
            console.warn("[main] isAuthenticated 异常: " + e)
        }
        root.isLoggedIn = authed
        if (authed) {
            // 已登录：直接进 Dashboard
            root.navigate("dashboard")
        } else {
            // 未登录：显示登录页（initialItem 已是 loginPageComp，补绑 colors）
            if (stackView.currentItem) {
                stackView.currentItem.colors = Qt.binding(function() { return root.colors })
            }
        }
    }

    // 切换最大化/还原
    function toggleMaximize() {
        if (root.visibility === Window.Maximized || root.visibility === Window.FullScreen) {
            root.visibility = Window.Windowed
        } else {
            root.visibility = Window.Maximized
        }
    }

    // ===== 自绘标题栏按钮组件（内联组件，Task 1 复用）=====
    // iconType: "minimize" | "maximize" | "close"
    component TitleBarButton : Rectangle {
        id: btn
        property string iconType: "minimize"
        property bool isMaximized: false
        property color normalColor: "transparent"
        property color hoverColor: "#313244"
        property color iconColor: "#cdd6f4"
        property color hoverIconColor: "#cdd6f4"
        property bool hovered: false

        signal clicked()

        color: hovered ? hoverColor : normalColor
        Behavior on color { ColorAnimation { duration: 100 } }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            onEntered: btn.hovered = true
            onExited: btn.hovered = false
            onClicked: btn.clicked()
        }

        Canvas {
            anchors.centerIn: parent
            width: 26
            height: 26
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                var color = btn.hovered ? btn.hoverIconColor : btn.iconColor
                ctx.lineWidth = 1.5
                ctx.strokeStyle = color
                ctx.lineCap = "round"

                if (btn.iconType === "minimize") {
                    ctx.beginPath()
                    ctx.moveTo(8, 13)
                    ctx.lineTo(18, 13)
                    ctx.stroke()
                } else if (btn.iconType === "maximize") {
                    if (btn.isMaximized) {
                        ctx.strokeRect(6, 8, 9, 9)
                        ctx.beginPath()
                        ctx.moveTo(9, 8)
                        ctx.lineTo(9, 5)
                        ctx.lineTo(18, 5)
                        ctx.lineTo(18, 14)
                        ctx.lineTo(15, 14)
                        ctx.stroke()
                    } else {
                        ctx.strokeRect(7, 6, 12, 12)
                    }
                } else if (btn.iconType === "close") {
                    ctx.beginPath()
                    ctx.moveTo(8, 8)
                    ctx.lineTo(18, 18)
                    ctx.moveTo(18, 8)
                    ctx.lineTo(8, 18)
                    ctx.stroke()
                }
            }
            // 悬停 / 最大化 / 颜色（主题切换）变化时重绘
            Connections {
                target: btn
                function onHoveredChanged() { requestPaint() }
                function onIsMaximizedChanged() { requestPaint() }
                function onIconColorChanged() { requestPaint() }
                function onHoverIconColorChanged() { requestPaint() }
            }
        }
    }
}
