"""Click-through Prism status pill with a live voice meter."""

import logging
import math
import os
import sys
import time

import numpy as np
from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, QTimer, QUrl, Qt,
)
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QApplication

from i18n import tr
from ui.styles import COLOR_ACCENT, COLOR_PINK, COLOR_RESULT, COLOR_TEXT_SECONDARY

logger = logging.getLogger(__name__)

# States
STATE_IDLE = "idle"
STATE_RECORDING = "recording"
STATE_RECOGNIZING = "recognizing"
STATE_RESULT = "result"
STATE_ERROR = "error"
STATE_FILTERED = "filtered"
STATE_LOADING = "loading"

_STATE_LABELS = {
    STATE_RECORDING: ("overlay.recording", COLOR_PINK),
    STATE_RECOGNIZING: ("overlay.recognizing", COLOR_ACCENT),
    STATE_RESULT: ("overlay.inserted", COLOR_RESULT),
    STATE_ERROR: ("overlay.error", COLOR_PINK),
    STATE_FILTERED: ("overlay.filtered", COLOR_TEXT_SECONDARY),
    STATE_LOADING: ("overlay.loading", COLOR_ACCENT),
}

# QML file path (relative to this file)
_QML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlay.qml")

# FFT constants
_FFT_SIZE = 1024
_BAND_EDGES = [0, 8, 16, 32, 64, 128, 256, 413, 513]
_HANNING = np.hanning(_FFT_SIZE).astype(np.float32)

# Windows click-through constants
if sys.platform == "win32":
    import ctypes
    WS_EX_LAYERED = 0x80000
    WS_EX_TRANSPARENT = 0x20
    WS_EX_TOOLWINDOW = 0x80
    GWL_EXSTYLE = -20


