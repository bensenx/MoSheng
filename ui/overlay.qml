import QtQuick

Rectangle {
    id: root
    property string statusMessage: ""
    property color indicator: "#fd92b5"
    property bool showMeter: true
    property real amplitude: 0
    property real b0: 0
    property real b1: 0
    property real b2: 0
    property real b3: 0
    property real b4: 0

    implicitHeight: Math.max(48, caption.implicitHeight + 20)
    radius: Math.min(height / 2, 24)
    color: "#241f32"
    border.color: "#625471"

    Rectangle {
        id: dot
        anchors.left: parent.left
        anchors.leftMargin: 18
        anchors.verticalCenter: parent.verticalCenter
        width: 8; height: 8; radius: 4
        color: root.indicator
    }

    Text {
        id: caption
        anchors.left: dot.right
        anchors.leftMargin: 12
        anchors.right: root.showMeter ? meter.left : parent.right
        anchors.rightMargin: 18
        anchors.verticalCenter: parent.verticalCenter
        text: root.statusMessage
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: "#f7f2ff"
        font.pixelSize: 15
        font.weight: Font.DemiBold
    }

    Row {
        id: meter
        anchors.right: parent.right
        anchors.rightMargin: 18
        anchors.verticalCenter: parent.verticalCenter
        height: 30
        spacing: 3
        visible: root.showMeter
        readonly property var colors: ["#fd92b5", "#b6a4ff", "#6be4d9"]
        readonly property var envelope: [4, 10, 16, 22, 12, 7, 17, 10, 4]
        Repeater {
            model: 9
            Rectangle {
                required property int index
                readonly property real band: [root.b0, root.b1, root.b2, root.b3, root.b4][Math.abs(4 - index)]
                y: (meter.height - height) / 2
                width: 4
                height: 4 + meter.envelope[index] * root.amplitude + 4 * band
                radius: 2
                color: meter.colors[index % 3]
            }
        }
    }
}
