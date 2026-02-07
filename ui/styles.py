"""Fluent Design dark theme: QSS stylesheet, color constants, and ToggleSwitch widget."""

from PySide6.QtCore import (
    Property, QEasingCurve, QPropertyAnimation, QRect, QSize, Qt, Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

# ---------------------------------------------------------------------------
# Color palette  (Windows 11 Fluent Design dark)
# ---------------------------------------------------------------------------
COLOR_BASE = "#202020"
COLOR_SURFACE = "#2d2d2d"
COLOR_SURFACE_HOVER = "#383838"
COLOR_ACCENT = "#60cdff"
COLOR_ACCENT_HOVER = "#78d6ff"
COLOR_TEXT = "#ffffff"
COLOR_TEXT_SECONDARY = "#c5c5c5"
COLOR_TEXT_DISABLED = "#9d9d9d"
COLOR_BORDER = "#3d3d3d"
COLOR_BORDER_FOCUS = "#60cdff"

# Overlay / tray state colors  (Catppuccin-inspired)
COLOR_RECORDING = "#f38ba8"
COLOR_RECOGNIZING = "#f9e2af"
COLOR_RESULT = "#a6e3a1"
COLOR_ERROR = "#f38ba8"
COLOR_IDLE_TRAY = "#6c7086"

# Overlay background
COLOR_OVERLAY_BG = "#1e1e2e"
COLOR_OVERLAY_TEXT = "#cdd6f4"

# ---------------------------------------------------------------------------
# Global QSS stylesheet
# ---------------------------------------------------------------------------
FLUENT_DARK_STYLESHEET = """
/* ---- Global ---- */
* {
    font-family: "Segoe UI Variable", "Segoe UI", sans-serif;
    font-size: 14px;
    color: #ffffff;
}

/* ---- QDialog / QWidget backgrounds ---- */
QDialog, QWidget#settingsRoot {
    background-color: #202020;
}

/* ---- QGroupBox (card-like section) ---- */
QGroupBox {
    background-color: #2d2d2d;
    border: 1px solid #3d3d3d;
    border-radius: 8px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #c5c5c5;
    font-size: 13px;
}

/* ---- QLabel ---- */
QLabel {
    background: transparent;
    color: #ffffff;
}
QLabel#secondaryLabel {
    color: #c5c5c5;
}

/* ---- QLineEdit ---- */
QLineEdit {
    background-color: #383838;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 5px 8px;
    color: #ffffff;
    selection-background-color: #60cdff;
}
QLineEdit:focus {
    border: 1px solid #60cdff;
}
QLineEdit:read-only {
    background-color: #2d2d2d;
    color: #c5c5c5;
}

/* ---- QPushButton ---- */
QPushButton {
    background-color: #383838;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 6px 16px;
    color: #ffffff;
    min-width: 72px;
}
QPushButton:hover {
    background-color: #434343;
    border: 1px solid #4d4d4d;
}
QPushButton:pressed {
    background-color: #2d2d2d;
}

/* Primary / accent button */
QPushButton#primaryButton {
    background-color: #60cdff;
    border: 1px solid #60cdff;
    color: #000000;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background-color: #78d6ff;
    border: 1px solid #78d6ff;
}
QPushButton#primaryButton:pressed {
    background-color: #4db8e8;
}

/* Danger button (used during hotkey capture) */
QPushButton#dangerButton {
    background-color: #c42b1c;
    border: 1px solid #c42b1c;
    color: #ffffff;
}

/* ---- QComboBox ---- */
QComboBox {
    background-color: #383838;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 5px 8px;
    color: #ffffff;
    min-width: 120px;
}
QComboBox:hover {
    border: 1px solid #4d4d4d;
}
QComboBox:focus {
    border: 1px solid #60cdff;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #c5c5c5;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    border: 1px solid #3d3d3d;
    selection-background-color: #383838;
    color: #ffffff;
    outline: none;
}

/* ---- QRadioButton ---- */
QRadioButton {
    spacing: 8px;
    background: transparent;
}
QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 2px solid #9d9d9d;
    background-color: transparent;
}
QRadioButton::indicator:hover {
    border: 2px solid #c5c5c5;
}
QRadioButton::indicator:checked {
    border: 2px solid #60cdff;
    background-color: #60cdff;
}

/* ---- QScrollBar (thin, subtle) ---- */
QScrollBar:vertical {
    background: transparent;
    width: 6px;
}
QScrollBar::handle:vertical {
    background: #4d4d4d;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

/* ---- QMenu (tray context menu) ---- */
QMenu {
    background-color: #2d2d2d;
    border: 1px solid #3d3d3d;
    border-radius: 8px;
    padding: 4px 0;
}
QMenu::item {
    padding: 6px 24px;
    color: #ffffff;
}
QMenu::item:selected {
    background-color: #383838;
}
QMenu::separator {
    height: 1px;
    background: #3d3d3d;
    margin: 4px 8px;
}
"""

# ---------------------------------------------------------------------------
# ToggleSwitch custom widget
# ---------------------------------------------------------------------------

class ToggleSwitch(QWidget):
    """A Windows 11-style toggle switch with smooth animation."""

    toggled = Signal(bool)

    TRACK_WIDTH = 44
    TRACK_HEIGHT = 22
    KNOB_RADIUS = 7
    KNOB_MARGIN = 4

    def __init__(self, text: str = "", checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._checked = checked
        self._label_text = text
        self._knob_pos = 1.0 if checked else 0.0

        self._animation = QPropertyAnimation(self, b"knobPos", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # --- Qt property for animation ---
    def _get_knob_pos(self) -> float:
        return self._knob_pos

    def _set_knob_pos(self, value: float) -> None:
        self._knob_pos = value
        self.update()

    knobPos = Property(float, _get_knob_pos, _set_knob_pos)

    # --- Public API ---
    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        if self._checked == checked:
            return
        self._checked = checked
        self._knob_pos = 1.0 if checked else 0.0
        self.update()

    # --- Events ---
    def mousePressEvent(self, event) -> None:
        self._checked = not self._checked
        self._animation.stop()
        self._animation.setStartValue(self._knob_pos)
        self._animation.setEndValue(1.0 if self._checked else 0.0)
        self._animation.start()
        self.toggled.emit(self._checked)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self._label_text) if self._label_text else 0
        total_w = self.TRACK_WIDTH + (12 + text_w if text_w else 0)
        return QSize(total_w, 28)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Track
        track_rect = QRect(0, (self.height() - self.TRACK_HEIGHT) // 2,
                           self.TRACK_WIDTH, self.TRACK_HEIGHT)
        track_radius = self.TRACK_HEIGHT / 2

        if self._knob_pos > 0.5:
            p.setBrush(QColor(COLOR_ACCENT))
            p.setPen(QColor(COLOR_ACCENT))
        else:
            p.setBrush(QColor("#4d4d4d"))
            p.setPen(QColor("#6d6d6d"))
        p.drawRoundedRect(track_rect, track_radius, track_radius)

        # Knob
        knob_y = self.height() // 2
        x_off = self.KNOB_MARGIN + self.KNOB_RADIUS
        x_on = self.TRACK_WIDTH - self.KNOB_MARGIN - self.KNOB_RADIUS
        knob_x = x_off + (x_on - x_off) * self._knob_pos

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(int(knob_x - self.KNOB_RADIUS), int(knob_y - self.KNOB_RADIUS),
                       self.KNOB_RADIUS * 2, self.KNOB_RADIUS * 2)

        # Label text
        if self._label_text:
            p.setPen(QColor(COLOR_TEXT))
            text_x = self.TRACK_WIDTH + 12
            p.drawText(text_x, 0, self.width() - text_x, self.height(),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       self._label_text)

        p.end()
