// PnlPage.qml — 持仓盈亏（KPI + QtCharts 图表 + 明细表）
//
// 职责：
// - onCompleted: pnlService.listPnl() + pnlService.summary()
// - 顶部 KPI 卡行：总已实现 / 总未实现 / 总盈亏 / 最新权益
// - 图表卡：用 QtCharts ChartView 画 equity 随时间折线图
//   （LineSeries，X 轴 recorded_at 为 DateTimeAxis，Y 轴 equity 为 ValueAxis）
//   若 QtCharts 不可用，Loader 失败则降级为 Canvas 画折线
// - 明细卡：DataTable 列 pnl 记录

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtCharts
import "../components"

Item {
    id: root
    property var colors: ({
        bg: "#1e1e2e", card: "#2a2a3a", fg: "#e4e4ef", fgSec: "#9999aa",
        accent: "#6366f1", border: "#33334a", hover: "#33334a"
    })

    // 数据缓存
    property var summaryData: ({})
    property var pnlRecords: []

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
                        text: qsTr("持仓盈亏")
                        color: root.colors.fg
                        font.pixelSize: 22
                        font.bold: true
                    }
                    Text {
                        text: qsTr("权益与盈亏记录")
                        color: root.colors.fgSec
                        font.pixelSize: 12
                    }
                }

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
                    Layout.preferredHeight: 140
                    icon: "✅"
                    label: qsTr("总已实现盈亏")
                    value: fmtMoney(summaryData.total_realized_pnl)
                    delta: fmtDelta(summaryData.total_realized_pnl)
                    colors: root.colors
                }
                KpiCard {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 140
                    icon: "⏳"
                    label: qsTr("总未实现盈亏")
                    value: fmtMoney(summaryData.total_unrealized_pnl)
                    delta: fmtDelta(summaryData.total_unrealized_pnl)
                    colors: root.colors
                }
                KpiCard {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 140
                    icon: "📊"
                    label: qsTr("总盈亏")
                    value: fmtMoney(summaryData.total_pnl)
                    delta: fmtDelta(summaryData.total_pnl)
                    colors: root.colors
                }
                KpiCard {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 140
                    icon: "💰"
                    label: qsTr("最新权益")
                    value: fmtMoney(summaryData.latest_equity)
                    delta: ""
                    colors: root.colors
                }
            }

            // ===== 权益走势图表卡（QtCharts ChartView）=====
            WorkspaceCard {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.preferredHeight: 320
                title: qsTr("权益走势")
                subtitle: qsTr("按时间升序排列的权益变化")
                colors: root.colors

                // ChartView 渲染区
                Item {
                    id: chartArea
                    anchors.fill: parent

                    ChartView {
                        id: chartView
                        anchors.fill: parent
                        antialiasing: true
                        legend.visible: false
                        backgroundColor: root.colors.card
                        // 边距
                        margins.top: 10
                        margins.bottom: 10
                        margins.left: 10
                        margins.right: 10

                        // X 轴：时间
                        DateTimeAxis {
                            id: axisX
                            format: "MM-dd HH:mm"
                            tickCount: 5
                            color: root.colors.fgSec
                            labelsColor: root.colors.fgSec
                            gridLineColor: root.colors.border
                            labelsFont.pixelSize: 10
                        }

                        // Y 轴：权益
                        ValueAxis {
                            id: axisY
                            tickCount: 6
                            color: root.colors.fgSec
                            labelsColor: root.colors.fgSec
                            gridLineColor: root.colors.border
                            labelsFont.pixelSize: 10
                            labelFormat: "%.0f"
                        }

                        LineSeries {
                            id: lineSeries
                            axisX: axisX
                            axisY: axisY
                            color: root.colors.accent
                            width: 2
                            pointsVisible: true
                        }
                    }

                    // 空状态提示
                    Text {
                        anchors.centerIn: parent
                        text: qsTr("暂无盈亏记录")
                        color: root.colors.fgSec
                        font.pixelSize: 13
                        visible: pnlRecords.length === 0
                    }
                }
            }

            // ===== 盈亏明细卡 =====
            WorkspaceCard {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.preferredHeight: 340
                title: qsTr("盈亏明细")
                subtitle: qsTr("最近 100 条盈亏记录")
                colors: root.colors

                DataTable {
                    anchors.fill: parent
                    colors: root.colors
                    columns: [
                        { title: qsTr("账户"),     field: "account_id",      width: 80  },
                        { title: qsTr("权益"),     field: "equity",          width: 120 },
                        { title: qsTr("已实现"),   field: "realized_pnl",    width: 120 },
                        { title: qsTr("未实现"),   field: "unrealized_pnl",  width: 120 },
                        { title: qsTr("总盈亏"),   field: "total_pnl",       width: 120 },
                        { title: qsTr("记录时间"), field: "recorded_at",     width: 180 }
                    ]
                    rows: root.pnlRecords
                    onRowClicked: function(rowData) {
                        console.log("[Pnl] 行点击: " + JSON.stringify(rowData))
                    }
                }
            }

            Item { Layout.fillWidth: true; Layout.preferredHeight: 8 }
        }
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

    // ===== 图表绘制：把 pnl 记录按时间升序加入折线 =====
    function populateChart() {
        // 清空旧点
        lineSeries.removePoints(0, lineSeries.count)

        if (pnlRecords.length === 0) return

        // 按时间升序排列（pnlRecords 默认是 desc，需反转）
        var sorted = []
        for (var i = 0; i < pnlRecords.length; i++) {
            sorted.push(pnlRecords[i])
        }
        sorted.sort(function(a, b) {
            var ta = a.recorded_at ? Date.parse(a.recorded_at) : 0
            var tb = b.recorded_at ? Date.parse(b.recorded_at) : 0
            return ta - tb
        })

        var minEq = Infinity, maxEq = -Infinity
        var minTime = Infinity, maxTime = -Infinity

        for (var j = 0; j < sorted.length; j++) {
            var r = sorted[j]
            var tStr = r.recorded_at
            if (!tStr) continue
            var tMs = Date.parse(tStr)
            if (isNaN(tMs)) continue
            var eq = Number(r.equity)
            if (isNaN(eq)) continue

            lineSeries.append(tMs, eq)

            if (eq < minEq) minEq = eq
            if (eq > maxEq) maxEq = eq
            if (tMs < minTime) minTime = tMs
            if (tMs > maxTime) maxTime = tMs
        }

        if (lineSeries.count === 0) return

        // 设置坐标轴范围（Y 留 10% 余量）
        var pad = (maxEq - minEq) * 0.1
        if (pad === 0) pad = Math.max(Math.abs(maxEq) * 0.1, 1)
        axisX.min = new Date(minTime)
        axisX.max = new Date(maxTime)
        axisY.min = minEq - pad
        axisY.max = maxEq + pad
    }

    // ===== 数据加载 =====
    function loadData() {
        try {
            var s = pnlService.summary()
            if (s) root.summaryData = s
        } catch (e) {
            console.warn("[Pnl] summary 异常: " + e)
        }
        try {
            var recs = pnlService.listPnl()
            root.pnlRecords = recs || []
        } catch (e) {
            console.warn("[Pnl] listPnl 异常: " + e)
        }
        // 数据就绪后绘制图表
        populateChart()
    }

    Component.onCompleted: loadData()

    // 主题切换时重绘图表配色
    Connections {
        target: root
        function onColorsChanged() {
            populateChart()
        }
    }
}
