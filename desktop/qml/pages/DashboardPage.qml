// DashboardPage.qml — 工作台首页
//
// 职责：
// - onCompleted: 调 pnlService.summary() / accountService.listAccounts() /
//   strategyService.listInstances() / orderService.listOrders() 取数据
// - KPI 卡行：账户权益 / 今日盈亏 / 活跃策略数 / 账户数
// - 行情概览卡（占位：无行情接口，显示提示 + 币种列表占位）
// - 近期策略卡：DataTable 列 instances
// - 近期订单卡：DataTable 列 orders 前 10 条
// - 快捷操作卡：新建策略 / 新建账户按钮（发信号）

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick3D
import "../components"

Item {
    id: root
    property var colors: ({
        bg: "#1e1e2e", card: "#2a2a3a", fg: "#e4e4ef", fgSec: "#9999aa",
        accent: "#6366f1", border: "#33334a", hover: "#33334a"
    })

    // ===== 3D 氛围背景层（z 序最低，轻量、低透明度）=====
    // 作为视觉背景，不遮挡前景 KPI/行情/策略卡内容
    View3D {
        id: bgView3D
        anchors.fill: parent
        z: -1
        opacity: 0.35
        // 透明背景，让父级 bg 色透出
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            clearColor: "transparent"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }

        PerspectiveCamera {
            id: bgCamera
            position: Qt.vector3d(0, 0, 480)
            eulerRotation: Qt.vector3d(-12, 0, 0)
        }

        DirectionalLight {
            eulerRotation: Qt.vector3d(-30, -20, 0)
            brightness: 0.8
            ambientColor: Qt.rgba(0.4, 0.4, 0.5, 1.0)
        }

        // 飘动光点模型 1（立方体）：缓慢自转 + 平移
        Model {
            source: "#Cube"
            position: Qt.vector3d(-260, 120, -80)
            scale: Qt.vector3d(0.6, 0.6, 0.6)
            materials: PrincipledMaterial {
                baseColor: root.colors.accent
                metalness: 0.4
                roughness: 0.5
                opacity: 0.85
            }
            NumberAnimation on eulerRotation.y {
                from: 0; to: 360; duration: 18000; loops: Animation.Infinite
            }
            SequentialAnimation on position.y {
                loops: Animation.Infinite
                NumberAnimation { from: 120; to: 180; duration: 9000; easing.type: Easing.InOutSine }
                NumberAnimation { from: 180; to: 120; duration: 9000; easing.type: Easing.InOutSine }
            }
        }

        // 飘动光点模型 2（球体）：缓慢自转
        Model {
            source: "#Sphere"
            position: Qt.vector3d(280, -80, -40)
            scale: Qt.vector3d(0.5, 0.5, 0.5)
            materials: PrincipledMaterial {
                baseColor: Qt.rgba(0.39, 0.40, 0.86, 1.0)  // accent 淡蓝紫
                metalness: 0.6
                roughness: 0.3
                opacity: 0.8
            }
            NumberAnimation on eulerRotation.x {
                from: 0; to: 360; duration: 24000; loops: Animation.Infinite
            }
            SequentialAnimation on position.x {
                loops: Animation.Infinite
                NumberAnimation { from: 280; to: 320; duration: 11000; easing.type: Easing.InOutSine }
                NumberAnimation { from: 320; to: 280; duration: 11000; easing.type: Easing.InOutSine }
            }
        }

        // 飘动光点模型 3（小立方体，背景远处）
        Model {
            source: "#Cube"
            position: Qt.vector3d(60, 200, -180)
            scale: Qt.vector3d(0.35, 0.35, 0.35)
            materials: PrincipledMaterial {
                baseColor: root.colors.accent
                metalness: 0.2
                roughness: 0.7
                opacity: 0.6
            }
            NumberAnimation on eulerRotation.z {
                from: 0; to: -360; duration: 30000; loops: Animation.Infinite
            }
        }
    }

    // 快捷操作信号（main.qml 可接，未接则 console.log）
    signal newStrategyRequested()
    signal newAccountRequested()

    // 数据缓存
    property var summaryData: ({})
    property var accounts: []
    property var instances: []
    property var orders: []

    // 衍生统计
    readonly property int activeStrategyCount: {
        var c = 0
        for (var i = 0; i < instances.length; i++) {
            if (instances[i].status === "running") c++
        }
        return c
    }

    // ===== 主滚动区 =====
    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight + 32
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: content
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            spacing: 16

            // ===== 顶部标题行 =====
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.topMargin: 20
                spacing: 12

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Text {
                        text: qsTr("工作台")
                        color: root.colors.fg
                        font.pixelSize: 22
                        font.bold: true
                    }
                    Text {
                        text: qsTr("量化交易总览")
                        color: root.colors.fgSec
                        font.pixelSize: 12
                    }
                }

                // 刷新按钮
                Rectangle {
                    Layout.alignment: Qt.AlignVCenter
                    width: 32; height: 32; radius: 6
                    color: refreshMa.containsMouse ? root.colors.hover : "transparent"
                    border.color: root.colors.border
                    border.width: 1
                    Text {
                        anchors.centerIn: parent
                        text: "↻"
                        color: root.colors.fg
                        font.pixelSize: 16
                    }
                    MouseArea {
                        id: refreshMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: loadData()
                    }
                }
            }

            // ===== KPI 卡片行 =====
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                spacing: 16

                KpiCard {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 150
                    icon: "💰"
                    label: qsTr("账户权益")
                    value: fmtMoney(summaryData.latest_equity)
                    delta: ""
                    colors: root.colors
                }
                KpiCard {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 150
                    icon: "📈"
                    label: qsTr("今日盈亏")
                    value: fmtMoney(summaryData.total_pnl)
                    delta: fmtDelta(summaryData.total_pnl)
                    colors: root.colors
                }
                KpiCard {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 150
                    icon: "⚡"
                    label: qsTr("活跃策略")
                    value: String(activeStrategyCount)
                    delta: ""
                    colors: root.colors
                }
                KpiCard {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 150
                    icon: "👛"
                    label: qsTr("账户数")
                    value: String(accounts.length)
                    delta: ""
                    colors: root.colors
                }
            }

            // ===== 行情概览卡（占位）=====
            WorkspaceCard {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.preferredHeight: 120
                title: qsTr("行情概览")
                subtitle: qsTr("实时行情接口待接入")
                colors: root.colors

                Row {
                    anchors.fill: parent
                    spacing: 10

                    Text {
                        text: qsTr("行情接口待接入，可在此展示 BTC/ETH/SOL 等币种实时价格")
                        color: root.colors.fgSec
                        font.pixelSize: 12
                        anchors.verticalCenter: parent.verticalCenter
                        wrapMode: Text.WordWrap
                        width: parent.width - 20
                    }
                }
            }

            // ===== 近期策略卡 =====
            WorkspaceCard {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.preferredHeight: 280
                title: qsTr("近期策略")
                subtitle: qsTr("已部署的策略实例")
                colors: root.colors

                DataTable {
                    anchors.fill: parent
                    colors: root.colors
                    columns: [
                        { title: qsTr("名称"),   field: "name",       width: 160 },
                        { title: qsTr("币种"),   field: "symbol",     width: 140 },
                        { title: qsTr("状态"),   field: "statusText", width: 100 },
                        { title: qsTr("模板"),   field: "template_name", width: 160 },
                        { title: qsTr("启动时间"), field: "started_at",  width: 180 }
                    ]
                    rows: instanceRows
                    onRowClicked: function(rowData) {
                        console.log("[Dashboard] 策略行点击: " + JSON.stringify(rowData))
                    }
                }
            }

            // ===== 近期订单卡 =====
            WorkspaceCard {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.preferredHeight: 340
                title: qsTr("近期订单")
                subtitle: qsTr("最近 10 条订单")
                colors: root.colors

                DataTable {
                    anchors.fill: parent
                    colors: root.colors
                    columns: [
                        { title: qsTr("订单ID"), field: "id",         width: 80  },
                        { title: qsTr("币种"),   field: "symbol",     width: 130 },
                        { title: qsTr("方向"),   field: "side",       width: 70  },
                        { title: qsTr("价格"),   field: "price",      width: 110 },
                        { title: qsTr("数量"),   field: "quantity",   width: 100 },
                        { title: qsTr("状态"),   field: "status",     width: 100 },
                        { title: qsTr("时间"),   field: "created_at", width: 180 }
                    ]
                    rows: orderRows
                    onRowClicked: function(rowData) {
                        console.log("[Dashboard] 订单行点击: " + JSON.stringify(rowData))
                    }
                }
            }

            // ===== 快捷操作卡 =====
            WorkspaceCard {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.preferredHeight: 110
                title: qsTr("快捷操作")
                subtitle: qsTr("常用入口")
                colors: root.colors

                Row {
                    anchors.fill: parent
                    spacing: 12

                    // 新建策略按钮
                    Rectangle {
                        width: 140; height: 40
                        radius: 8
                        color: newStrategyMa.containsMouse ? Qt.lighter(root.colors.accent, 1.12)
                              : root.colors.accent
                        anchors.verticalCenter: parent.verticalCenter
                        Behavior on color { ColorAnimation { duration: 120 } }
                        Text {
                            anchors.centerIn: parent
                            text: qsTr("+ 新建策略")
                            color: "#ffffff"
                            font.pixelSize: 13
                            font.bold: true
                        }
                        MouseArea {
                            id: newStrategyMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                console.log("[Dashboard] 新建策略")
                                root.newStrategyRequested()
                            }
                        }
                    }

                    // 新建账户按钮
                    Rectangle {
                        width: 140; height: 40
                        radius: 8
                        color: newAccountMa.containsMouse ? root.colors.hover : "transparent"
                        border.color: root.colors.border
                        border.width: 1
                        anchors.verticalCenter: parent.verticalCenter
                        Behavior on color { ColorAnimation { duration: 120 } }
                        Text {
                            anchors.centerIn: parent
                            text: qsTr("+ 新建账户")
                            color: root.colors.fg
                            font.pixelSize: 13
                            font.bold: true
                        }
                        MouseArea {
                            id: newAccountMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                console.log("[Dashboard] 新建账户")
                                root.newAccountRequested()
                            }
                        }
                    }
                }
            }

            // 底部留白
            Item { Layout.fillWidth: true; Layout.preferredHeight: 8 }
        }
    }

    // ===== 衍生数据：为 DataTable 增加状态显示文本 =====
    readonly property var instanceRows: {
        var out = []
        for (var i = 0; i < instances.length; i++) {
            var it = instances[i]
            var copy = {}
            for (var k in it) copy[k] = it[k]
            copy.statusText = statusText(it.status)
            out.push(copy)
        }
        return out
    }

    readonly property var orderRows: {
        var out = []
        var n = Math.min(orders.length, 10)
        for (var i = 0; i < n; i++) {
            out.push(orders[i])
        }
        return out
    }

    // ===== 工具函数 =====
    function fmtMoney(v) {
        var n = Number(v)
        if (isNaN(n)) return "$0.00"
        var sign = n < 0 ? "-" : ""
        return sign + "$" + Math.abs(n).toLocaleString(Qt.locale("en_US"), "f", 2)
    }

    function fmtDelta(v) {
        var n = Number(v)
        if (isNaN(n) || n === 0) return ""
        return (n > 0 ? "+" : "") + n.toFixed(2)
    }

    function statusText(s) {
        if (s === "running") return qsTr("运行中")
        if (s === "stopped") return qsTr("已停止")
        if (s === "error") return qsTr("异常")
        if (s === "pending") return qsTr("等待中")
        return s ? s : "-"
    }

    // ===== 数据加载 =====
    function loadData() {
        // 盈亏汇总
        try {
            var s = pnlService.summary()
            if (s) root.summaryData = s
        } catch (e) {
            console.warn("[Dashboard] pnlService.summary 异常: " + e)
        }
        // 账户列表
        try {
            var accs = accountService.listAccounts()
            root.accounts = accs || []
        } catch (e) {
            console.warn("[Dashboard] accountService.listAccounts 异常: " + e)
        }
        // 策略实例
        try {
            var insts = strategyService.listInstances()
            root.instances = insts || []
        } catch (e) {
            console.warn("[Dashboard] strategyService.listInstances 异常: " + e)
        }
        // 订单
        try {
            var ords = orderService.listOrders()
            root.orders = ords || []
        } catch (e) {
            console.warn("[Dashboard] orderService.listOrders 异常: " + e)
        }
    }

    Component.onCompleted: loadData()
}
