// WorkspaceCard.qml — 统一卡片组件
//
// 职责：
// - 圆角 12px 卡片，背景随主题，轻投影（悬停时显现）
// - 悬停抬升（scale 1.02，Behavior 150ms）
// - 顶部标题区（title + subtitle + 可选 headerAction 槽）
// - 内容区 default property alias content：外部放入的子项进入 contentHolder

import QtQuick
import QtQuick.Layouts

Item {
    id: root
    implicitWidth: 320
    implicitHeight: 200

    property string title: ""
    property string subtitle: ""
    property var colors: ({
        card: "#2a2a3a",
        fg: "#e4e4ef",
        fgSec: "#9999aa",
        accent: "#6366f1",
        border: "#33334a"
    })

    // 默认内容槽：外部直接放入的子项会进入 contentHolder
    default property alias content: contentHolder.children
    // 头部右侧操作槽（可选）
    property alias headerAction: actionSlot.children

    property bool hovered: false
    scale: hovered ? 1.02 : 1.0
    Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutQuad } }

    // 悬停时显现的投影（无模糊，偏移 + 低透明黑）
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
        id: cardBody
        anchors.fill: parent
        radius: 12
        color: root.colors.card
        border.color: root.colors.border
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            // ===== 头部：标题/副标题 + 操作槽 =====
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Text {
                        text: root.title
                        color: root.colors.fg
                        font.pixelSize: 15
                        font.bold: true
                        visible: root.title.length > 0
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }

                    Text {
                        text: root.subtitle
                        color: root.colors.fgSec
                        font.pixelSize: 11
                        visible: root.subtitle.length > 0
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                }

                // 右侧操作槽（可选塞按钮）
                Item {
                    id: actionSlot
                    Layout.alignment: Qt.AlignVCenter | Qt.AlignRight
                    implicitWidth: children.length ? childrenRect.width : 0
                    implicitHeight: children.length ? childrenRect.height : 0
                }
            }

            // ===== 内容区 =====
            Item {
                id: contentHolder
                Layout.fillWidth: true
                Layout.fillHeight: true
            }
        }
    }

    // 悬停检测：acceptedButtons=NoButton 不拦截点击，仅做 hover 抬升
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
        onEntered: root.hovered = true
        onExited: root.hovered = false
    }
}
