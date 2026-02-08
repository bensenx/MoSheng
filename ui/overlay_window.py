"""Floating overlay window with glassmorphism effect and fade animations."""

import ctypes
import logging

from PySide6.QtCore import (
    Property, QEasingCurve, QPropertyAnimation, QTimer, Qt, Slot,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ui.styles import (
    COLOR_BORDER, COLOR_ERROR, COLOR_FILTERED, COLOR_OVERLAY_BG, COLOR_OVERLAY_TEXT,
    COLOR_RECORDING, COLOR_RECOGNIZING, COLOR_RESULT, FONT_FAMILY,
)

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


class OverlayWindow(QWidget):
    """Transparent, topmost, click-through status overlay at bottom-right."""

    WIDTH = 300
    HEIGHT = 54
    MARGIN = 24
    BG_RADIUS = 16
    RESULT_DISPLAY_MS = 2000
    FADE_DURATION_MS = 200

    def __init__(self, enabled: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self._enabled = enabled
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._animate_recording)
        self._anim_step = 0
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self._opacity = 0.0

        # Window flags
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.WIDTH, self.HEIGHT)

        # Label for status text
        self._label = QLabel("", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setFont(QFont("Segoe UI Variable", 12, QFont.Weight.Medium))
        self._label.setStyleSheet(f"color: {COLOR_OVERLAY_TEXT}; background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.addWidget(self._label)

        # Fade animation
        self._fade_anim = QPropertyAnimation(self, b"overlayOpacity", self)
        self._fade_anim.setDuration(self.FADE_DURATION_MS)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self._position_bottom_right()
        self.setWindowOpacity(0.0)
        self.hide()

    # --- Animated opacity property ---

    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, value: float) -> None:
        self._opacity = value
        self.setWindowOpacity(value)
        if value <= 0.01:
            super().hide()

    overlayOpacity = Property(float, _get_opacity, _set_opacity)

    # --- Painting (glassmorphism card) ---

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Semi-transparent background
        bg = QColor(COLOR_OVERLAY_BG)
        bg.setAlphaF(0.78)
        p.setBrush(bg)

        # Subtle border
        border = QColor(255, 255, 255, 18)
        p.setPen(QPen(border, 1))

        p.drawRoundedRect(
            self.rect().adjusted(1, 1, -1, -1),
            self.BG_RADIUS, self.BG_RADIUS,
        )
        p.end()

    # --- Positioning ---

    def _position_bottom_right(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.right() - self.WIDTH - self.MARGIN
        y = geo.bottom() - self.HEIGHT - self.MARGIN
        self.move(x, y)

    # --- Click-through (Windows-specific) ---

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._set_click_through()

    def _set_click_through(self) -> None:
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW,
            )
        except Exception:
            logger.debug("Could not set click-through")

    # --- Fade helpers ---

    def _fade_in(self) -> None:
        super().show()
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def _fade_out(self) -> None:
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def hide(self) -> None:
        if self._opacity > 0.01:
            self._fade_out()
        else:
            super().hide()

    # --- Public API (thread-safe via signal connection) ---

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        if not value:
            self._anim_timer.stop()
            self._fade_anim.stop()
            self.setWindowOpacity(0.0)
            super().hide()

    @Slot(str, str)
    def set_state(self, state: str, text: str = "") -> None:
        """Update the overlay display. Call from main thread or via queued signal."""
        if not self._enabled:
            return

        self._anim_timer.stop()
        self._hide_timer.stop()

        if state == STATE_IDLE:
            self.hide()
            return

        self._fade_in()

        if state == STATE_RECORDING:
            self._label.setStyleSheet(f"color: {COLOR_RECORDING}; background: transparent;")
            self._anim_step = 0
            self._anim_timer.start(400)
            self._animate_recording()

        elif state == STATE_RECOGNIZING:
            self._label.setStyleSheet(f"color: {COLOR_RECOGNIZING}; background: transparent;")
            self._label.setText("识别中...")

        elif state == STATE_RESULT:
            self._label.setStyleSheet(f"color: {COLOR_RESULT}; background: transparent;")
            display = text if len(text) <= 30 else text[:28] + "..."
            self._label.setText(display)
            self._hide_timer.start(self.RESULT_DISPLAY_MS)

        elif state == STATE_ERROR:
            self._label.setStyleSheet(f"color: {COLOR_ERROR}; background: transparent;")
            display = text if len(text) <= 30 else text[:28] + "..."
            self._label.setText(display)
            self._hide_timer.start(self.RESULT_DISPLAY_MS)

        elif state == STATE_FILTERED:
            self._label.setStyleSheet(f"color: {COLOR_FILTERED}; background: transparent;")
            self._label.setText("已过滤")
            self._hide_timer.start(1000)

    # --- Animation ---

    def _animate_recording(self) -> None:
        dots = "\u25cf" * ((self._anim_step % 3) + 1)
        self._label.setText(f"录音中 {dots}")
        self._anim_step += 1
