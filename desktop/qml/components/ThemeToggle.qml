// ThemeToggle.qml — 主题切换按钮（太阳/月亮）
//
// 职责：
// - 显示太阳/月亮图标（Canvas 绘制）
// - 点击向外发 themeChanged(nextTheme) 信号，由 main.qml 更新 root.theme
// - 本组件不持久化，持久化（QSettings）由 main.qml 侧 Python 桥接完成（Task 2/3）

import QtQuick
import QtQuick.Controls

Item {
    id: root
    implicitWidth: 36
    implicitHeight: 36

    // 当前主题（仅用于显示图标，由 main.qml 单向绑定注入）
    property string theme: "dark"
    // 颜色板（由 main.qml 注入）
    property var colors: ({
        fg: "#e4e4ef",
        hover: "#33334a"
    })

    // 注意：不能命名为 themeChanged——property theme 会自动生成同名信号，QML 禁止覆盖
    signal themeSwitched(string theme)

    // 悬停背景
    Rectangle {
        anchors.fill: parent
        radius: 8
        color: mouseArea.containsMouse ? root.colors.hover : "transparent"
        Behavior on color { ColorAnimation { duration: 120 } }
    }

    Canvas {
        anchors.centerIn: parent
        width: 20
        height: 20
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.strokeStyle = root.colors.fg
            ctx.fillStyle = root.colors.fg
            ctx.lineWidth = 1.6
            ctx.lineCap = "round"

            if (root.theme === "dark") {
                // 月亮：带缺口的圆弧
                ctx.beginPath()
                ctx.arc(10, 10, 6.5, Math.PI * 0.25, Math.PI * 1.75)
                ctx.stroke()
            } else {
                // 太阳：中心圆 + 八道光线
                ctx.beginPath()
                ctx.arc(10, 10, 4.5, 0, Math.PI * 2)
                ctx.stroke()
                for (var i = 0; i < 8; i++) {
                    var a = i * Math.PI / 4
                    ctx.beginPath()
                    ctx.moveTo(10 + Math.cos(a) * 7, 10 + Math.sin(a) * 7)
                    ctx.lineTo(10 + Math.cos(a) * 9, 10 + Math.sin(a) * 9)
                    ctx.stroke()
                }
            }
        }
        // 主题 / 颜色变化时重绘
        Connections {
            target: root
            function onThemeChanged() { requestPaint() }
            function onColorsChanged() { requestPaint() }
        }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            // 只发信号，不自行改 theme；由 main.qml 统一更新后回灌
            var next = root.theme === "dark" ? "light" : "dark"
            root.themeSwitched(next)
        }
    }

    ToolTip.visible: mouseArea.containsMouse
    ToolTip.delay: 400
    ToolTip.text: root.theme === "dark" ? qsTr("切换到浅色主题") : qsTr("切换到深色主题")
}
