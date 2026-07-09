// OrdersPage.qml — 订单管理（筛选侧栏 + 卡片容器内表格）
//
// 职责：
// - onCompleted: orderService.listOrders() + accountService.listAccounts()
// - 左侧筛选侧栏（宽 200）：账户过滤、状态过滤、数量限制输入
// - 右侧 WorkspaceCard 内 DataTable：列 id/symbol/side/price/quantity/status/created_at
// - 筛选变化重新调 orderService.listOrdersByAccount(accId) 或本地过滤

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
    property var accounts: []
    property var orders: []

    // 筛选状态
    property int filterAccountId: -1   // -1 = 全部账户
    property string filterStatus: ""   // 空 = 全部状态
    property int filterLimit: 100

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ===== 左侧筛选侧栏 =====
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 220
            Layout.leftMargin: 16
            Layout.topMargin: 16
            Layout.bottomMargin: 16
            color: root.colors.card
            border.color: root.colors.border
            border.width: 1
            radius: 12

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 16

                Text {
                    text: qsTr("筛选")
                    color: root.colors.fg
                    font.pixelSize: 14
                    font.bold: true
                    Layout.fillWidth: true
                }

                // 账户过滤
                Text {
                    text: qsTr("账户")
                    color: root.colors.fgSec
                    font.pixelSize: 11
                    Layout.fillWidth: true
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 34
                    radius: 6
                    color: root.colors.bg
                    border.color: root.colors.border
                    border.width: 1

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        verticalAlignment: Text.AlignVCenter
                        text: filterAccountId < 0 ? qsTr("全部账户")
                              : accountName(filterAccountId)
                        color: root.colors.fg
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }

                    // 下拉箭头
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        text: "▾"
                        color: root.colors.fgSec
                        font.pixelSize: 10
                    }

                    MouseArea {
                        id: accountFilterMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: accountMenu.open()
                    }

                    Menu {
                        id: accountMenu
                        width: 200

                        MenuItem {
                            text: qsTr("全部账户")
                            onTriggered: {
                                root.filterAccountId = -1
                                reloadOrders()
                            }
                        }
                        MenuSeparator {}
                        Repeater {
                            model: root.accounts
                            delegate: MenuItem {
                                text: modelData.name + " · " + modelData.exchange
                                onTriggered: {
                                    root.filterAccountId = modelData.id
                                    reloadOrders()
                                }
                            }
                        }
                    }
                }

                // 状态过滤
                Text {
                    text: qsTr("状态")
                    color: root.colors.fgSec
                    font.pixelSize: 11
                    Layout.fillWidth: true
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Repeater {
                        model: [
                            { key: "",         label: qsTr("全部") },
                            { key: "live",     label: qsTr("待成交") },
                            { key: "filled",   label: qsTr("已成交") },
                            { key: "canceled", label: qsTr("已撤销") }
                        ]

                        delegate: Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 28
                            radius: 6
                            color: root.filterStatus === modelData.key
                                   ? root.colors.accent
                                   : (statMa.containsMouse ? root.colors.hover : "transparent")
                            border.color: root.colors.border
                            border.width: root.filterStatus === modelData.key ? 0 : 1
                            Behavior on color { ColorAnimation { duration: 120 } }

                            Text {
                                anchors.centerIn: parent
                                text: modelData.label
                                color: root.filterStatus === modelData.key ? "#ffffff" : root.colors.fg
                                font.pixelSize: 12
                                font.bold: root.filterStatus === modelData.key
                            }

                            MouseArea {
                                id: statMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.filterStatus = modelData.key
                                }
                            }
                        }
                    }
                }

                // 数量限制
                Text {
                    text: qsTr("数量限制")
                    color: root.colors.fgSec
                    font.pixelSize: 11
                    Layout.fillWidth: true
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 34
                    radius: 6
                    color: root.colors.bg
                    border.color: root.colors.border
                    border.width: 1

                    TextInput {
                        id: limitInput
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        verticalAlignment: Text.AlignVCenter
                        color: root.colors.fg
                        font.pixelSize: 12
                        text: String(root.filterLimit)
                        selectByMouse: true
                        validator: IntValidator { bottom: 1; top: 1000 }
                        onActiveFocusChanged: {
                            if (!activeFocus) {
                                var n = parseInt(text)
                                if (!isNaN(n) && n > 0) {
                                    root.filterLimit = n
                                    reloadOrders()
                                } else {
                                    text = String(root.filterLimit)
                                }
                            }
                        }
                    }
                }

                // 弹簧
                Item { Layout.fillHeight: true }

                // 刷新按钮
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 34
                    radius: 6
                    color: refreshMa.containsMouse ? root.colors.hover : "transparent"
                    border.color: root.colors.border
                    border.width: 1
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Text {
                        anchors.centerIn: parent
                        text: qsTr("↻ 刷新")
                        color: root.colors.fg
                        font.pixelSize: 12
                        font.bold: true
                    }
                    MouseArea {
                        id: refreshMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: reloadOrders()
                    }
                }
            }
        }

        // ===== 右侧订单表格卡 =====
        WorkspaceCard {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.rightMargin: 16
            Layout.topMargin: 16
            Layout.bottomMargin: 16
            title: qsTr("订单列表")
            subtitle: qsTr("共 %1 条订单").arg(filteredOrders.length)
            colors: root.colors

            DataTable {
                anchors.fill: parent
                colors: root.colors
                columns: [
                    { title: qsTr("ID"),     field: "id",         width: 70  },
                    { title: qsTr("币种"),   field: "symbol",     width: 130 },
                    { title: qsTr("方向"),   field: "side",       width: 70  },
                    { title: qsTr("价格"),   field: "price",      width: 110 },
                    { title: qsTr("数量"),   field: "quantity",   width: 100 },
                    { title: qsTr("已成交"), field: "filled_quantity", width: 100 },
                    { title: qsTr("状态"),   field: "status",     width: 100 },
                    { title: qsTr("时间"),   field: "created_at", width: 180 }
                ]
                rows: filteredOrders
                onRowClicked: function(rowData) {
                    console.log("[Orders] 行点击: " + JSON.stringify(rowData))
                }
            }
        }
    }

    // ===== 衍生：状态过滤后的订单 =====
    readonly property var filteredOrders: {
        var out = []
        for (var i = 0; i < orders.length; i++) {
            var o = orders[i]
            if (filterStatus.length > 0 && o.status !== filterStatus) continue
            out.push(o)
        }
        return out
    }

    // ===== 工具函数 =====
    function accountName(accId) {
        for (var i = 0; i < accounts.length; i++) {
            if (accounts[i].id === accId) return accounts[i].name
        }
        return qsTr("(未知账户)")
    }

    // ===== 数据加载 =====
    function reloadOrders() {
        try {
            var ords
            if (root.filterAccountId > 0) {
                ords = orderService.listOrdersByAccount(root.filterAccountId)
            } else {
                ords = orderService.listOrdersWithLimit(root.filterLimit)
            }
            root.orders = ords || []
        } catch (e) {
            console.warn("[Orders] reloadOrders 异常: " + e)
        }
    }

    function loadAccounts() {
        try {
            var accs = accountService.listAccounts()
            root.accounts = accs || []
        } catch (e) {
            console.warn("[Orders] listAccounts 异常: " + e)
        }
    }

    Component.onCompleted: {
        loadAccounts()
        reloadOrders()
    }
}
