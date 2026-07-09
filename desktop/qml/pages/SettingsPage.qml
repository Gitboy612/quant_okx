// SettingsPage.qml — 设置（M365 设置风格：左分区导航 + 右内容）
//
// 职责：
// - 左侧分区导航：通用 / 账户 / 主题 / 关于
// - 通用：开机自启开关（占位）、语言选择（占位）
// - 账户：当前用户（authService.currentUser()）、退出登录按钮
//   （authService.logout() + 发 logoutSignal）
// - 主题：明/暗切换（通过信号 themeSwitched 传给 main.qml）
// - 关于：版本号、技术栈说明（Qt PySide6 QML）

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var colors: ({
        bg: "#1e1e2e", card: "#2a2a3a", fg: "#e4e4ef", fgSec: "#9999aa",
        accent: "#6366f1", border: "#33334a", hover: "#33334a"
    })
    property string theme: "dark"

    // 业务信号
    signal logoutRequested()      // 退出登录（main.qml 接 → replace 到 LoginPage）
    signal themeSwitched(string t) // 主题切换（main.qml 接 → 更新 root.theme）

    // 当前选中分区
    property int currentSection: 0   // 0=通用 1=账户 2=主题 3=关于

    // 分区列表
    property var sections: [
        { key: "general", icon: "⚙️", label: qsTr("通用") },
        { key: "account", icon: "👤", label: qsTr("账户") },
        { key: "theme",   icon: "🎨", label: qsTr("主题") },
        { key: "about",   icon: "ℹ️", label: qsTr("关于") }
    ]

    // 当前用户
    property var currentUser: ({})

    // 开机自启占位开关状态
    property bool autoStartEnabled: false
    // 语言占位选择
    property string currentLanguage: "zh-CN"

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ===== 左侧分区导航 =====
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
                anchors.margins: 12
                spacing: 4

                Text {
                    text: qsTr("设置")
                    color: root.colors.fg
                    font.pixelSize: 16
                    font.bold: true
                    Layout.fillWidth: true
                    Layout.leftMargin: 8
                    Layout.topMargin: 4
                    Layout.bottomMargin: 8
                }

                Repeater {
                    model: root.sections

                    delegate: Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 40
                        radius: 8
                        color: root.currentSection === index ? root.colors.hover : "transparent"
                        Behavior on color { ColorAnimation { duration: 120 } }

                        Row {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 10

                            Text {
                                text: modelData.icon
                                font.pixelSize: 16
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: modelData.label
                                color: root.currentSection === index ? root.colors.fg : root.colors.fgSec
                                font.pixelSize: 13
                                font.bold: root.currentSection === index
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }

                        // 选中左侧竖条
                        Rectangle {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            width: 3; height: 18; radius: 1.5
                            color: root.colors.accent
                            visible: root.currentSection === index
                        }

                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.currentSection = index
                        }
                    }
                }

                // 弹簧
                Item { Layout.fillHeight: true }
            }
        }

        // ===== 右侧内容区 =====
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.rightMargin: 16
            Layout.topMargin: 16
            Layout.bottomMargin: 16
            color: root.colors.card
            border.color: root.colors.border
            border.width: 1
            radius: 12

            // 内容滚动区
            Flickable {
                anchors.fill: parent
                anchors.margins: 24
                contentWidth: width
                contentHeight: sectionContent.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                ColumnLayout {
                    id: sectionContent
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 20

                    // ===== 通用设置 =====
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 16
                        visible: root.currentSection === 0

                        Text {
                            text: qsTr("通用设置")
                            color: root.colors.fg
                            font.pixelSize: 18
                            font.bold: true
                        }

                        // 开机自启
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text {
                                    text: qsTr("开机自启动")
                                    color: root.colors.fg
                                    font.pixelSize: 13
                                }
                                Text {
                                    text: qsTr("系统启动时自动运行 QuantOKX")
                                    color: root.colors.fgSec
                                    font.pixelSize: 11
                                }
                            }
                            // 开关
                            Rectangle {
                                Layout.alignment: Qt.AlignVCenter
                                width: 44; height: 24; radius: 12
                                color: root.autoStartEnabled ? root.colors.accent : root.colors.border
                                Behavior on color { ColorAnimation { duration: 150 } }
                                Rectangle {
                                    x: root.autoStartEnabled ? parent.width - width - 3 : 3
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 18; height: 18; radius: 9
                                    color: "#ffffff"
                                    Behavior on x { NumberAnimation { duration: 150 } }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        root.autoStartEnabled = !root.autoStartEnabled
                                        console.log("[Settings] 开机自启: " + root.autoStartEnabled)
                                    }
                                }
                            }
                        }

                        Rectangle { Layout.fillWidth: true; height: 1; color: root.colors.border }

                        // 语言选择
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text {
                                    text: qsTr("语言")
                                    color: root.colors.fg
                                    font.pixelSize: 13
                                }
                                Text {
                                    text: qsTr("界面显示语言（占位，暂未实现）")
                                    color: root.colors.fgSec
                                    font.pixelSize: 11
                                }
                            }
                            Rectangle {
                                Layout.alignment: Qt.AlignVCenter
                                width: 140; height: 32; radius: 6
                                color: root.colors.bg
                                border.color: root.colors.border
                                border.width: 1
                                Text {
                                    anchors.centerIn: parent
                                    text: root.currentLanguage === "zh-CN" ? qsTr("简体中文") : qsTr("English")
                                    color: root.colors.fg
                                    font.pixelSize: 12
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        root.currentLanguage = root.currentLanguage === "zh-CN" ? "en-US" : "zh-CN"
                                        console.log("[Settings] 语言切换: " + root.currentLanguage)
                                    }
                                }
                            }
                        }
                    }

                    // ===== 账户设置 =====
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 16
                        visible: root.currentSection === 1

                        Text {
                            text: qsTr("账户")
                            color: root.colors.fg
                            font.pixelSize: 18
                            font.bold: true
                        }

                        // 当前用户信息
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 80
                            radius: 8
                            color: root.colors.bg
                            border.color: root.colors.border
                            border.width: 1

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 12

                                Rectangle {
                                    width: 44; height: 44; radius: 22
                                    color: root.colors.accent
                                    Layout.alignment: Qt.AlignVCenter
                                    Text {
                                        anchors.centerIn: parent
                                        text: currentUser.username ? currentUser.username.charAt(0).toUpperCase() : "U"
                                        color: "#ffffff"
                                        font.pixelSize: 18
                                        font.bold: true
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Text {
                                        text: currentUser.username || qsTr("未登录")
                                        color: root.colors.fg
                                        font.pixelSize: 15
                                        font.bold: true
                                    }
                                    Text {
                                        text: currentUser.id ? qsTr("用户 ID: %1").arg(currentUser.id) : qsTr("请先登录")
                                        color: root.colors.fgSec
                                        font.pixelSize: 11
                                    }
                                }
                            }
                        }

                        // 退出登录按钮
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 40
                            radius: 8
                            color: logoutMa.containsMouse ? "#3a1d1d" : "transparent"
                            border.color: logoutMa.containsMouse ? "#ef4444" : root.colors.border
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 120 } }
                            Text {
                                anchors.centerIn: parent
                                text: qsTr("退出登录")
                                color: logoutMa.containsMouse ? "#ef4444" : root.colors.fg
                                font.pixelSize: 13
                                font.bold: true
                            }
                            MouseArea {
                                id: logoutMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    try {
                                        authService.logout()
                                    } catch (e) {
                                        console.warn("[Settings] logout 异常: " + e)
                                    }
                                    console.log("[Settings] 退出登录")
                                    root.logoutRequested()
                                }
                            }
                        }
                    }

                    // ===== 主题设置 =====
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 16
                        visible: root.currentSection === 2

                        Text {
                            text: qsTr("主题")
                            color: root.colors.fg
                            font.pixelSize: 18
                            font.bold: true
                        }

                        Text {
                            text: qsTr("选择应用的外观主题")
                            color: root.colors.fgSec
                            font.pixelSize: 12
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 16

                            // 深色主题
                            Rectangle {
                                Layout.preferredWidth: 160
                                Layout.preferredHeight: 110
                                radius: 10
                                color: root.theme === "dark" ? root.colors.accent : root.colors.bg
                                border.color: root.theme === "dark" ? root.colors.accent : root.colors.border
                                border.width: root.theme === "dark" ? 2 : 1
                                Behavior on color { ColorAnimation { duration: 150 } }

                                Column {
                                    anchors.centerIn: parent
                                    spacing: 8
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: "🌙"
                                        font.pixelSize: 28
                                    }
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: qsTr("深色")
                                        color: root.theme === "dark" ? "#ffffff" : root.colors.fg
                                        font.pixelSize: 13
                                        font.bold: root.theme === "dark"
                                    }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.themeSwitched("dark")
                                }
                            }

                            // 浅色主题
                            Rectangle {
                                Layout.preferredWidth: 160
                                Layout.preferredHeight: 110
                                radius: 10
                                color: root.theme === "light" ? root.colors.accent : root.colors.bg
                                border.color: root.theme === "light" ? root.colors.accent : root.colors.border
                                border.width: root.theme === "light" ? 2 : 1
                                Behavior on color { ColorAnimation { duration: 150 } }

                                Column {
                                    anchors.centerIn: parent
                                    spacing: 8
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: "☀️"
                                        font.pixelSize: 28
                                    }
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: qsTr("浅色")
                                        color: root.theme === "light" ? "#ffffff" : root.colors.fg
                                        font.pixelSize: 13
                                        font.bold: root.theme === "light"
                                    }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.themeSwitched("light")
                                }
                            }
                        }
                    }

                    // ===== 关于 =====
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 16
                        visible: root.currentSection === 3

                        Text {
                            text: qsTr("关于")
                            color: root.colors.fg
                            font.pixelSize: 18
                            font.bold: true
                        }

                        // 应用信息卡
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 200
                            radius: 8
                            color: root.colors.bg
                            border.color: root.colors.border
                            border.width: 1

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 20
                                spacing: 12

                                RowLayout {
                                    spacing: 12
                                    Rectangle {
                                        width: 48; height: 48; radius: 12
                                        color: root.colors.accent
                                        Text {
                                            anchors.centerIn: parent
                                            text: "Q"
                                            color: "#ffffff"
                                            font.pixelSize: 24
                                            font.bold: true
                                        }
                                    }
                                    ColumnLayout {
                                        spacing: 2
                                        Text {
                                            text: "QuantOKX"
                                            color: root.colors.fg
                                            font.pixelSize: 16
                                            font.bold: true
                                        }
                                        Text {
                                            text: qsTr("版本 1.0.0")
                                            color: root.colors.fgSec
                                            font.pixelSize: 12
                                        }
                                    }
                                }

                                Rectangle { Layout.fillWidth: true; height: 1; color: root.colors.border }

                                ColumnLayout {
                                    spacing: 6
                                    Text {
                                        text: qsTr("技术栈：Qt 6 + PySide6 + QML")
                                        color: root.colors.fg
                                        font.pixelSize: 12
                                    }
                                    Text {
                                        text: qsTr("后端：FastAPI + SQLAlchemy + OKX API")
                                        color: root.colors.fgSec
                                        font.pixelSize: 12
                                    }
                                    Text {
                                        text: qsTr("数据库：SQLite / PostgreSQL")
                                        color: root.colors.fgSec
                                        font.pixelSize: 12
                                    }
                                    Text {
                                        text: qsTr("量化交易策略管理与执行桌面终端")
                                        color: root.colors.fgSec
                                        font.pixelSize: 11
                                    }
                                }
                            }
                        }
                    }

                    Item { Layout.fillWidth: true; Layout.preferredHeight: 8 }
                }
            }
        }
    }

    // ===== 数据加载 =====
    function loadCurrentUser() {
        try {
            var u = authService.currentUser()
            if (u) root.currentUser = u
        } catch (e) {
            console.warn("[Settings] currentUser 异常: " + e)
        }
    }

    Component.onCompleted: loadCurrentUser()
}
