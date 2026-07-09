// KpiCard.qml — KPI 卡片（复用 WorkspaceCard 视觉风格）
//
// 职责：
// - property string label  ：上方小字灰色标签
// - property string value  ：中部大字粗体数值
// - property string delta  ：涨跌（如 "+12.3%" / "-4.2%"，以 '-' 开头判定为跌）
// - property string icon   ：可选 emoji 图标
// - 底部迷你 sparkline（Canvas 占位折线，涨跌配色）

import QtQuick
import QtQuick.Layouts

Item {
    id: root
    implicitWidth: 220
    implicitHeight: 150

    property string label: ""
    property string value: ""
    property string delta: ""
    property string icon: ""
    property var colors: ({
        card: "#2a2a3a",
        fg: "#e4e4ef",
        fgSec: "#9999aa",
        accent: "#6366f1",
        border: "#33334a"
    })

    property bool hovered: false
    scale: hovered ? 1.02 : 1.0
    Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutQuad } }

    // 涨跌判定与配色
    readonly property bool deltaNegative: delta.length > 0 && delta.charAt(0) === '-'
    readonly property color deltaColor: deltaNegative ? "#ef4444" : "#22c55e"
    readonly property string deltaArrow: deltaNegative ? "▼" : "▲"

    // 投影
    Rectangle {
        z: -1
        anchors.fill: parent
        anchors.topMargin: 3
        color: "#000000"
        opacity: root.hovered ? 0.22 : 0.10
        radius: 12
        Behavior on opacity { NumberAnimation { duration: 150 } }
    }

    Rectangle {
        anchors.fill: parent
        radius: 12
        color: root.colors.card
        border.color: root.colors.border
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 6

            // 标签 + 图标
            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                Text {
                    text: root.icon
                    font.pixelSize: 14
                    visible: root.icon.length > 0
                }

                Text {
                    text: root.label
                    color: root.colors.fgSec
                    font.pixelSize: 12
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }

            // 数值
            Text {
                text: root.value
                color: root.colors.fg
                font.pixelSize: 26
                font.bold: true
                Layout.fillWidth: true
                elide: Text.ElideRight
            }

            // 涨跌
            Row {
                Layout.fillWidth: true
                spacing: 4
                visible: root.delta.length > 0

                Text {
                    text: root.deltaArrow
                    color: root.deltaColor
                    font.pixelSize: 11
                }
                Text {
                    text: root.delta
                    color: root.deltaColor
                    font.pixelSize: 11
                    font.bold: true
                }
            }

            // 迷你 sparkline（占位折线）
            Canvas {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredHeight: 24
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    ctx.strokeStyle = root.deltaColor
                    ctx.lineWidth = 1.5
                    ctx.lineJoin = "round"
                    var w = width
                    var h = height
                    var pts = [0.20, 0.55, 0.38, 0.72, 0.50, 0.85, 0.62]
                    ctx.beginPath()
                    for (var i = 0; i < pts.length; i++) {
                        var x = (i / (pts.length - 1)) * w
                        var y = h - pts[i] * (h - 2) - 1
                        if (i === 0) ctx.moveTo(x, y)
                        else ctx.lineTo(x, y)
                    }
                    ctx.stroke()
                }
                Connections {
                    target: root
                    function onDeltaNegativeChanged() { requestPaint() }
                }
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
        onEntered: root.hovered = true
        onExited: root.hovered = false
    }
}
