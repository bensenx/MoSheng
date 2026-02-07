"""Floating overlay window for recording/recognition status display (PySide6)."""

import ctypes
import logging

from PySide6.QtCore import QTimer, Qt, Slot
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ui.styles import (
    COLOR_ERROR, COLOR_OVERLAY_BG, COLOR_OVERLAY_TEXT,
    COLOR_RECORDING, COLOR_RECOGNIZING, COLOR_RESULT,
)

logger = logging.getLogger(__name__)

# States
STATE_IDLE = "idle"
STATE_RECORDING = "recording"
STATE_RECOGNIZING = "recognizing"
STATE_RESULT = "result"
STATE_ERROR = "error"

# Windows extended window style flags
WS_EX_LAYERED = 0x80000
WS_EX_TRANSPARENT = 0x20
WS_EX_TOOLWINDOW = 0x80
GWL_EXSTYLE = -20


class OverlayWindow(QWidget):
    """Transparent, topmost, click-through status overlay at bottom-right."""

    WIDTH = 280
    HEIGHT = 50
    MARGIN = 20
    BG_RADIUS = 12
    RESULT_DISPLAY_MS = 2000

    def __init__(self, enabled: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self._enabled = enabled
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._animate_recording)
        self._anim_step = 0

        # Window flags: frameless, always on top, tool window (no taskbar entry)
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
        self._label.setFont(QFont("Segoe UI Variable", 12))
        self._label.setStyleSheet(f"color: {COLOR_OVERLAY_TEXT}; background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.addWidget(self._label)

        self._position_bottom_right()
        self.hide()

    # --- Painting ---

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        bg = QColor(COLOR_OVERLAY_BG)
        bg.setAlphaF(0.85)
        p.setBrush(bg)
        p.drawRoundedRect(self.rect(), self.BG_RADIUS, self.BG_RADIUS)
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

    # --- Public API (thread-safe via signal connection) ---

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        if not value:
            self.hide()

    @Slot(str, str)
    def set_state(self, state: str, text: str = "") -> None:
        """Update the overlay display. Call from main thread or via queued signal."""
        if not self._enabled:
            return

        self._anim_timer.stop()

        if state == STATE_IDLE:
            self.hide()
            return

        self.show()

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
            QTimer.singleShot(self.RESULT_DISPLAY_MS, self.hide)

        elif state == STATE_ERROR:
            self._label.setStyleSheet(f"color: {COLOR_ERROR}; background: transparent;")
            display = text if len(text) <= 30 else text[:28] + "..."
            self._label.setText(display)
            QTimer.singleShot(self.RESULT_DISPLAY_MS, self.hide)

    # --- Animation ---

    def _animate_recording(self) -> None:
        dots = "\u25cf" * ((self._anim_step % 3) + 1)
        self._label.setText(f"录音中 {dots}")
        self._anim_step += 1
