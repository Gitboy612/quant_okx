// DataTable.qml — 表格组件（Column + Repeater 简化版）
//
// 职责：
// - property var columns：[{title, field, width}, ...]
// - property var rows：list of dict（每行 {field: value}）
// - 表头行 + 数据行 Repeater，斑马纹，悬停高亮，点击发 rowClicked(rowData)
// - 列宽超出时横向滚动（Flickable 包裹）

import QtQuick
import QtQuick.Controls

Item {
    id: root
    implicitWidth: 600
    implicitHeight: 300

    property var columns: []
    property var rows: []
    property var colors: ({
        card: "#2a2a3a",
        fg: "#e4e4ef",
        fgSec: "#9999aa",
        accent: "#6366f1",
        border: "#33334a",
        hover: "#33334a"
    })

    signal rowClicked(var rowData)

    readonly property real rowHeight: 38
    readonly property real headerHeight: 36
    // 所有列宽之和
    readonly property real totalWidth: {
        var w = 0
        for (var i = 0; i < columns.length; i++) w += columns[i].width
        return w
    }

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: root.colors.card
        border.color: root.colors.border
        border.width: 1
        clip: true

        Flickable {
            id: flick
            anchors.fill: parent
            anchors.margins: 1
            contentWidth: Math.max(root.totalWidth, flick.width)
            contentHeight: root.headerHeight + root.rows.length * root.rowHeight
            clip: true
            flickableDirection: Flickable.HorizontalFlick
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

            Column {
                width: Math.max(root.totalWidth, flick.width)
                spacing: 0

                // ===== 表头 =====
                Rectangle {
                    width: parent.width
                    height: root.headerHeight
                    color: Qt.rgba(0, 0, 0, 0.12)

                    Row {
                        anchors.fill: parent
                        spacing: 0

                        Repeater {
                            model: root.columns
                            delegate: Rectangle {
                                width: modelData.width
                                height: root.headerHeight
                                color: "transparent"
                                Text {
                                    anchors.fill: parent
                                    anchors.leftMargin: 12
                                    verticalAlignment: Text.AlignVCenter
                                    text: modelData.title
                                    color: root.colors.fgSec
                                    font.pixelSize: 12
                                    font.bold: true
                                }
                                // 列分隔
                                Rectangle {
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 1
                                    height: parent.height * 0.6
                                    color: root.colors.border
                                }
                            }
                        }
                    }
                }

                // ===== 数据行 =====
                Repeater {
                    model: root.rows
                    delegate: Rectangle {
                        id: rowDelegate
                        // 捕获当前行对象，供内层列 delegate 通过 rowDelegate.rowData 访问
                        readonly property var rowData: modelData
                        width: parent.width
                        height: root.rowHeight
                        color: "transparent"

                        // 斑马纹（4% 黑色叠加，明暗主题通用）
                        Rectangle {
                            anchors.fill: parent
                            color: "#000000"
                            opacity: index % 2 === 1 ? 0.04 : 0.0
                        }
                        // 悬停高亮
                        Rectangle {
                            anchors.fill: parent
                            color: root.colors.hover
                            opacity: rowMa.containsMouse ? 1.0 : 0.0
                            Behavior on opacity { NumberAnimation { duration: 100 } }
                        }

                        Row {
                            anchors.fill: parent
                            spacing: 0

                            Repeater {
                                model: root.columns
                                delegate: Rectangle {
                                    width: modelData.width
                                    height: root.rowHeight
                                    color: "transparent"
                                    Text {
                                        anchors.fill: parent
                                        anchors.leftMargin: 12
                                        anchors.rightMargin: 12
                                        verticalAlignment: Text.AlignVCenter
                                        text: (rowDelegate.rowData && rowDelegate.rowData[modelData.field] !== undefined)
                                              ? String(rowDelegate.rowData[modelData.field]) : ""
                                        color: root.colors.fg
                                        font.pixelSize: 12
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }

                        MouseArea {
                            id: rowMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.rowClicked(rowDelegate.rowData)
                        }
                    }
                }
            }
        }
    }
}
