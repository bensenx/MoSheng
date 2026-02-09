"""QML GPU shader overlay: five-color ink wash visualization (五色墨韵)."""

import ctypes
import logging
import math
import os
import time

import numpy as np
from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, QTimer, QUrl, Qt,
)
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

# States
STATE_IDLE = "idle"
STATE_RECORDING = "recording"
STATE_RECOGNIZING = "recognizing"
STATE_RESULT = "result"
STATE_ERROR = "error"
STATE_FILTERED = "filtered"

# Windows extended window style flags
WS_EX_LAYERED = 0x80000
WS_EX_TRANSPARENT = 0x20
WS_EX_TOOLWINDOW = 0x80
GWL_EXSTYLE = -20

# State → (stateBrightness, stateHue) for shader modulation
_STATE_VISUALS = {
    STATE_RECORDING:   (1.0, 0.0),   # pure ink colors
    STATE_RECOGNIZING: (1.3, 0.3),   # brighter, warm gold shift
    STATE_RESULT:      (1.3, 0.3),   # inherit recognizing look
    STATE_ERROR:       (0.8, 0.0),   # dimmer
    STATE_FILTERED:    (0.7, 0.5),   # dim + grey shift
}

# QML file path (relative to this file)
_QML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlay.qml")

# FFT constants
_FFT_SIZE = 1024
# Logarithmic band edges (bin indices) for 8 bands at 16kHz / 1024-point FFT
# bin_hz ≈ 15.6 Hz/bin
# ~0-125, 125-250, 250-500, 500-1k, 1k-2k, 2k-4k, 4k-6.4k, 6.4k-8kHz
_BAND_EDGES = [0, 8, 16, 32, 64, 128, 256, 413, 513]
_HANNING = np.hanning(_FFT_SIZE).astype(np.float32)


