// StatusBadge.qml — 状态徽章（胶囊形）
//
// 职责：
// - 小胶囊形 Rectangle，圆角全（radius = height/2）
// - property string status：running/stopped/error/pending（颜色映射）
// - property string text：徽章文字
// - 内含小圆点 + text

import QtQuick

Item {
    id: root
    implicitHeight: 22
    implicitWidth: row.implicitWidth + 20

    property string status: "running"   // running/stopped/error/pending
    property string text: ""
    property var colors: ({ fg: "#e4e4ef" })

    // status -> 颜色映射
    readonly property var statusColors: ({
        running: "#22c55e",   // 绿
        stopped: "#6b7280",   // 灰
        error:   "#ef4444",   // 红
        pending: "#eab308"    // 黄
    })
    readonly property color currentColor: root.statusColors[root.status] || "#6b7280"

    // 背景浅色填充
    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: root.currentColor
        opacity: 0.16
    }
    // 描边
    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: "transparent"
        border.color: root.currentColor
        border.width: 1
        opacity: 0.55
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6

        Rectangle {
            width: 6
            height: 6
            radius: 3
            color: root.currentColor
            anchors.verticalCenter: parent.verticalCenter
        }

        Text {
            text: root.text
            color: root.currentColor
            font.pixelSize: 11
            font.bold: true
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
