import QtQuick

Item {
    id: root

    // Exposed properties — set from Python via rootObject
    property real amplitude: 0.0
    property real stateBrightness: 1.0
    property real stateHue: 0.0
    // FFT frequency bands (5 aggregated from 8)
    property real b0: 0.0
    property real b1: 0.0
    property real b2: 0.0
    property real b3: 0.0
    property real b4: 0.0

    // No background card — ShaderEffect renders directly with alpha
    ShaderEffect {
        anchors.fill: parent

        property real time: 0.0
        property real amplitude: root.amplitude
        property real stateBrightness: root.stateBrightness
        property real stateHue: root.stateHue
        property real b0: root.b0
        property real b1: root.b1
        property real b2: root.b2
        property real b3: root.b3
        property real b4: root.b4

        fragmentShader: "shaders/smoke.frag.qsb"

        NumberAnimation on time {
            from: 0
            to: 100000
            duration: 100000000  // ~27 hours, effectively infinite
            loops: Animation.Infinite
        }
    }
}