class OverlayWindow:
    """Bottom-center QML shader overlay for audio visualization.

    Uses QQuickView with a GLSL fragment shader for GPU-rendered ink ripples.
    Five curves with distinct ink colors respond to 5 frequency bands.
    """

    HEIGHT = 140
    WIDTH_RATIO = 0.07
    MARGIN = 32
    RESULT_DISPLAY_MS = 1500
    FRAME_INTERVAL_MS = 33  # ~30 fps for RMS polling

    def __init__(self, enabled: bool = True, recorder=None,
                 parent=None):
        self._enabled = enabled
        self._recorder = recorder
        self._state = STATE_IDLE
        self._opacity = 0.0
        self._target_rms = 0.0
        self._display_rms = 0.0
        self._breath_start = 0.0
        self._root = None
        self._ready = False
        self._band_smooth = np.zeros(5, dtype=np.float32)

        # Create QQuickView with transparent background
        self._view = QQuickView()
        self._view.setColor(QColor(0, 0, 0, 0))
        self._view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self._view.setFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        # Position and size
        self._update_geometry()

        # Hide timer (auto-hide after result/error display)
        self._hide_timer = QTimer()
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        # Frame timer for RMS polling
        self._frame_timer = QTimer()
        self._frame_timer.timeout.connect(self._on_frame)

        # Opacity animation
        self._fade_anim = QPropertyAnimation(self._view, b"opacity")
        self._fade_anim.setDuration(200)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade_anim.valueChanged.connect(self._on_opacity_changed)

        self._view.setOpacity(0.0)

        # Load QML
        logger.info("Loading QML from: %s", _QML_PATH)
        self._view.setSource(QUrl.fromLocalFile(_QML_PATH))
        if self._view.status() != QQuickView.Status.Ready:
            for error in self._view.errors():
                logger.error("QML error: %s", error.toString())
            logger.error("QML failed to load, overlay disabled")
            return

        self._root = self._view.rootObject()
        if self._root is None:
            logger.error("QML root object is None, overlay disabled")
            return

        # Set initial state visuals
        brightness, hue = _STATE_VISUALS[STATE_RECORDING]
        self._root.setProperty("stateBrightness", brightness)
        self._root.setProperty("stateHue", hue)
        self._root.setProperty("amplitude", 0.0)

        self._ready = True
        logger.info("QML overlay ready (view size: %dx%d)", self._view.width(), self._view.height())

    # --- Geometry ---

    def _update_geometry(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self._view.setWidth(400)
            self._view.setHeight(self.HEIGHT)
            return
        geo = screen.availableGeometry()
        w = int(geo.width() * self.WIDTH_RATIO)
        self._view.setWidth(w)
        self._view.setHeight(self.HEIGHT)
        x = geo.x() + (geo.width() - w) // 2
        y = geo.bottom() - self.HEIGHT - self.MARGIN + 1
        self._view.setPosition(x, y)

    # --- Click-through (Windows) ---

    def _set_click_through(self) -> None:
        try:
            hwnd = int(self._view.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW,
            )
        except Exception:
            logger.debug("Could not set click-through")

    # --- Opacity ---

    def _on_opacity_changed(self, value) -> None:
        self._opacity = float(value)
        if self._opacity <= 0.01:
            self._frame_timer.stop()
            self._view.hide()

    def _fade_in(self) -> None:
        self._view.show()
        self._set_click_through()
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def _show_instant(self) -> None:
        self._fade_anim.stop()
        self._opacity = 1.0
        self._view.setOpacity(1.0)
        self._view.show()
        self._set_click_through()

    def _fade_out(self) -> None:
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def hide(self) -> None:
        if self._opacity > 0.01:
            self._fade_out()
        else:
            self._frame_timer.stop()
            self._view.hide()

    def close(self) -> None:
        self._frame_timer.stop()
        self._fade_anim.stop()
        self._view.close()

    # --- FFT band computation ---

    _BAND_NAMES = [f"b{i}" for i in range(5)]

    @staticmethod
    def _aggregate_to_5(bands8: np.ndarray) -> np.ndarray:
        """Aggregate 8 FFT bands into 5 for the five-color curves."""
        return np.array([
            (bands8[0] + bands8[1]) * 0.5,   # Bass
            (bands8[2] + bands8[3]) * 0.5,   # Low-mid
            bands8[4],                         # Mid
            (bands8[5] + bands8[6]) * 0.5,   # High-mid
            bands8[7],                         # Treble
        ], dtype=np.float32)

    def _push_bands(self, bands: np.ndarray) -> None:
        """Push 5 frequency band values to QML as individual float properties."""
        if self._root is not None:
            for i, name in enumerate(self._BAND_NAMES):
                self._root.setProperty(name, float(bands[i]))

    def _zero_bands(self) -> None:
        """Reset shader band uniforms to zero."""
        if self._root is not None:
            for name in self._BAND_NAMES:
                self._root.setProperty(name, 0.0)

    def _compute_bands(self) -> np.ndarray | None:
        """Compute 8 logarithmic frequency bands from recent audio (normalized 0-1).

        Bands are normalized by peak then scaled by current RMS so that
        quiet ambient noise produces small values while loud voice
        produces large values.
        """
        if self._recorder is None:
            return None
        samples = self._recorder.get_recent_samples(_FFT_SIZE)
        if samples is None or len(samples) < _FFT_SIZE:
            return None

        windowed = samples[-_FFT_SIZE:] * _HANNING
        fft_mag = np.abs(np.fft.rfft(windowed))

        bands = np.zeros(8, dtype=np.float32)
        for i in range(8):
            lo, hi = _BAND_EDGES[i], _BAND_EDGES[i + 1]
            if hi > lo:
                bands[i] = np.mean(fft_mag[lo:hi])

        peak = np.max(bands)
        if peak > 1e-6:
            bands /= peak

        # Scale by volume so quiet sounds → small, loud voice → large
        rms = self._recorder.current_rms
        vol_scale = min(rms * 50.0, 1.0)
        bands *= vol_scale
        return bands

    # --- Frame tick (RMS + FFT polling) ---

    def _on_frame(self) -> None:
        if self._state == STATE_RECORDING and self._recorder is not None:
            raw = self._recorder.current_rms
            self._target_rms = max(min(raw * 40.0, 1.0), 0.3)

            # Compute FFT bands (8) → aggregate to 5 → push to QML
            raw_bands = self._compute_bands()
            if raw_bands is not None:
                bands5 = self._aggregate_to_5(raw_bands)
                # Asymmetric smoothing: fast attack (0.6), slower decay (0.25)
                alpha = np.where(bands5 > self._band_smooth, 0.6, 0.25)
                self._band_smooth += alpha * (bands5 - self._band_smooth)
                self._push_bands(self._band_smooth)
                # Log once per second for diagnostic
                if not hasattr(self, '_band_log_count'):
                    self._band_log_count = 0
                self._band_log_count += 1
                if self._band_log_count % 30 == 1:
                    b = self._band_smooth
                    logger.info("FFT bands (5): [%.2f %.2f %.2f %.2f %.2f]",
                                b[0], b[1], b[2], b[3], b[4])

        elif self._state == STATE_RECOGNIZING:
            t = time.monotonic() - self._breath_start
            self._target_rms = 0.3 + 0.2 * math.sin(2.0 * math.pi * t / 2.0)
        elif self._state in (STATE_RESULT, STATE_ERROR, STATE_FILTERED):
            t = time.monotonic() - self._breath_start
            self._target_rms = max(0.35 * math.exp(-t * 1.5), 0.0)
        else:
            self._target_rms = 0.0

        # EMA smooth amplitude
        alpha = 0.35
        self._display_rms += alpha * (self._target_rms - self._display_rms)

        # Push amplitude to QML
        if self._root is not None:
            self._root.setProperty("amplitude", self._display_rms)

    # --- Public API ---

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        if not value and self._ready:
            self._frame_timer.stop()
            self._fade_anim.stop()
            self._view.setOpacity(0.0)
            self._view.hide()

    def set_state(self, state: str, text: str = "") -> None:
        if not self._enabled or not self._ready:
            return

        self._hide_timer.stop()
        self._state = state

        # Update state visuals (brightness + hue)
        brightness, hue = _STATE_VISUALS.get(state, _STATE_VISUALS[STATE_RECORDING])
        if self._root is not None:
            self._root.setProperty("stateBrightness", brightness)
            self._root.setProperty("stateHue", hue)

        if state == STATE_IDLE:
            self._frame_timer.stop()
            self.hide()
            return

        if state == STATE_RECORDING:
            self._display_rms = 0.0
            self._target_rms = 0.0
            self._band_smooth[:] = 0.0
            self._show_instant()
            if not self._frame_timer.isActive():
                self._frame_timer.start(self.FRAME_INTERVAL_MS)

        elif state == STATE_RECOGNIZING:
            self._breath_start = time.monotonic()
            self._band_smooth[:] = 0.0
            self._zero_bands()
            self._show_instant()
            if not self._frame_timer.isActive():
                self._frame_timer.start(self.FRAME_INTERVAL_MS)

        elif state in (STATE_RESULT, STATE_ERROR, STATE_FILTERED):
            self._breath_start = time.monotonic()
            self._display_rms = 0.35
            self._band_smooth[:] = 0.0
            self._zero_bands()
            self._show_instant()
            if not self._frame_timer.isActive():
                self._frame_timer.start(self.FRAME_INTERVAL_MS)
            duration = 1000 if state == STATE_FILTERED else self.RESULT_DISPLAY_MS
            self._hide_timer.start(duration)

        if self._root is not None:
            self._root.setProperty("amplitude", self._display_rms)