class OverlayWindow:
    """Bottom-center status and audio visualization."""

    HEIGHT = 48
    WIDTH = 248
    MARGIN = 32
    RESULT_DISPLAY_MS = 1500
    FRAME_INTERVAL_MS = 33

    def __init__(self, enabled: bool = True, recorder=None, parent=None):
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

        self._view = QQuickView()
        self._view.setColor(QColor(0, 0, 0, 0))
        self._view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self._view.setFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )

        self._update_geometry()

        self._hide_timer = QTimer()
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        self._frame_timer = QTimer()
        self._frame_timer.timeout.connect(self._on_frame)

        self._fade_anim = QPropertyAnimation(self._view, b"opacity")
        self._fade_anim.setDuration(200)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade_anim.valueChanged.connect(self._on_opacity_changed)

        self._view.setOpacity(0.0)

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

        self._ready = True
        logger.info("QML overlay ready (view size: %dx%d)", self._view.width(), self._view.height())

    def _update_geometry(self, show_message: bool = False) -> None:
        screen = QApplication.primaryScreen()
        width = 360 if show_message else self.WIDTH
        if screen is not None:
            width = min(width, screen.availableGeometry().width())
        self._view.setWidth(width)
        height = self.HEIGHT
        if self._root is not None:
            height = max(height, math.ceil(self._root.implicitHeight()))
        self._view.setHeight(height)
        if screen is not None:
            geo = screen.availableGeometry()
            self._view.setPosition(geo.x() + (geo.width() - width) // 2,
                                   geo.bottom() - height - self.MARGIN + 1)

    def _set_click_through(self) -> None:
        if sys.platform == "win32":
            try:
                hwnd = int(self._view.winId())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(
                    hwnd, GWL_EXSTYLE,
                    style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW,
                )
            except Exception:
                logger.debug("Could not set click-through")
        elif sys.platform == "darwin":
            # Qt.Tool + FramelessWindowHint provides most behavior on macOS.
            # Full click-through would need NSWindow.setIgnoresMouseEvents_(True).
            pass

    def _on_opacity_changed(self, value) -> None:
        self._opacity = float(value)
        if self._opacity <= 0.01:
            self._frame_timer.stop()
            self._view.hide()

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
        self._hide_timer.stop()
        self._frame_timer.stop()
        self._fade_anim.stop()
        self._view.close()

    # --- FFT band computation ---

    _BAND_NAMES = [f"b{i}" for i in range(5)]

    @staticmethod
    def _aggregate_to_5(bands8: np.ndarray) -> np.ndarray:
        return np.array([
            (bands8[0] + bands8[1]) * 0.5,
            (bands8[2] + bands8[3]) * 0.5,
            bands8[4],
            (bands8[5] + bands8[6]) * 0.5,
            bands8[7],
        ], dtype=np.float32)

    def _push_bands(self, bands: np.ndarray) -> None:
        if self._root is not None:
            for i, name in enumerate(self._BAND_NAMES):
                self._root.setProperty(name, float(bands[i]))

    def _zero_bands(self) -> None:
        if self._root is not None:
            for name in self._BAND_NAMES:
                self._root.setProperty(name, 0.0)

    def _compute_bands(self) -> np.ndarray | None:
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

        rms = self._recorder.current_rms
        vol_scale = min(rms * 50.0, 1.0)
        bands *= vol_scale
        return bands

    def _on_frame(self) -> None:
        if self._state == STATE_RECORDING and self._recorder is not None:
            raw = self._recorder.current_rms
            self._target_rms = max(min(raw * 40.0, 1.0), 0.3)

            raw_bands = self._compute_bands()
            if raw_bands is not None:
                bands5 = self._aggregate_to_5(raw_bands)
                alpha = np.where(bands5 > self._band_smooth, 0.6, 0.25)
                self._band_smooth += alpha * (bands5 - self._band_smooth)
                self._push_bands(self._band_smooth)

        elif self._state == STATE_RECOGNIZING:
            t = time.monotonic() - self._breath_start
            self._target_rms = 0.3 + 0.2 * math.sin(2.0 * math.pi * t / 2.0)
        else:
            self._target_rms = 0.0

        alpha = 0.35
        self._display_rms += alpha * (self._target_rms - self._display_rms)

        if self._root is not None:
            self._root.setProperty("amplitude", self._display_rms)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        if not value and self._ready:
            self._hide_timer.stop()
            self._frame_timer.stop()
            self._fade_anim.stop()
            self._opacity = 0.0
            self._view.setOpacity(0.0)
            self._view.hide()

    def set_state(self, state: str, text: str = "") -> None:
        if not self._enabled or not self._ready:
            logger.debug("Overlay set_state(%s) skipped: enabled=%s, ready=%s",
                         state, self._enabled, self._ready)
            return

        self._hide_timer.stop()
        self._state = state
        if state == STATE_IDLE:
            self._frame_timer.stop()
            self.hide()
            return

        label, color = _STATE_LABELS[state]
        detailed = state in (STATE_LOADING, STATE_FILTERED, STATE_ERROR) and bool(text)
        self._root.setProperty("statusMessage", text if detailed else tr(label))
        self._root.setProperty("indicator", QColor(color))
        self._root.setProperty("showMeter", state in (STATE_RECORDING, STATE_RECOGNIZING))
        self._update_geometry(detailed)

        if state in (STATE_RECORDING, STATE_RECOGNIZING):
            self._display_rms = 0.0
            self._target_rms = 0.0
            self._breath_start = time.monotonic()
            self._band_smooth[:] = 0.0
            self._zero_bands()
            self._show_instant()
            if not self._frame_timer.isActive():
                self._frame_timer.start(self.FRAME_INTERVAL_MS)

        else:
            self._frame_timer.stop()
            self._show_instant()
            duration = 3500 if state == STATE_ERROR else self.RESULT_DISPLAY_MS
            self._hide_timer.start(duration)

        if self._root is not None:
            self._root.setProperty("amplitude", self._display_rms)
