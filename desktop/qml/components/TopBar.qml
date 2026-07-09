// TopBar.qml — 顶栏功能区（Adobe/M365 式）
//
// 职责（仅功能区，不含窗口控制——窗口控制由 Task 1 标题栏负责）：
// - 左侧：全局搜索框（TextField + 搜索图标，placeholder "搜索策略/订单/币种"）
//         回车发 searchSubmitted(text)
// - 右侧：账户切换器（发 accountSwitcherClicked）
//         通知铃铛（Canvas 绘制 + 红点未读数，发 notificationClicked）
//         主题切换按钮（ThemeToggle，转发 themeChanged）
//
// 说明：本 TopBar 作为标题栏下方的第二行（56px），与 Task 1 标题栏（40px）叠加。

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    implicitHeight: 56
    color: colors.bg

    property var colors: ({
        bg: "#1e1e2e",
        card: "#2a2a3a",
        fg: "#e4e4ef",
        fgSec: "#9999aa",
        accent: "#6366f1",
        border: "#33334a",
        hover: "#33334a"
    })
    property string theme: "dark"
    property int unreadNotifications: 3

    signal searchSubmitted(string text)
    signal accountSwitcherClicked()
    signal notificationClicked()
    // 注意：不能命名为 themeChanged——property theme 会自动生成同名信号，QML 禁止覆盖
    signal themeSwitched(string theme)

    // 暴露给 main.qml 的全局快捷键 Ctrl+K 调用：聚焦搜索框并全选，便于重新输入
    function focusSearch() {
        searchInput.forceActiveFocus()
        searchInput.selectAll()
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 12
        spacing: 12

        // ===== 搜索框 =====
        Rectangle {
            Layout.preferredWidth: 360
            Layout.preferredHeight: 36
            Layout.alignment: Qt.AlignVCenter
            radius: 8
            color: root.colors.card
            border.color: root.colors.border
            border.width: 1

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 8

                Canvas {
                    Layout.preferredWidth: 16
                    Layout.preferredHeight: 16
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.reset()
                        ctx.strokeStyle = root.colors.fgSec
                        ctx.lineWidth = 1.6
                        // 放大镜圆
                        ctx.beginPath()
                        ctx.arc(6, 6, 4, 0, Math.PI * 2)
                        ctx.stroke()
                        // 把手
                        ctx.beginPath()
                        ctx.moveTo(9.2, 9.2)
                        ctx.lineTo(14, 14)
                        ctx.stroke()
                    }
                    Connections {
                        target: root
                        function onColorsChanged() { requestPaint() }
                    }
                }

                // 用 QtQuick TextInput（无原生背景），避免 Controls 原生样式与深色主题冲突
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 20
                    clip: true

                    Text {
                        anchors.fill: parent
                        verticalAlignment: Text.AlignVCenter
                        text: qsTr("搜索策略/订单/币种")
                        color: root.colors.fgSec
                        font.pixelSize: 13
                        visible: searchInput.text.length === 0
                    }

                    TextInput {
                        id: searchInput
                        anchors.fill: parent
                        verticalAlignment: Text.AlignVCenter
                        color: root.colors.fg
                        font.pixelSize: 13
                        selectByMouse: true
                        onAccepted: root.searchSubmitted(text)
                    }
                }
            }
        }

        // 弹簧
        Item { Layout.fillWidth: true }

        // ===== 账户切换器 =====
        Rectangle {
            Layout.preferredHeight: 36
            Layout.preferredWidth: accountRow.implicitWidth + 24
            Layout.alignment: Qt.AlignVCenter
            radius: 8
            color: accountMa.containsMouse ? root.colors.hover : "transparent"
            border.color: root.colors.border
            border.width: 1
            Behavior on color { ColorAnimation { duration: 120 } }

            Row {
                id: accountRow
                anchors.centerIn: parent
                spacing: 8

                Rectangle {
                    width: 18
                    height: 18
                    radius: 9
                    color: root.colors.accent
                    anchors.verticalCenter: parent.verticalCenter
                    Text {
                        anchors.centerIn: parent
                        text: "M"
                        color: "#ffffff"
                        font.pixelSize: 10
                        font.bold: true
                    }
                }
                Text {
                    text: qsTr("主账户")
                    color: root.colors.fg
                    font.pixelSize: 13
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: "▾"
                    color: root.colors.fgSec
                    font.pixelSize: 10
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            MouseArea {
                id: accountMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.accountSwitcherClicked()
            }
        }

        // ===== 通知铃铛 =====
        Item {
            Layout.preferredWidth: 36
            Layout.preferredHeight: 36
            Layout.alignment: Qt.AlignVCenter

            Canvas {
                anchors.centerIn: parent
                width: 22
                height: 22
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    ctx.fillStyle = root.colors.fg
                    // 铃铛主体：底边 + 两侧 + 顶部圆弧
                    ctx.beginPath()
                    ctx.moveTo(5, 16)
                    ctx.lineTo(5, 10)
                    ctx.arc(11, 10, 6, Math.PI, 0, false)
                    ctx.lineTo(17, 16)
                    ctx.closePath()
                    ctx.fill()
                    // 底部小舌头
                    ctx.beginPath()
                    ctx.arc(11, 17.6, 1.6, 0, Math.PI * 2)
                    ctx.fill()
                }
                Connections {
                    target: root
                    function onColorsChanged() { requestPaint() }
                }
            }

            // 红点未读数
            Rectangle {
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.topMargin: 1
                anchors.rightMargin: 1
                width: 16
                height: 16
                radius: 8
                color: "#ef4444"
                visible: root.unreadNotifications > 0
                border.color: root.colors.bg
                border.width: 1.5
                Text {
                    anchors.centerIn: parent
                    text: String(root.unreadNotifications)
                    color: "#ffffff"
                    font.pixelSize: 9
                    font.bold: true
                }
            }

            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.notificationClicked()
            }
        }

        // ===== 主题切换 =====
        ThemeToggle {
            Layout.preferredWidth: 36
            Layout.preferredHeight: 36
            Layout.alignment: Qt.AlignVCenter
            theme: root.theme
            colors: root.colors
            onThemeSwitched: function(t) { root.themeSwitched(t) }
        }
    }
}
