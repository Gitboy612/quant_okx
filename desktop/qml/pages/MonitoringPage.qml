// MonitoringPage.qml — 监控中心（事件统计 + 事件表格 + 自动刷新）
//
// 职责：
// - onCompleted: strategyService.listInstances()（先列实例，选中后查事件）
// - 顶部：标题"监控中心" + 策略实例选择器（标签切换）
// - 选中实例后：调 monitoringService.eventStats(instanceId) 显示统计卡
//   （总事件数 + 各类型计数），monitoringService.listEvents(instanceId) 用 DataTable 列事件
// - 自动刷新（Timer 每 10s 重新拉事件）

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var colors: ({
        bg: "#1e1e2e", card: "#2a2a3a", fg: "#e4e4ef", fgSec: "#9999aa",
        accent: "#6366f1", border: "#33334a", hover: "#33334a"
    })

    // 数据缓存
    property var instances: []
    property int selectedInstanceId: -1
    property var statsData: ({ total: 0, by_type: ({}) })
    property var events: []

    // 自动刷新定时器（每 10s 拉事件）
    Timer {
        id: refreshTimer
        interval: 10000
        repeat: true
        running: selectedInstanceId > 0
        onTriggered: loadEvents()
    }

    ColumnLayout {
        anchors.fill: parent
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
                    text: qsTr("监控中心")
                    color: root.colors.fg
                    font.pixelSize: 22
                    font.bold: true
                }
                Text {
                    text: qsTr("策略事件实时监控")
                    color: root.colors.fgSec
                    font.pixelSize: 12
                }
            }

            // 自动刷新指示
            Rectangle {
                Layout.alignment: Qt.AlignVCenter
                width: autoIndicator.implicitWidth + 20; height: 28
                radius: 14
                color: root.colors.hover
                visible: selectedInstanceId > 0
                Row {
                    id: autoIndicator
                    anchors.centerIn: parent
                    spacing: 6
                    Rectangle {
                        width: 6; height: 6; radius: 3
                        color: "#22c55e"
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: qsTr("自动刷新 10s")
                        color: root.colors.fgSec
                        font.pixelSize: 11
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }
        }

        // ===== 策略实例选择器（横向标签）=====
        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: 24
            Layout.rightMargin: 24
            Layout.preferredHeight: 48
            radius: 8
            color: root.colors.card
            border.color: root.colors.border
            border.width: 1

            Flickable {
                anchors.fill: parent
                anchors.margins: 4
                contentWidth: tagsRow.implicitWidth
                contentHeight: height
                flickableDirection: Flickable.HorizontalFlick
                boundsBehavior: Flickable.StopAtBounds
                clip: true
                ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

                Row {
                    id: tagsRow
                    spacing: 6

                    Repeater {
                        model: root.instances

                        delegate: Rectangle {
                            height: 36
                            width: tagRow.implicitWidth + 24
                            radius: 6
                            anchors.verticalCenter: parent.verticalCenter
                            color: root.selectedInstanceId === modelData.id
                                   ? root.colors.accent
                                   : (tagMa.containsMouse ? root.colors.hover : "transparent")
                            border.color: root.colors.border
                            border.width: root.selectedInstanceId === modelData.id ? 0 : 1
                            Behavior on color { ColorAnimation { duration: 120 } }

                            Row {
                                id: tagRow
                                anchors.centerIn: parent
                                spacing: 6
                                Text {
                                    text: modelData.name || qsTr("(未命名)")
                                    color: root.selectedInstanceId === modelData.id ? "#ffffff" : root.colors.fg
                                    font.pixelSize: 12
                                    font.bold: root.selectedInstanceId === modelData.id
                                    anchors.verticalCenter: parent.verticalCenter
                                    elide: Text.ElideRight
                                }
                            }

                            MouseArea {
                                id: tagMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.selectedInstanceId = modelData.id
                                    loadEvents()
                                }
                            }
                        }
                    }
                }
            }
        }

        // ===== 空状态：未选实例 =====
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 24
            Layout.rightMargin: 24
            visible: root.selectedInstanceId <= 0
            radius: 12
            color: root.colors.card
            border.color: root.colors.border
            border.width: 1

            Column {
                anchors.centerIn: parent
                spacing: 12
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "📡"
                    font.pixelSize: 40
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.instances.length === 0 ? qsTr("暂无策略实例") : qsTr("请选择上方策略实例查看监控")
                    color: root.colors.fg
                    font.pixelSize: 14
                    font.bold: true
                }
            }
        }

        // ===== 主内容区（选中实例后）=====
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 24
            Layout.rightMargin: 24
            spacing: 16
            visible: root.selectedInstanceId > 0

            // ===== 事件统计卡（总事件数 + 各类型计数）=====
            WorkspaceCard {
                Layout.fillWidth: true
                Layout.preferredHeight: 110
                title: qsTr("事件统计")
                subtitle: qsTr("总事件数 %1").arg(statsData.total || 0)
                colors: root.colors

                Flickable {
                    anchors.fill: parent
                    contentWidth: statsRow.implicitWidth
                    contentHeight: height
                    flickableDirection: Flickable.HorizontalFlick
                    boundsBehavior: Flickable.StopAtBounds
                    clip: true
                    ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

                    Row {
                        id: statsRow
                        anchors.fill: parent
                        spacing: 12

                        Repeater {
                            model: statsList

                            delegate: Rectangle {
                                width: 110; height: 56
                                radius: 8
                                color: root.colors.bg
                                border.color: root.colors.border
                                border.width: 1
                                anchors.verticalCenter: parent.verticalCenter

                                Column {
                                    anchors.centerIn: parent
                                    spacing: 2
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: modelData.count
                                        color: root.colors.fg
                                        font.pixelSize: 18
                                        font.bold: true
                                    }
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: modelData.type
                                        color: root.colors.fgSec
                                        font.pixelSize: 11
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ===== 事件明细卡 =====
            WorkspaceCard {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: qsTr("事件明细")
                subtitle: qsTr("最近 100 条事件")
                colors: root.colors

                DataTable {
                    anchors.fill: parent
                    colors: root.colors
                    columns: [
                        { title: qsTr("ID"),     field: "id",          width: 70  },
                        { title: qsTr("类型"),   field: "event_type",  width: 120 },
                        { title: qsTr("消息"),   field: "message",     width: 220 },
                        { title: qsTr("详情"),   field: "details",     width: 220 },
                        { title: qsTr("时间"),   field: "created_at",  width: 180 }
                    ]
                    rows: root.events
                    onRowClicked: function(rowData) {
                        console.log("[Monitoring] 事件行点击: " + JSON.stringify(rowData))
                    }
                }
            }
        }
    }

    // ===== 衍生：统计 by_type → 列表（便于 Repeater）=====
    readonly property var statsList: {
        var out = []
        var byType = statsData.by_type || {}
        for (var k in byType) {
            if (byType.hasOwnProperty(k)) {
                out.push({ type: k, count: byType[k] })
            }
        }
        if (out.length === 0 && (statsData.total || 0) > 0) {
            out.push({ type: qsTr("总计"), count: statsData.total })
        }
        return out
    }

    // ===== 数据加载 =====
    function loadInstances() {
        try {
            var insts = strategyService.listInstances()
            root.instances = insts || []
            // 默认选中第一个
            if (root.instances.length > 0 && root.selectedInstanceId <= 0) {
                root.selectedInstanceId = root.instances[0].id
                loadEvents()
            }
        } catch (e) {
            console.warn("[Monitoring] listInstances 异常: " + e)
        }
    }

    function loadEvents() {
        if (root.selectedInstanceId <= 0) return
        // 统计
        try {
            var s = monitoringService.eventStats(root.selectedInstanceId)
            if (s) root.statsData = s
        } catch (e) {
            console.warn("[Monitoring] eventStats 异常: " + e)
        }
        // 事件列表
        try {
            var evts = monitoringService.listEvents(root.selectedInstanceId)
            root.events = evts || []
        } catch (e) {
            console.warn("[Monitoring] listEvents 异常: " + e)
        }
    }

    Component.onCompleted: loadInstances()
}
