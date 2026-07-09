// LoginPage.qml — 登录页（M365/Adobe 登录风格）
//
// 职责：
// - 全屏渐变背景（colors.bg 主调）
// - 居中登录卡：Logo 区（QuantOKX 大字 + 副标题"量化交易终端"）
//   用户名输入、密码输入、登录按钮、错误提示
// - 登录按钮调 authService.login(username, password)：
//   返回非空 token → 发 loginSuccess() 信号（main.qml 接，切到 Dashboard）
//   返回空串 → 显示"用户名或密码错误"
// - 首次启动若 DB 无用户可能登录失败，底部显示友好提示
//
// 注意：登录页时 main.qml 隐藏 IconRail/TopBar，本页全屏。

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    // 颜色板由 main.qml 注入
    property var colors: ({
        bg: "#1e1e2e", card: "#2a2a3a", fg: "#e4e4ef", fgSec: "#9999aa",
        accent: "#6366f1", border: "#33334a", hover: "#33334a"
    })

    // 登录成功信号：main.qml 接，replace 到 DashboardPage
    signal loginSuccess()

    // ===== 全屏渐变背景 =====
    Rectangle {
        anchors.fill: parent
        // 顶部稍亮 → 底部稍暗的纵向渐变，营造工作台氛围
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: Qt.lighter(root.colors.bg, 1.12) }
            GradientStop { position: 1.0; color: Qt.darker(root.colors.bg, 1.05) }
        }

        // 右上角装饰光晕（accent 色，极低透明度）
        Rectangle {
            anchors.top: parent.top
            anchors.right: parent.right
            anchors.topMargin: -120
            anchors.rightMargin: -120
            width: 420
            height: 420
            radius: 210
            color: root.colors.accent
            opacity: 0.08
        }
        // 左下角装饰光晕
        Rectangle {
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.bottomMargin: -160
            anchors.leftMargin: -160
            width: 480
            height: 480
            radius: 240
            color: root.colors.accent
            opacity: 0.05
        }
    }

    // ===== 居中登录卡 =====
    Rectangle {
        id: card
        anchors.centerIn: parent
        width: 400
        height: 480
        radius: 16
        color: root.colors.card
        border.color: root.colors.border
        border.width: 1

        // 卡片投影
        Rectangle {
            z: -1
            anchors.fill: parent
            anchors.topMargin: 8
            radius: 16
            color: "#000000"
            opacity: 0.25
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 40
            spacing: 0

            // ===== Logo 区 =====
            Item { Layout.fillHeight: true }

            // Logo 圆形图标
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                width: 64
                height: 64
                radius: 16
                color: root.colors.accent
                Layout.preferredHeight: 64

                Text {
                    anchors.centerIn: parent
                    text: "Q"
                    color: "#ffffff"
                    font.pixelSize: 32
                    font.bold: true
                }
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 16
                text: "QuantOKX"
                color: root.colors.fg
                font.pixelSize: 26
                font.bold: true
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 6
                text: qsTr("量化交易终端")
                color: root.colors.fgSec
                font.pixelSize: 13
            }

            Item { Layout.fillHeight: true }

            // ===== 用户名输入 =====
            Text {
                text: qsTr("用户名")
                color: root.colors.fgSec
                font.pixelSize: 12
                Layout.fillWidth: true
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 42
                Layout.topMargin: 6
                radius: 8
                color: root.colors.bg
                border.color: usernameInput.activeFocus ? root.colors.accent : root.colors.border
                border.width: 1
                Behavior on border.color { ColorAnimation { duration: 120 } }

                TextInput {
                    id: usernameInput
                    anchors.fill: parent
                    anchors.leftMargin: 14
                    anchors.rightMargin: 14
                    verticalAlignment: Text.AlignVCenter
                    color: root.colors.fg
                    font.pixelSize: 14
                    selectByMouse: true
                    clip: true
                    // 回车切到密码框
                    Keys.onReturnPressed: passwordInput.forceActiveFocus()
                    Keys.onEnterPressed: passwordInput.forceActiveFocus()
                    // 隐藏占位文字
                    Text {
                        anchors.fill: parent
                        verticalAlignment: Text.AlignVCenter
                        text: qsTr("请输入用户名")
                        color: root.colors.fgSec
                        font.pixelSize: 14
                        visible: !usernameInput.text.length
                    }
                }
            }

            // ===== 密码输入 =====
            Text {
                Layout.topMargin: 16
                text: qsTr("密码")
                color: root.colors.fgSec
                font.pixelSize: 12
                Layout.fillWidth: true
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 42
                Layout.topMargin: 6
                radius: 8
                color: root.colors.bg
                border.color: passwordInput.activeFocus ? root.colors.accent : root.colors.border
                border.width: 1
                Behavior on border.color { ColorAnimation { duration: 120 } }

                TextInput {
                    id: passwordInput
                    anchors.fill: parent
                    anchors.leftMargin: 14
                    anchors.rightMargin: 14
                    verticalAlignment: Text.AlignVCenter
                    color: root.colors.fg
                    font.pixelSize: 14
                    selectByMouse: true
                    echoMode: TextInput.Password
                    clip: true
                    Keys.onReturnPressed: doLogin()
                    Keys.onEnterPressed: doLogin()
                    Text {
                        anchors.fill: parent
                        verticalAlignment: Text.AlignVCenter
                        text: qsTr("请输入密码")
                        color: root.colors.fgSec
                        font.pixelSize: 14
                        visible: !passwordInput.text.length
                    }
                }
            }

            // ===== 错误提示 =====
            Text {
                id: errorText
                Layout.fillWidth: true
                Layout.topMargin: 10
                text: ""
                color: "#ef4444"
                font.pixelSize: 12
                visible: text.length > 0
            }

            // ===== 登录按钮 =====
            Rectangle {
                id: loginBtn
                Layout.fillWidth: true
                Layout.preferredHeight: 44
                Layout.topMargin: 16
                radius: 8
                color: loginMa.containsMouse ? Qt.lighter(root.colors.accent, 1.12)
                      : root.colors.accent
                Behavior on color { ColorAnimation { duration: 120 } }

                Text {
                    anchors.centerIn: parent
                    text: qsTr("登 录")
                    color: "#ffffff"
                    font.pixelSize: 15
                    font.bold: true
                }

                MouseArea {
                    id: loginMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: doLogin()
                }
            }

            Item { Layout.fillHeight: true }

            // ===== 底部友好提示 =====
            Text {
                Layout.alignment: Qt.AlignHCenter
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("首次使用请先在 Web 端注册账户")
                color: root.colors.fgSec
                font.pixelSize: 11
                wrapMode: Text.WordWrap
            }
        }
    }

    // ===== 登录逻辑 =====
    function doLogin() {
        var u = usernameInput.text.trim()
        var p = passwordInput.text
        if (!u || !p) {
            errorText.text = qsTr("请输入用户名和密码")
            return
        }
        errorText.text = ""
        var token = ""
        try {
            token = authService.login(u, p)
        } catch (e) {
            console.warn("[LoginPage] authService.login 异常: " + e)
            errorText.text = qsTr("登录服务异常，请检查后端")
            return
        }
        if (token && token.length > 0) {
            root.loginSuccess()
        } else {
            errorText.text = qsTr("用户名或密码错误")
            passwordInput.text = ""
        }
    }

    // 页面加载后自动聚焦用户名框
    Component.onCompleted: usernameInput.forceActiveFocus()
}
