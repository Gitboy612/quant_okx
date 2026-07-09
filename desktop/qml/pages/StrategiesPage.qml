// StrategiesPage.qml — 策略管理（卡片网格 + 醒目"新建策略"按钮）
//
// 职责：
// - onCompleted: strategyService.listInstances() + strategyService.listTemplates()
// - 顶部：标题"策略管理" + 醒目"新建策略"按钮（accent 色，发信号）
// - 卡片网格（Flow）：每张卡显示 name/symbol/StatusBadge(status)/template_name/strategy_type，
//   底部"启停/详情"按钮（发信号）
// - 空状态：无策略时显示"暂无策略，点击新建"占位

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

    // 业务信号（main.qml 可接；当前仅 console.log）
    signal newStrategyRequested()
    signal toggleStrategyRequested(var instanceId)
    signal strategyDetailRequested(var instanceId)

    // 数据缓存
    property var instances: []
    property var templates: []

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
                        text: qsTr("策略管理")
                        color: root.colors.fg
                        font.pixelSize: 22
                        font.bold: true
                    }
                    Text {
                        text: qsTr("共 %1 个策略实例，%2 个模板").arg(instances.length).arg(templates.length)
                        color: root.colors.fgSec
                        font.pixelSize: 12
                    }
                }

                // 醒目"新建策略"按钮
                Rectangle {
                    Layout.alignment: Qt.AlignVCenter
                    width: 130; height: 38
                    radius: 8
                    color: newMa.containsMouse ? Qt.lighter(root.colors.accent, 1.12)
                          : root.colors.accent
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Row {
                        anchors.centerIn: parent
                        spacing: 6
                        Text {
                            text: "＋"
                            color: "#ffffff"
                            font.pixelSize: 16
                            font.bold: true
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: qsTr("新建策略")
                            color: "#ffffff"
                            font.pixelSize: 13
                            font.bold: true
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    MouseArea {
                        id: newMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            console.log("[Strategies] 新建策略")
                            root.newStrategyRequested()
                        }
                    }
                }
            }

            // ===== 空状态占位 =====
            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.preferredHeight: 200
                visible: instances.length === 0
                radius: 12
                color: root.colors.card
                border.color: root.colors.border
                border.width: 1

                Column {
                    anchors.centerIn: parent
                    spacing: 12
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "🎯"
                        font.pixelSize: 40
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: qsTr("暂无策略")
                        color: root.colors.fg
                        font.pixelSize: 16
                        font.bold: true
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: qsTr("点击右上角「新建策略」开始部署")
                        color: root.colors.fgSec
                        font.pixelSize: 12
                    }
                }
            }

            // ===== 策略卡片网格（Flow 自适应换行）=====
            Flow {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                spacing: 16
                visible: instances.length > 0

                Repeater {
                    model: root.instances

                    delegate: Rectangle {
                        width: 300
                        height: 200
                        radius: 12
                        color: root.colors.card
                        border.color: root.colors.border
                        border.width: 1

                        // 悬停投影
                        Rectangle {
                            z: -1
                            anchors.fill: parent
                            anchors.topMargin: 3
                            radius: 12
                            color: "#000000"
                            opacity: cardMa.containsMouse ? 0.22 : 0.10
                            Behavior on opacity { NumberAnimation { duration: 150 } }
                        }

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 16
                            spacing: 8

                            // 顶部：名称 + 状态徽章
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.name || qsTr("(未命名)")
                                    color: root.colors.fg
                                    font.pixelSize: 15
                                    font.bold: true
                                    elide: Text.ElideRight
                                }

                                StatusBadge {
                                    status: modelData.status || "stopped"
                                    text: statusText(modelData.status)
                                    colors: root.colors
                                    Layout.alignment: Qt.AlignVCenter
                                }
                            }

                            // 币种 + 市场类型
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Text {
                                    text: "💱"
                                    font.pixelSize: 12
                                    color: root.colors.fgSec
                                }
                                Text {
                                    text: (modelData.symbol || "-") + " · " + (modelData.market_type || qsTr("现货"))
                                    color: root.colors.fg
                                    font.pixelSize: 13
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                }
                            }

                            // 模板 / 类型
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Text {
                                    text: "🎯"
                                    font.pixelSize: 12
                                    color: root.colors.fgSec
                                }
                                Text {
                                    text: (modelData.template_name || qsTr("自定义")) + " · " + (modelData.strategy_type || "-")
                                    color: root.colors.fgSec
                                    font.pixelSize: 12
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                }
                            }

                            // 弹簧
                            Item { Layout.fillHeight: true }

                            // 底部按钮组
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                // 启停按钮
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 30
                                    radius: 6
                                    color: toggleMa.containsMouse ? root.colors.hover : "transparent"
                                    border.color: root.colors.border
                                    border.width: 1
                                    Behavior on color { ColorAnimation { duration: 120 } }
                                    Text {
                                        anchors.centerIn: parent
                                        text: modelData.status === "running" ? qsTr("停止") : qsTr("启动")
                                        color: root.colors.fg
                                        font.pixelSize: 12
                                        font.bold: true
                                    }
                                    MouseArea {
                                        id: toggleMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            console.log("[Strategies] 启停策略 id=" + modelData.id)
                                            root.toggleStrategyRequested(modelData.id)
                                        }
                                    }
                                }

                                // 详情按钮
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 30
                                    radius: 6
                                    color: detailMa.containsMouse ? root.colors.hover : "transparent"
                                    border.color: root.colors.border
                                    border.width: 1
                                    Behavior on color { ColorAnimation { duration: 120 } }
                                    Text {
                                        anchors.centerIn: parent
                                        text: qsTr("详情")
                                        color: root.colors.fg
                                        font.pixelSize: 12
                                        font.bold: true
                                    }
                                    MouseArea {
                                        id: detailMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            console.log("[Strategies] 策略详情 id=" + modelData.id)
                                            root.strategyDetailRequested(modelData.id)
                                        }
                                    }
                                }
                            }
                        }

                        MouseArea {
                            id: cardMa
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.NoButton
                        }
                    }
                }
            }

            Item { Layout.fillWidth: true; Layout.preferredHeight: 8 }
        }
    }

    // ===== 工具函数 =====
    function statusText(s) {
        if (s === "running") return qsTr("运行中")
        if (s === "stopped") return qsTr("已停止")
        if (s === "error") return qsTr("异常")
        if (s === "pending") return qsTr("等待中")
        return s ? s : "-"
    }

    // ===== 数据加载 =====
    function loadData() {
        try {
            var insts = strategyService.listInstances()
            root.instances = insts || []
        } catch (e) {
            console.warn("[Strategies] listInstances 异常: " + e)
        }
        try {
            var tpls = strategyService.listTemplates()
            root.templates = tpls || []
        } catch (e) {
            console.warn("[Strategies] listTemplates 异常: " + e)
        }
    }

    Component.onCompleted: loadData()
}
