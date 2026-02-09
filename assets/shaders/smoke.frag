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

    // --- Cold ink palette: 五色墨韵 (5 distinct cool tones) ---
    vec3 colors[5] = vec3[5](
        vec3(0.22, 0.24, 0.30),      // 墨灰 ink grey — cool charcoal
        vec3(0.28, 0.38, 0.52),      // 钢蓝 steel blue — cool blue-grey
        vec3(0.24, 0.36, 0.64),      // 暗蓝 dark blue — logo ink stroke (main)
        vec3(0.40, 0.46, 0.56),      // 霜蓝 frost blue — light blue-grey
        vec3(0.52, 0.56, 0.62)       // 冷银 cool silver — bright metallic
    );

    // --- Layer hierarchy: distant(0,4) → mid(1,3) → main(2) ---
    // Rendering order: back-to-front
    int order[5] = int[5](0, 4, 1, 3, 2);

    // Shared baseline — all curves oscillate around the same center
    float baseline = 0.50;

    // Amplitude scale: main curve dominates
    float ampScale[5] = float[5](0.40, 0.65, 1.00, 0.65, 0.40);

    // Line SDF: crisp strokes (distant 3.2px / mid 4.0px / main 4.8px)
    float lineOuter[5] = float[5](0.008, 0.010, 0.012, 0.010, 0.008);
    float lineInner[5] = float[5](0.002, 0.003, 0.004, 0.003, 0.002);

    // Line opacity: depth-based transparency
    float lineAlphas[5] = float[5](0.55, 0.72, 0.92, 0.72, 0.55);

    // Glow: subtle aura, not visible haze
    float glowRadius[5] = float[5](0.00015, 0.00020, 0.00030, 0.00020, 0.00015);
    float glowStr[5]    = float[5](0.06, 0.08, 0.10, 0.08, 0.06);

    // Downward shadow: main curve only, tight
    float shadowAlpha[5] = float[5](0.0, 0.0, 0.08, 0.0, 0.0);
    float shadowDecay[5] = float[5](1.0, 1.0, 14.0, 1.0, 1.0);

    // Brightness: wider depth gap for layered feel
    float bright[5] = float[5](0.50, 0.72, 1.00, 0.72, 0.50);

    // Peak X positions (closer to center for tighter grouping)
    float peakX[5] = float[5](0.25, 0.38, 0.50, 0.62, 0.75);

    // Per-curve wave frequencies (halved for cx*2.0 compensation)
    float waveFreq[5] = float[5](3.5, 2.75, 2.0, 2.75, 3.5);

    // Band energies
    float bands[5] = float[5](b0, b1, b2, b3, b4);

    // Detect FFT data vs idle
    float bandSum = b0 + b1 + b2 + b3 + b4;
    float hasData = smoothstep(0.0, 0.05, bandSum);

    // State color modulation
    vec3 stateTint = vec3(0.85, 0.75, 0.55);

    // Edge alpha fade (horizontal)
    float edgeFade = smoothstep(0.0, 0.05, uv.x) * smoothstep(1.0, 0.95, uv.x);

    vec3 result_rgb = vec3(0.0);
    float result_a = 0.0;

    for (int j = 0; j < 5; j++) {
        int i = order[j];  // back-to-front
        float fi = float(i);

        // Symmetric index: distance from center curve (2,1,0,1,2)
        float si = abs(fi - 2.0);
        // Signed distance from center (smooth, no abs() cusp)
        float dx_center = uv.x - 0.5;

        // Energy from FFT band or idle animation
        float energy;
        if (hasData > 0.5) {
            energy = bands[i];
            energy = pow(max(energy, 0.0), 0.5);
        } else {
            float phase = si * 1.4 + time * (0.25 + si * 0.05);
            energy = amplitude * (0.12 + si * 0.04 + 0.18 * sin(phase));
        }
        energy *= ampScale[i];

        // Gaussian envelope: peak in own horizontal region
        float dx = uv.x - peakX[i];
        float gauss = exp(-dx * dx * 18.0);
        float envelope = 0.08 + 0.92 * gauss;

        // Smooth center-symmetric wave: cos(even function) → no cusp at center
        float wphase = dx_center * 2.0 * 3.14159 * waveFreq[i] + si * 2.3 + time * 0.15;
        float sinVal = cos(wphase);

        // Displacement from baseline (smooth, both directions)
        float displacement = energy * envelope * sinVal * 0.55;
        float curveY = baseline - displacement;

        // Micro-breathing wobble (smooth symmetric: spatial cos × temporal sin)
        float breath = cos(dx_center * 18.0) * sin(time * 0.22 + si * 1.7) * 0.005;
        curveY += breath;

        // --- SDF line with per-layer thickness ---
        float dist = abs(uv.y - curveY);
        float mainLine = smoothstep(lineOuter[i], lineInner[i], dist);

        // --- Glow with per-layer radius ---
        float glow = exp(-dist * dist / glowRadius[i]) * glowStr[i];

        // --- Downward shadow (main curve only) ---
        float belowCurve = uv.y - curveY;
        float shadow = 0.0;
        if (belowCurve > 0.0 && shadowAlpha[i] > 0.0) {
            shadow = shadowAlpha[i] * exp(-belowCurve * shadowDecay[i]);
        }

        // Color with state modulation + depth brightness
        vec3 col = colors[i] * stateBrightness * bright[i];
        col = mix(col, col * stateTint, stateHue);
        col = min(col, vec3(1.0));

        // Composite: line + glow + shadow
        float a = (mainLine * lineAlphas[i] + glow + shadow) * edgeFade;
        a = clamp(a, 0.0, 1.0);

        result_rgb = col * a + result_rgb * (1.0 - a);
        result_a = a + result_a * (1.0 - a);
    }

    fragColor = vec4(result_rgb, clamp(result_a, 0.0, 1.0)) * qt_Opacity;
}
