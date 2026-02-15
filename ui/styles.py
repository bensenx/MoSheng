"""Glassmorphism dark theme: QSS stylesheet, DWM backdrop, color constants, ToggleSwitch."""

import logging
import math
import sys

from PySide6.QtCore import (
    Property, QEasingCurve, QPointF, QPropertyAnimation, QRect, QRectF,
    QSize, Qt, Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGroupBox, QWidget

if sys.platform == "win32":
    import ctypes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color palette  (Glassmorphism dark)
# ---------------------------------------------------------------------------
COLOR_BASE = "rgba(20, 20, 24, 0.85)"
COLOR_BASE_SOLID = "#141418"
COLOR_SURFACE = "rgba(255, 255, 255, 0.12)"
COLOR_SURFACE_HOVER = "rgba(255, 255, 255, 0.16)"
COLOR_SURFACE_ACTIVE = "rgba(255, 255, 255, 0.08)"
COLOR_ACCENT = "#5b7fff"
COLOR_ACCENT_HOVER = "#7b9aff"
COLOR_TEXT = "#f0f0f0"
COLOR_TEXT_SECONDARY = "rgba(255, 255, 255, 0.55)"
COLOR_TEXT_DISABLED = "rgba(255, 255, 255, 0.28)"
COLOR_BORDER = "rgba(255, 255, 255, 0.08)"
COLOR_BORDER_HOVER = "rgba(255, 255, 255, 0.14)"
COLOR_BORDER_FOCUS = "#5b7fff"

# Overlay / tray state colors
COLOR_RECORDING = "#f38ba8"
COLOR_RECOGNIZING = "#f9e2af"
COLOR_RESULT = "#a6e3a1"
COLOR_ERROR = "#f38ba8"
COLOR_FILTERED = "#6c7086"
COLOR_IDLE_TRAY = "#6c7086"

# Overlay background
COLOR_OVERLAY_BG = "#1a1a24"
COLOR_OVERLAY_TEXT = "#e0e0e8"

# Ink waveform overlay colors
COLOR_INK_RECORDING = "#7b8fa8"
COLOR_INK_RECOGNIZING = "#d4a857"
COLOR_INK_FILTERED = "#6c7086"

# Five-color ink palette
COLOR_INK_PINE_SOOT = "#2d3436"
COLOR_INK_INDIGO = "#4a6fa5"
COLOR_INK_OCHRE = "#b87333"
COLOR_INK_CINNABAR = "#c24c40"
COLOR_INK_GAMBOGE = "#d4a857"

# ---------------------------------------------------------------------------
# Font
# ---------------------------------------------------------------------------
if sys.platform == "darwin":
    FONT_FAMILY = '"SF Pro Text", "PingFang SC", "Helvetica Neue", sans-serif'
else:
    FONT_FAMILY = '"Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI", sans-serif'

# ---------------------------------------------------------------------------
# Windows DWM Acrylic / Mica backdrop
# ---------------------------------------------------------------------------

def apply_acrylic_effect(hwnd: int) -> bool:
    """Apply platform-specific translucent backdrop. Returns True on success.

    On macOS this is a no-op — Qt's WA_TranslucentBackground handles transparency.
    The Windows DWM Acrylic path is only available on Windows.
    """
    if sys.platform != "win32":
        return False
    try:
        attr = 38
        value = ctypes.c_int(3)
        hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
        )
        if hr != 0:
            value = ctypes.c_int(4)
            hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
            )
        dark = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark)
        )

        class MARGINS(ctypes.Structure):
            _fields_ = [
                ("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int),
            ]
        margins = MARGINS(-1, -1, -1, -1)
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        return hr == 0
    except Exception:
        logger.debug("DWM acrylic effect not available")
        return False


# ---------------------------------------------------------------------------
# Global QSS stylesheet (Glassmorphism)
# ---------------------------------------------------------------------------
FLUENT_DARK_STYLESHEET = f"""
/* ---- Global ---- */
* {{
    font-family: {FONT_FAMILY};
    font-size: 14px;
    color: {COLOR_TEXT};
}}

/* ---- QDialog / QWidget backgrounds ---- */
QDialog, QWidget#settingsRoot {{
    background-color: transparent;
}}

/* Fallback solid bg when acrylic not available */
QDialog#settingsFallback {{
    background-color: {COLOR_BASE_SOLID};
}}

/* ---- QGroupBox (glass card) ---- */
QGroupBox {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 12px;
    margin-top: 14px;
    padding: 20px 16px 16px 16px;
    font-weight: 600;
    font-size: 13px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 10px 2px 34px;
    color: {COLOR_TEXT_SECONDARY};
    font-size: 12px;
    font-weight: 500;
}}

/* ---- QLabel ---- */
QLabel {{
    background: transparent;
    color: {COLOR_TEXT};
}}
QLabel#secondaryLabel {{
    color: {COLOR_TEXT_SECONDARY};
}}
QLabel#sectionIcon {{
    font-size: 16px;
    padding-right: 6px;
}}

/* ---- QLineEdit ---- */
QLineEdit {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 7px 12px;
    color: {COLOR_TEXT};
    selection-background-color: {COLOR_ACCENT};
}}
QLineEdit:focus {{
    border: 1px solid {COLOR_BORDER_FOCUS};
}}
QLineEdit:read-only {{
    background-color: rgba(255, 255, 255, 0.03);
    color: {COLOR_TEXT_SECONDARY};
}}

/* ---- QPushButton ---- */
QPushButton {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 8px 20px;
    color: {COLOR_TEXT};
    min-width: 80px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {COLOR_SURFACE_HOVER};
    border: 1px solid {COLOR_BORDER_HOVER};
}}
QPushButton:pressed {{
    background-color: {COLOR_SURFACE_ACTIVE};
}}

/* Primary / accent button */
QPushButton#primaryButton {{
    background-color: {COLOR_ACCENT};
    border: 1px solid {COLOR_ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#primaryButton:hover {{
    background-color: {COLOR_ACCENT_HOVER};
    border: 1px solid {COLOR_ACCENT_HOVER};
}}
QPushButton#primaryButton:pressed {{
    background-color: #4a6be0;
}}

/* Danger button (hotkey capture) */
QPushButton#dangerButton {{
    background-color: rgba(244, 67, 54, 0.25);
    border: 1px solid rgba(244, 67, 54, 0.4);
    color: #ff6b6b;
}}

/* ---- QComboBox ---- */
QComboBox {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 7px 12px;
    color: {COLOR_TEXT};
    min-width: 120px;
}}
QComboBox:hover {{
    border: 1px solid {COLOR_BORDER_HOVER};
    background-color: {COLOR_SURFACE_HOVER};
}}
QComboBox:focus {{
    border: 1px solid {COLOR_BORDER_FOCUS};
}}
QComboBox::drop-down {{
    border: none;
    width: 28px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 5px solid rgba(255, 255, 255, 0.45);
    margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: rgba(30, 30, 36, 0.95);
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    selection-background-color: {COLOR_SURFACE_HOVER};
    color: {COLOR_TEXT};
    outline: none;
    padding: 4px;
}}
QComboBox QAbstractItemView::item {{
    padding: 6px 12px;
    border-radius: 6px;
}}
QComboBox QAbstractItemView::item:selected {{
    background-color: {COLOR_SURFACE_HOVER};
}}

/* ---- QRadioButton ---- */
QRadioButton {{
    spacing: 8px;
    background: transparent;
}}
QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 2px solid rgba(255, 255, 255, 0.3);
    background-color: transparent;
}}
QRadioButton::indicator:hover {{
    border: 2px solid rgba(255, 255, 255, 0.45);
}}
QRadioButton::indicator:checked {{
    border: 2px solid {COLOR_ACCENT};
    background-color: {COLOR_ACCENT};
}}

/* ---- QListWidget ---- */
QListWidget {{
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 4px;
    color: {COLOR_TEXT};
    outline: none;
}}
QListWidget::item {{
    padding: 5px 8px;
    border-radius: 6px;
}}
QListWidget::item:selected {{
    background-color: rgba(91, 127, 255, 0.25);
    color: {COLOR_TEXT};
}}
QListWidget::item:hover {{
    background-color: {COLOR_SURFACE_HOVER};
}}

/* ---- QScrollBar (thin, subtle) ---- */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.15);
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

/* ---- QMenu (tray context menu) ---- */
QMenu {{
    background-color: rgba(30, 30, 36, 0.92);
    border: 1px solid {COLOR_BORDER};
    border-radius: 12px;
    padding: 6px 4px;
}}
QMenu::item {{
    padding: 8px 28px 8px 16px;
    border-radius: 8px;
    margin: 2px 4px;
    color: {COLOR_TEXT};
}}
QMenu::item:selected {{
    background-color: {COLOR_SURFACE_HOVER};
}}
QMenu::separator {{
    height: 1px;
    background: {COLOR_BORDER};
    margin: 4px 12px;
}}
"""

# ---------------------------------------------------------------------------
# ToggleSwitch custom widget
# ---------------------------------------------------------------------------

class ToggleSwitch(QWidget):
    """A glassmorphism-style toggle switch with smooth animation."""

    toggled = Signal(bool)

    TRACK_WIDTH = 44
    TRACK_HEIGHT = 24
    KNOB_RADIUS = 8
    KNOB_MARGIN = 4

    def __init__(self, text: str = "", checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._checked = checked
        self._label_text = text
        self._knob_pos = 1.0 if checked else 0.0

        self._animation = QPropertyAnimation(self, b"knobPos", self)
        self._animation.setDuration(200)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _get_knob_pos(self) -> float:
        return self._knob_pos

    def _set_knob_pos(self, value: float) -> None:
        self._knob_pos = value
        self.update()

    knobPos = Property(float, _get_knob_pos, _set_knob_pos)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        if self._checked == checked:
            return
        self._checked = checked
        self._knob_pos = 1.0 if checked else 0.0
        self.update()

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
        return QSize(total_w, 32)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_rect = QRect(0, (self.height() - self.TRACK_HEIGHT) // 2,
                           self.TRACK_WIDTH, self.TRACK_HEIGHT)
        track_radius = self.TRACK_HEIGHT / 2

        if self._knob_pos > 0.5:
            track_color = QColor(COLOR_ACCENT)
            track_border = QColor(COLOR_ACCENT)
            track_border.setAlphaF(0.6)
        else:
            track_color = QColor(255, 255, 255, 20)
            track_border = QColor(255, 255, 255, 40)

        p.setBrush(track_color)
        p.setPen(QPen(track_border, 1))
        p.drawRoundedRect(track_rect, track_radius, track_radius)

        knob_y = self.height() // 2
        x_off = self.KNOB_MARGIN + self.KNOB_RADIUS
        x_on = self.TRACK_WIDTH - self.KNOB_MARGIN - self.KNOB_RADIUS
        knob_x = x_off + (x_on - x_off) * self._knob_pos

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(int(knob_x - self.KNOB_RADIUS), int(knob_y - self.KNOB_RADIUS + 1),
                       self.KNOB_RADIUS * 2, self.KNOB_RADIUS * 2)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(int(knob_x - self.KNOB_RADIUS), int(knob_y - self.KNOB_RADIUS),
                       self.KNOB_RADIUS * 2, self.KNOB_RADIUS * 2)

        if self._label_text:
            p.setPen(QColor(COLOR_TEXT))
            text_x = self.TRACK_WIDTH + 12
            p.drawText(text_x, 0, self.width() - text_x, self.height(),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       self._label_text)

        p.end()


# ---------------------------------------------------------------------------
# App icon loader (high-DPI)
# ---------------------------------------------------------------------------

def _screen_dpr() -> float:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        screen = app.primaryScreen()
        if screen is not None:
            return max(screen.devicePixelRatio(), 2.0)
    return 2.0


def load_icon_pixmap(logical_size: int) -> QPixmap | None:
    import os
    from config import ASSETS_DIR

    dpr = _screen_dpr()
    icon_exts = ("png", "icns") if sys.platform == "darwin" else ("png", "ico")
    for ext in icon_exts:
        path = os.path.join(ASSETS_DIR, f"icon.{ext}")
        if os.path.isfile(path):
            physical = round(logical_size * dpr)
            pm = QPixmap(path).scaled(
                physical, physical,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            pm.setDevicePixelRatio(dpr)
            return pm
    return None


# ---------------------------------------------------------------------------
# Section icons (QPainter line art)
# ---------------------------------------------------------------------------

def draw_section_icon(name: str, color: str = COLOR_ACCENT, size: int = 18) -> QPixmap:
    dpr = _screen_dpr()
    ps = round(size * dpr)
    pixmap = QPixmap(ps, ps)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(QColor(0, 0, 0, 0))
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(QColor(color), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    s = float(size)

    if name == "keyboard":
        p.drawRoundedRect(QRectF(1, 3, s - 2, s - 6), 2.5, 2.5)
        ks = s * 0.16
        for x in [s * 0.25, s * 0.5, s * 0.75]:
            p.drawRoundedRect(QRectF(x - ks / 2, s * 0.38 - ks / 2, ks, ks), 0.8, 0.8)
        p.drawLine(QPointF(s * 0.3, s * 0.68), QPointF(s * 0.7, s * 0.68))

    elif name == "waveform":
        heights = [0.3, 0.6, 1.0, 0.6, 0.3]
        gap = s * 0.18
        bar_w = s * 0.1
        start_x = (s - (5 * bar_w + 4 * gap)) / 2
        cy = s / 2
        for i, h in enumerate(heights):
            x = start_x + i * (bar_w + gap) + bar_w / 2
            half_h = h * s * 0.38
            p.drawLine(QPointF(x, cy - half_h), QPointF(x, cy + half_h))

    elif name == "microphone":
        cx = s / 2
        cap_w = s * 0.35
        cap_h = s * 0.45
        p.drawRoundedRect(QRectF(cx - cap_w / 2, s * 0.05, cap_w, cap_h), cap_w / 2, cap_w / 2)
        cradle_w = s * 0.55
        cradle_h = s * 0.3
        p.drawArc(QRectF(cx - cradle_w / 2, s * 0.28, cradle_w, cradle_h).toRect(), 0, -180 * 16)
        p.drawLine(QPointF(cx, s * 0.73), QPointF(cx, s * 0.85))
        p.drawLine(QPointF(cx - s * 0.18, s * 0.85), QPointF(cx + s * 0.18, s * 0.85))

    elif name == "gear":
        cx, cy = s / 2, s / 2
        r_outer = s * 0.42
        r_inner = s * 0.30
        r_center = s * 0.15
        teeth = 6
        path = QPainterPath()
        for i in range(teeth * 2):
            angle = math.pi * i / teeth - math.pi / 2
            r = r_outer if i % 2 == 0 else r_inner
            x = cx + r * math.cos(angle)
            y = cy + r * math.sin(angle)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
        p.drawPath(path)
        p.drawEllipse(QPointF(cx, cy), r_center, r_center)

    elif name == "book":
        cx = s / 2
        p.drawLine(QPointF(cx, s * 0.15), QPointF(cx, s * 0.85))
        path_l = QPainterPath()
        path_l.moveTo(cx, s * 0.15)
        path_l.quadTo(s * 0.1, s * 0.15, s * 0.1, s * 0.25)
        path_l.lineTo(s * 0.1, s * 0.75)
        path_l.quadTo(s * 0.1, s * 0.85, cx, s * 0.85)
        p.drawPath(path_l)
        path_r = QPainterPath()
        path_r.moveTo(cx, s * 0.15)
        path_r.quadTo(s * 0.9, s * 0.15, s * 0.9, s * 0.25)
        path_r.lineTo(s * 0.9, s * 0.75)
        path_r.quadTo(s * 0.9, s * 0.85, cx, s * 0.85)
        p.drawPath(path_r)

    elif name == "shield":
        cx = s / 2
        path = QPainterPath()
        path.moveTo(cx, s * 0.08)
        path.lineTo(s * 0.88, s * 0.28)
        path.quadTo(s * 0.88, s * 0.62, cx, s * 0.92)
        path.quadTo(s * 0.12, s * 0.62, s * 0.12, s * 0.28)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(cx - s * 0.15, s * 0.50), QPointF(cx - s * 0.02, s * 0.63))
        p.drawLine(QPointF(cx - s * 0.02, s * 0.63), QPointF(cx + s * 0.18, s * 0.38))

    elif name == "power":
        cx = s / 2
        r = s * 0.32
        arc_rect = QRectF(cx - r, s * 0.5 - r, r * 2, r * 2)
        start_angle = 60 * 16
        span_angle = 240 * 16
        p.drawArc(arc_rect.toRect(), start_angle, span_angle)
        p.drawLine(QPointF(cx, s * 0.10), QPointF(cx, s * 0.45))

    p.end()
    return pixmap


# ---------------------------------------------------------------------------
# IconGroupBox: QGroupBox with a painted section icon
# ---------------------------------------------------------------------------

COLOR_ICON = "#8aa4ff"

class IconGroupBox(QGroupBox):
    def __init__(self, title: str, icon_name: str, parent: QWidget | None = None):
        super().__init__(title, parent)
        self._icon_pixmap = draw_section_icon(icon_name, COLOR_ICON, 18)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        x = 12
        y = -1
        p.drawPixmap(x, y, self._icon_pixmap)
        p.end()
