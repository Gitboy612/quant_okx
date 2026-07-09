// AccountsPage.qml — 账户管理（卡片网格，M365 文档卡风格）
//
// 职责：
// - onCompleted: accountService.listAccounts()
// - 顶部：标题"账户管理" + "新建账户"按钮
// - 卡片网格：每卡 name/exchange/StatusBadge(is_active?running:stopped)/
//   trade_mode/api_key_masked/created_at，底部"编辑/删除"按钮
// - 空状态占位

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
    signal newAccountRequested()
    signal editAccountRequested(var accountId)
    signal deleteAccountRequested(var accountId)

    // 数据缓存
    property var accounts: []

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
                        text: qsTr("账户管理")
                        color: root.colors.fg
                        font.pixelSize: 22
                        font.bold: true
                    }
                    Text {
                        text: qsTr("共 %1 个交易账户").arg(accounts.length)
                        color: root.colors.fgSec
                        font.pixelSize: 12
                    }
                }

                // "新建账户"按钮
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
                            text: qsTr("新建账户")
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
                            console.log("[Accounts] 新建账户")
                            root.newAccountRequested()
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
                visible: accounts.length === 0
                radius: 12
                color: root.colors.card
                border.color: root.colors.border
                border.width: 1

                Column {
                    anchors.centerIn: parent
                    spacing: 12
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "👛"
                        font.pixelSize: 40
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: qsTr("暂无账户")
                        color: root.colors.fg
                        font.pixelSize: 16
                        font.bold: true
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: qsTr("点击右上角「新建账户」接入交易所 API")
                        color: root.colors.fgSec
                        font.pixelSize: 12
                    }
                }
            }

            // ===== 账户卡片网格 =====
            Flow {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                spacing: 16
                visible: accounts.length > 0

                Repeater {
                    model: root.accounts

                    delegate: Rectangle {
                        width: 320
                        height: 210
                        radius: 12
                        color: root.colors.card
                        border.color: root.colors.border
                        border.width: 1

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

                            // 顶部：账户名 + 状态
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Rectangle {
                                    width: 36; height: 36
                                    radius: 8
                                    color: root.colors.accent
                                    Layout.alignment: Qt.AlignVCenter
                                    Text {
                                        anchors.centerIn: parent
                                        text: (modelData.name || "?").charAt(0).toUpperCase()
                                        color: "#ffffff"
                                        font.pixelSize: 16
                                        font.bold: true
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData.name || qsTr("(未命名)")
                                        color: root.colors.fg
                                        font.pixelSize: 15
                                        font.bold: true
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData.exchange || "OKX"
                                        color: root.colors.fgSec
                                        font.pixelSize: 11
                                        elide: Text.ElideRight
                                    }
                                }

                                StatusBadge {
                                    status: modelData.is_active ? "running" : "stopped"
                                    text: modelData.is_active ? qsTr("启用") : qsTr("停用")
                                    colors: root.colors
                                    Layout.alignment: Qt.AlignVCenter
                                }
                            }

                            // 交易模式
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Text {
                                    text: qsTr("交易模式")
                                    color: root.colors.fgSec
                                    font.pixelSize: 11
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: tradeModeText(modelData.trade_mode)
                                    color: root.colors.fg
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                    horizontalAlignment: Text.AlignRight
                                }
                            }

                            // API Key
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Text {
                                    text: qsTr("API Key")
                                    color: root.colors.fgSec
                                    font.pixelSize: 11
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.api_key_masked || "****"
                                    color: root.colors.fg
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                    horizontalAlignment: Text.AlignRight
                                }
                            }

                            // 创建时间
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Text {
                                    text: qsTr("创建时间")
                                    color: root.colors.fgSec
                                    font.pixelSize: 11
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: fmtTime(modelData.created_at)
                                    color: root.colors.fg
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                    horizontalAlignment: Text.AlignRight
                                }
                            }

                            // 弹簧
                            Item { Layout.fillHeight: true }

                            // 底部按钮组
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                // 编辑按钮
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 30
                                    radius: 6
                                    color: editMa.containsMouse ? root.colors.hover : "transparent"
                                    border.color: root.colors.border
                                    border.width: 1
                                    Behavior on color { ColorAnimation { duration: 120 } }
                                    Text {
                                        anchors.centerIn: parent
                                        text: qsTr("编辑")
                                        color: root.colors.fg
                                        font.pixelSize: 12
                                        font.bold: true
                                    }
                                    MouseArea {
                                        id: editMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            console.log("[Accounts] 编辑账户 id=" + modelData.id)
                                            root.editAccountRequested(modelData.id)
                                        }
                                    }
                                }

                                // 删除按钮
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 30
                                    radius: 6
                                    color: delMa.containsMouse ? "#3a1d1d" : "transparent"
                                    border.color: delMa.containsMouse ? "#ef4444" : root.colors.border
                                    border.width: 1
                                    Behavior on color { ColorAnimation { duration: 120 } }
                                    Text {
                                        anchors.centerIn: parent
                                        text: qsTr("删除")
                                        color: delMa.containsMouse ? "#ef4444" : root.colors.fg
                                        font.pixelSize: 12
                                        font.bold: true
                                    }
                                    MouseArea {
                                        id: delMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            console.log("[Accounts] 删除账户 id=" + modelData.id)
                                            root.deleteAccountRequested(modelData.id)
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
    function tradeModeText(m) {
        if (m === "live") return qsTr("实盘")
        if (m === "demo") return qsTr("模拟")
        return m || "-"
    }

    function fmtTime(s) {
        if (!s) return "-"
        // ISO 字符串取前 16 位（YYYY-MM-DD HH:MM）
        return String(s).substring(0, 16).replace("T", " ")
    }

    // ===== 数据加载 =====
    function loadData() {
        try {
            var accs = accountService.listAccounts()
            root.accounts = accs || []
        } catch (e) {
            console.warn("[Accounts] listAccounts 异常: " + e)
        }
    }

    Component.onCompleted: loadData()
}
