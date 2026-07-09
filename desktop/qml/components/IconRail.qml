// IconRail.qml — 极窄图标导航轨（QQ 式）
//
// 职责：
// - 宽 80px，满高，深色背景（colors.rail）
// - 顶部用户头像（圆形占位，点击发 accountClicked()）
// - 中部模块图标垂直排列：emoji 图标 + 下方 10pt 文字标签
// - 当前选中项：左侧 accent 竖条 + 背景稍亮，点击发 navClicked(module)
// - 底部设置图标
// - 悬停 tooltip（ToolTip.show）
// - property string currentModule 跟踪选中

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

Rectangle {
    id: root
    implicitWidth: 80
    color: colors.rail

    property var colors: ({
        rail: "#15151f",
        accent: "#6366f1",
        fg: "#e4e4ef",
        fgSec: "#9999aa",
        hover: "#33334a",
        border: "#33334a"
    })
    property string currentModule: "dashboard"

    // 中部模块列表（设置固定在底部，故此处不含 settings）
    property var modules: [
        { key: "dashboard",  icon: "📊", label: "仪表盘" },
        { key: "strategy",   icon: "🎯", label: "策略" },
        { key: "orders",     icon: "📋", label: "订单" },
        { key: "pnl",        icon: "💰", label: "持仓PnL" },
        { key: "accounts",   icon: "👛", label: "账户" },
        { key: "logs",       icon: "📜", label: "日志" },
        { key: "monitoring", icon: "📡", label: "监控" }
    ]

    signal navClicked(string module)
    signal accountClicked()

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ===== 顶部用户头像 =====
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 84

            Rectangle {
                id: avatar
                width: 44
                height: 44
                radius: 22
                anchors.centerIn: parent
                color: root.colors.accent
                border.color: root.colors.border
                border.width: 1

                Text {
                    anchors.centerIn: parent
                    text: "Q"
                    color: "#ffffff"
                    font.pixelSize: 18
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.accountClicked()
                    onEntered: ToolTip.show(qsTr("账户中心"), 2000)
                    onExited: ToolTip.hide()
                }
            }
        }

        // 分隔线
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            Layout.leftMargin: 12
            Layout.rightMargin: 12
            color: root.colors.border
            opacity: 0.6
        }

        // ===== 中部模块（可纵向滚动，防最小高度溢出）=====
        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: modulesCol.implicitHeight
            clip: true
            flickableDirection: Flickable.VerticalFlick
            boundsBehavior: Flickable.StopAtBounds

            ColumnLayout {
                id: modulesCol
                anchors.left: parent.left
                anchors.right: parent.right
                spacing: 2

                Repeater {
                    model: root.modules

                    delegate: Item {
                        id: cell
                        Layout.fillWidth: true
                        Layout.preferredHeight: 58

                        readonly property bool isActive: root.currentModule === modelData.key

                        // 行背景
                        Rectangle {
                            anchors.fill: parent
                            anchors.leftMargin: 6
                            anchors.rightMargin: 6
                            radius: 8
                            color: cell.isActive ? root.colors.hover
                                  : (cellMa.containsMouse ? root.colors.hover : "transparent")
                            Behavior on color { ColorAnimation { duration: 120 } }
                        }

                        // 左侧选中竖条
                        Rectangle {
                            anchors.left: parent.left
                            anchors.leftMargin: 6
                            anchors.verticalCenter: parent.verticalCenter
                            width: 3
                            height: 26
                            radius: 1.5
                            color: root.colors.accent
                            visible: cell.isActive
                        }

                        Column {
                            anchors.centerIn: parent
                            spacing: 3

                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.icon
                                font.pixelSize: 20
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.label
                                color: cell.isActive ? root.colors.fg : root.colors.fgSec
                                font.pixelSize: 10
                            }
                        }

                        MouseArea {
                            id: cellMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.navClicked(modelData.key)
                            onEntered: ToolTip.show(modelData.label, 2000)
                            onExited: ToolTip.hide()
                        }
                    }
                }
            }
        }

        // 分隔线
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            Layout.leftMargin: 12
            Layout.rightMargin: 12
            color: root.colors.border
            opacity: 0.6
        }

        // ===== 底部设置 =====
        Item {
            id: settingsCell
            Layout.fillWidth: true
            Layout.preferredHeight: 58

            readonly property bool isActive: root.currentModule === "settings"

            Rectangle {
                anchors.fill: parent
                anchors.leftMargin: 6
                anchors.rightMargin: 6
                radius: 8
                color: settingsCell.isActive ? root.colors.hover
                      : (settingsMa.containsMouse ? root.colors.hover : "transparent")
                Behavior on color { ColorAnimation { duration: 120 } }
            }
            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                width: 3
                height: 26
                radius: 1.5
                color: root.colors.accent
                visible: settingsCell.isActive
            }
            Column {
                anchors.centerIn: parent
                spacing: 3
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "⚙️"
                    font.pixelSize: 20
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr("设置")
                    color: settingsCell.isActive ? root.colors.fg : root.colors.fgSec
                    font.pixelSize: 10
                }
            }
            MouseArea {
                id: settingsMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.navClicked("settings")
                onEntered: ToolTip.show(qsTr("设置"), 2000)
                onExited: ToolTip.hide()
            }
        }

        Item { Layout.preferredHeight: 8; Layout.fillWidth: true }
    }
}
