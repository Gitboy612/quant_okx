// LogsPage.qml — 日志中心（操作日志 / API 调用日志 Tab 切换 + 筛选）
//
// 职责：
// - 顶部 Tab 切换：操作日志 / API 调用日志
// - 操作日志 Tab：logService.listLogs() → DataTable(id/action/target_type/detail/ip_address/created_at)，筛选 action
// - API 日志 Tab：logService.listApiLogs() → DataTable(account_name/endpoint/method/response_code/status/created_at)，按策略实例筛选

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

    // 当前 Tab：0=操作日志, 1=API 日志
    property int currentTab: 0

    // 数据缓存
    property var opLogs: []
    property var apiLogs: []
    property var instances: []

    // 筛选状态
    property string opActionFilter: ""        // 操作日志 action 过滤
    property int apiStrategyFilter: -1        // API 日志策略实例过滤

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
                    text: qsTr("日志中心")
                    color: root.colors.fg
                    font.pixelSize: 22
                    font.bold: true
                }
                Text {
                    text: currentTab === 0
                          ? qsTr("操作日志 · 共 %1 条").arg(filteredOpLogs.length)
                          : qsTr("API 调用日志 · 共 %1 条").arg(filteredApiLogs.length)
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
                    onClicked: reloadCurrent()
                }
            }
        }

        // ===== Tab 切换栏 =====
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 24
            Layout.rightMargin: 24
            spacing: 8

            // 操作日志 Tab
            Rectangle {
                Layout.preferredWidth: 120
                Layout.preferredHeight: 36
                radius: 8
                color: root.currentTab === 0 ? root.colors.accent : "transparent"
                border.color: root.currentTab === 0 ? root.colors.accent : root.colors.border
                border.width: 1
                Behavior on color { ColorAnimation { duration: 120 } }
                Text {
                    anchors.centerIn: parent
                    text: qsTr("操作日志")
                    color: root.currentTab === 0 ? "#ffffff" : root.colors.fg
                    font.pixelSize: 13
                    font.bold: root.currentTab === 0
                }
                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        root.currentTab = 0
                        reloadCurrent()
                    }
                }
            }

            // API 调用日志 Tab
            Rectangle {
                Layout.preferredWidth: 140
                Layout.preferredHeight: 36
                radius: 8
                color: root.currentTab === 1 ? root.colors.accent : "transparent"
                border.color: root.currentTab === 1 ? root.colors.accent : root.colors.border
                border.width: 1
                Behavior on color { ColorAnimation { duration: 120 } }
                Text {
                    anchors.centerIn: parent
                    text: qsTr("API 调用日志")
                    color: root.currentTab === 1 ? "#ffffff" : root.colors.fg
                    font.pixelSize: 13
                    font.bold: root.currentTab === 1
                }
                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        root.currentTab = 1
                        reloadCurrent()
                    }
                }
            }

            // 弹簧
            Item { Layout.fillWidth: true }

            // 筛选器（根据 Tab 不同）
            // 操作日志：action 筛选输入
            Rectangle {
                Layout.preferredWidth: 200
                Layout.preferredHeight: 34
                radius: 6
                color: root.colors.card
                border.color: root.colors.border
                border.width: 1
                visible: root.currentTab === 0

                TextInput {
                    id: actionFilterInput
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    verticalAlignment: Text.AlignVCenter
                    color: root.colors.fg
                    font.pixelSize: 12
                    selectByMouse: true
                    clip: true
                    onTextChanged: root.opActionFilter = text.trim()
                    Text {
                        anchors.fill: parent
                        verticalAlignment: Text.AlignVCenter
                        text: qsTr("筛选 action（如 login）")
                        color: root.colors.fgSec
                        font.pixelSize: 12
                        visible: !actionFilterInput.text.length
                    }
                }
            }

            // API 日志：策略实例筛选下拉
            Rectangle {
                Layout.preferredWidth: 220
                Layout.preferredHeight: 34
                radius: 6
                color: root.colors.card
                border.color: root.colors.border
                border.width: 1
                visible: root.currentTab === 1

                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    verticalAlignment: Text.AlignVCenter
                    text: root.apiStrategyFilter < 0 ? qsTr("全部策略实例")
                          : instanceName(root.apiStrategyFilter)
                    color: root.colors.fg
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: "▾"
                    color: root.colors.fgSec
                    font.pixelSize: 10
                }
                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: strategyMenu.open()
                }
                Menu {
                    id: strategyMenu
                    width: 220
                    MenuItem {
                        text: qsTr("全部策略实例")
                        onTriggered: {
                            root.apiStrategyFilter = -1
                            loadApiLogs()
                        }
                    }
                    MenuSeparator {}
                    Repeater {
                        model: root.instances
                        delegate: MenuItem {
                            text: modelData.name + " · " + (modelData.symbol || "")
                            onTriggered: {
                                root.apiStrategyFilter = modelData.id
                                loadApiLogs()
                            }
                        }
                    }
                }
            }
        }

        // ===== 日志表格区 =====
        WorkspaceCard {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 24
            Layout.rightMargin: 24
            Layout.bottomMargin: 16
            title: currentTab === 0 ? qsTr("操作日志") : qsTr("API 调用日志")
            subtitle: currentTab === 0 ? qsTr("用户操作审计记录") : qsTr("策略调用的 OKX API 记录")
            colors: root.colors

            // 操作日志表格
            DataTable {
                anchors.fill: parent
                colors: root.colors
                visible: root.currentTab === 0
                columns: [
                    { title: qsTr("ID"),     field: "id",          width: 70  },
                    { title: qsTr("动作"),   field: "action",      width: 120 },
                    { title: qsTr("目标类型"), field: "target_type", width: 110 },
                    { title: qsTr("目标ID"), field: "target_id",   width: 90  },
                    { title: qsTr("详情"),   field: "detail",      width: 220 },
                    { title: qsTr("IP"),     field: "ip_address",  width: 120 },
                    { title: qsTr("时间"),   field: "created_at",  width: 180 }
                ]
                rows: filteredOpLogs
                onRowClicked: function(rowData) {
                    console.log("[Logs] 操作日志行点击: " + JSON.stringify(rowData))
                }
            }

            // API 日志表格
            DataTable {
                anchors.fill: parent
                colors: root.colors
                visible: root.currentTab === 1
                columns: [
                    { title: qsTr("ID"),     field: "id",           width: 70  },
                    { title: qsTr("账户"),   field: "account_name", width: 120 },
                    { title: qsTr("接口"),   field: "endpoint",     width: 200 },
                    { title: qsTr("方法"),   field: "method",       width: 70  },
                    { title: qsTr("响应码"), field: "response_code",width: 90  },
                    { title: qsTr("状态"),   field: "status",       width: 100 },
                    { title: qsTr("时间"),   field: "created_at",   width: 180 }
                ]
                rows: filteredApiLogs
                onRowClicked: function(rowData) {
                    console.log("[Logs] API 日志行点击: " + JSON.stringify(rowData))
                }
            }
        }
    }

    // ===== 衍生：过滤后的日志 =====
    readonly property var filteredOpLogs: {
        if (root.opActionFilter.length === 0) return root.opLogs
        var out = []
        for (var i = 0; i < root.opLogs.length; i++) {
            var a = root.opLogs[i].action || ""
            if (a.indexOf(root.opActionFilter) >= 0) out.push(root.opLogs[i])
        }
        return out
    }

    readonly property var filteredApiLogs: root.apiLogs

    // ===== 工具函数 =====
    function instanceName(sid) {
        for (var i = 0; i < instances.length; i++) {
            if (instances[i].id === sid) return instances[i].name
        }
        return qsTr("(未知实例)")
    }

    // ===== 数据加载 =====
    function loadOpLogs() {
        try {
            var logs = logService.listLogs()
            root.opLogs = logs || []
        } catch (e) {
            console.warn("[Logs] listLogs 异常: " + e)
        }
    }

    function loadApiLogs() {
        try {
            var logs
            if (root.apiStrategyFilter > 0) {
                logs = logService.listApiLogsByStrategy(root.apiStrategyFilter)
            } else {
                logs = logService.listApiLogs()
            }
            root.apiLogs = logs || []
        } catch (e) {
            console.warn("[Logs] listApiLogs 异常: " + e)
        }
    }

    function loadInstances() {
        try {
            var insts = strategyService.listInstances()
            root.instances = insts || []
        } catch (e) {
            console.warn("[Logs] listInstances 异常: " + e)
        }
    }

    function reloadCurrent() {
        if (root.currentTab === 0) {
            loadOpLogs()
        } else {
            loadApiLogs()
        }
    }

    Component.onCompleted: {
        loadInstances()
        loadOpLogs()
        loadApiLogs()
    }
}
