#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float amplitude;
    float stateBrightness;
    float stateHue;
    float b0; float b1; float b2; float b3; float b4;
};

void main() {
    vec2 uv = qt_TexCoord0;

    // --- Five-color ink palette (五色墨韵) ---
    vec3 colors[5] = vec3[5](
        vec3(0.176, 0.204, 0.212),   // 松烟墨 (Bass)
        vec3(0.290, 0.435, 0.647),   // 靛蓝 (Low-mid)
        vec3(0.722, 0.451, 0.200),   // 赭石 (Mid, center)
        vec3(0.761, 0.298, 0.251),   // 朱砂 (High-mid)
        vec3(0.831, 0.659, 0.341)    // 藤黄 (Treble)
    );

    // Peak X positions
    float peakX[5] = float[5](0.12, 0.32, 0.50, 0.70, 0.88);

    // Amplitude scale: center curve largest
    float ampScale[5] = float[5](0.55, 0.75, 1.00, 0.75, 0.55);

    // Per-curve wave frequencies
    float waveFreq[5] = float[5](7.0, 5.5, 4.0, 6.0, 8.0);

    // Band energies
    float bands[5] = float[5](b0, b1, b2, b3, b4);

    // Detect FFT data vs idle
    float bandSum = b0 + b1 + b2 + b3 + b4;
    float hasData = smoothstep(0.0, 0.05, bandSum);

    // State color modulation
    vec3 stateTint = vec3(0.85, 0.75, 0.55);

    // Edge alpha fade
    float edgeFade = smoothstep(0.0, 0.05, uv.x) * smoothstep(1.0, 0.95, uv.x);

    // Baseline: center of overlay
    float baseline = 0.50;

    vec3 result_rgb = vec3(0.0);
    float result_a = 0.0;

    for (int i = 0; i < 5; i++) {
        float fi = float(i);

        // Energy from band
        float energy;
        if (hasData > 0.5) {
            energy = bands[i];
            energy = pow(max(energy, 0.0), 0.35);
        } else {
            float phase = fi * 1.4 + time * (0.25 + fi * 0.05);
            energy = amplitude * (0.12 + fi * 0.04 + 0.18 * sin(phase));
        }
        energy *= ampScale[i];

        // Gaussian envelope: sharp peak in own region
        float dx = uv.x - peakX[i];
        float gauss = exp(-dx * dx * 18.0);
        float envelope = 0.08 + 0.92 * gauss;

        // Sinusoidal wave — oscillates both above and below baseline
        float phase = uv.x * 3.14159 * waveFreq[i] + fi * 2.3 + time * 0.15;
        float sinVal = sin(phase);  // [-1, 1]

        // Displacement from baseline (both directions)
        float displacement = energy * envelope * sinVal * 0.42;
        float curveY = baseline - displacement;

        // Micro-breathing wobble
        float breath = sin(time * 0.22 + uv.x * 4.5 + fi * 1.7) * 0.005;
        curveY += breath;

        // SDF thin line + subtle glow
        float dist = abs(uv.y - curveY);
        float mainLine = smoothstep(0.018, 0.004, dist);
        float glow = exp(-dist * dist / 0.0006) * 0.12;

        // Color with state modulation
        vec3 col = colors[i] * stateBrightness;
        col = mix(col, col * stateTint, stateHue);
        col = min(col, vec3(1.0));

        // Composite
        float a = (mainLine * 0.90 + glow) * edgeFade;

        result_rgb = col * a + result_rgb * (1.0 - a);
        result_a = a + result_a * (1.0 - a);
    }

    fragColor = vec4(result_rgb, clamp(result_a, 0.0, 1.0)) * qt_Opacity;
}
