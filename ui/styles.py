"""Prism palette, native widget styles, and shared interface artwork."""

import os
import sys

from PySide6.QtCore import (
    Property, QEasingCurve, QPropertyAnimation, QRect, QRectF,
    QSize, Qt,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout, QLabel, QWidget

if sys.platform == "win32":
    import ctypes

from config import ASSETS_DIR

_ASSET_URL = ASSETS_DIR.replace(os.sep, "/")

# ---------------------------------------------------------------------------
# Prism palette
COLOR_BASE_SOLID = "#171521"
COLOR_HEADER = "#211b33"
COLOR_SURFACE = "#241f32"
COLOR_FIELD = "#302a40"
COLOR_SURFACE_HOVER = "#433950"
COLOR_SURFACE_ACTIVE = "#382d49"
COLOR_ACCENT = "#b6a4ff"
COLOR_ACCENT_HOVER = "#cabaff"
COLOR_PINK = "#fd92b5"
COLOR_RESULT = "#6be4d9"
COLOR_TEXT = "#f7f2ff"
COLOR_TEXT_SECONDARY = "#c2b7d3"
COLOR_BORDER = "#44394f"
COLOR_BORDER_HOVER = "#71617e"
COLOR_BORDER_FOCUS = COLOR_ACCENT

# ---------------------------------------------------------------------------
# Font
# ---------------------------------------------------------------------------
if sys.platform == "darwin":
    FONT_FAMILY = '"SF Pro Text", "PingFang SC", "Helvetica Neue", sans-serif'
else:
    FONT_FAMILY = '"Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI", sans-serif'

# ---------------------------------------------------------------------------
# Windows native title bar
# ---------------------------------------------------------------------------

def style_title_bar(widget: QWidget) -> None:
    """Use the system window controls on a matching dark Windows caption."""
    if sys.platform == "win32":
        color = QColor(COLOR_HEADER)
        hwnd = ctypes.c_void_p(int(widget.winId()))
        for attribute, value in ((20, 1), (35, color.red() | color.green() << 8 | color.blue() << 16)):
            setting = ctypes.c_int(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(setting), 4)


class PrismHeader(QWidget):
    """Title and static voice ribbon shared by Settings and startup."""
    def __init__(self, title: str, compact: bool = False):
        super().__init__()
        self._ribbon = QPixmap(os.path.join(ASSETS_DIR, "prism-ribbon.png"))
        self.setFixedHeight(66 if compact else 102)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18 if compact else 24, 0, 0, 0)
        label = QLabel(title)
        label.setStyleSheet(f"font-size: {26 if compact else 36}px; font-weight: 700;")
        layout.addWidget(label)
        layout.addStretch()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(COLOR_HEADER))
        if not self._ribbon.isNull():
            width = self.width() * 0.50
            height = width * self._ribbon.height() / self._ribbon.width()
            rect = QRectF(self.width() - width - 13, (self.height() - height) / 2, width, height)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(rect, self._ribbon, QRectF(self._ribbon.rect()))
        p.end()


FLUENT_DARK_STYLESHEET = f"""
/* ---- Global ---- */
* {{
    font-family: {FONT_FAMILY};
    font-size: 14px;
    color: {COLOR_TEXT};
}}

/* ---- QDialog / QWidget backgrounds ---- */
QDialog, QScrollArea, QWidget#settingsPage {{
    background-color: {COLOR_BASE_SOLID};
}}
QGroupBox {{
    background: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 13px;
    margin: 0;
    padding: 38px 9px 8px 9px;
}}
QGroupBox::title {{
    subcontrol-origin: border;
    subcontrol-position: top left;
    left: 42px; top: 12px;
    color: {COLOR_TEXT};
    font-size: 15px; font-weight: 600;
}}
QTabBar {{
    background: {COLOR_FIELD}; border-radius: 10px;
}}
QTabBar::tab {{
    background: transparent; color: {COLOR_TEXT_SECONDARY};
    padding: 6px 12px; margin: 3px; border-radius: 7px;
    border: 1px solid transparent;
}}
QTabBar::tab:selected {{ background: #51446e; color: {COLOR_TEXT}; }}
QTabBar::tab:hover:!selected {{ background: {COLOR_SURFACE_HOVER}; }}
QTabBar::tab:selected:focus, QPushButton:focus {{ border: 1px solid {COLOR_ACCENT}; }}
QSpinBox, QDoubleSpinBox {{
    background: {COLOR_FIELD}; color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 4px 8px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {COLOR_ACCENT}; }}
QProgressBar {{ background: {COLOR_FIELD}; border: none; border-radius: 4px; }}
QProgressBar::chunk {{ background: {COLOR_RESULT}; border-radius: 4px; }}

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
    background-color: {COLOR_FIELD};
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
    color: #201637;
    font-weight: 600;
}}
QPushButton#primaryButton:hover {{
    background-color: {COLOR_ACCENT_HOVER};
    border: 1px solid {COLOR_ACCENT_HOVER};
}}
QPushButton#primaryButton:pressed {{
    background-color: #a18be8;
}}

/* Danger button (hotkey capture) */
QPushButton#dangerButton {{
    background-color: rgba(244, 67, 54, 0.25);
    border: 1px solid rgba(244, 67, 54, 0.4);
    color: #ff6b6b;
}}

/* ---- QComboBox ---- */
QComboBox {{
    background-color: {COLOR_FIELD};
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
    image: url("{_ASSET_URL}/chevron-down.svg");
    width: 12px; height: 10px;
}}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    width: 24px; background: {COLOR_SURFACE_ACTIVE};
    border-left: 1px solid {COLOR_BORDER};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-position: top right; border-top-right-radius: 6px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-position: bottom right; border-bottom-right-radius: 6px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{_ASSET_URL}/chevron-up.svg"); width: 10px; height: 8px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{_ASSET_URL}/chevron-down.svg"); width: 10px; height: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLOR_SURFACE};
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
    background-color: {COLOR_SURFACE};
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

class ToggleSwitch(QCheckBox):
    """A labeled switch with an animated thumb and a keyboard focus outline."""

    TRACK_WIDTH = 38
    TRACK_HEIGHT = 20
    KNOB_RADIUS = 6
    KNOB_MARGIN = 4

    def __init__(self, text: str = "", checked: bool = False, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setChecked(checked)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._knob_pos = 1.0 if checked else 0.0

        self._animation = QPropertyAnimation(self, b"knobPos", self)
        self._animation.setDuration(200)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.toggled.connect(self._animate_toggle)

        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _get_knob_pos(self) -> float:
        return self._knob_pos

    def _set_knob_pos(self, value: float) -> None:
        self._knob_pos = value
        self.update()

    knobPos = Property(float, _get_knob_pos, _set_knob_pos)

    def _animate_toggle(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._knob_pos)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def hitButton(self, point) -> bool:
        return self.rect().contains(point)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text())
        total_w = self.TRACK_WIDTH + (12 + text_w if text_w else 0)
        return QSize(total_w, 32)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_x = self.width() - self.TRACK_WIDTH
        track_rect = QRect(track_x + 1, (self.height() - self.TRACK_HEIGHT) // 2,
                           self.TRACK_WIDTH - 2, self.TRACK_HEIGHT)
        track_radius = self.TRACK_HEIGHT / 2

        if self._knob_pos > 0.5:
            track_color = QColor(COLOR_ACCENT)
            track_border = QColor(COLOR_ACCENT)
            track_border.setAlphaF(0.6)
        else:
            track_color = QColor(255, 255, 255, 20)
            track_border = QColor(255, 255, 255, 40)

        p.setBrush(track_color)
        p.setPen(QPen(QColor(COLOR_TEXT), 2) if self.hasFocus() else QPen(track_border, 1))
        p.drawRoundedRect(track_rect, track_radius, track_radius)

        knob_y = self.height() // 2
        x_off = self.KNOB_MARGIN + self.KNOB_RADIUS
        x_on = self.TRACK_WIDTH - self.KNOB_MARGIN - self.KNOB_RADIUS
        knob_x = track_x + x_off + (x_on - x_off) * self._knob_pos

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(int(knob_x - self.KNOB_RADIUS), int(knob_y - self.KNOB_RADIUS + 1),
                       self.KNOB_RADIUS * 2, self.KNOB_RADIUS * 2)
        p.setBrush(QColor("#201637" if self.isChecked() else COLOR_TEXT_SECONDARY))
        p.drawEllipse(int(knob_x - self.KNOB_RADIUS), int(knob_y - self.KNOB_RADIUS),
                       self.KNOB_RADIUS * 2, self.KNOB_RADIUS * 2)

        if self.text():
            p.setPen(QColor(COLOR_TEXT))
            p.drawText(0, 0, track_x - 8, self.height(),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       self.text())

        p.end()


# ---------------------------------------------------------------------------
# Settings section icons
# ---------------------------------------------------------------------------

class IconGroupBox(QGroupBox):
    def __init__(self, title: str, icon_name: str, parent: QWidget | None = None):
        super().__init__(title, parent)
        asset = "icon.ico" if icon_name == "microphone" else f"settings/{icon_name}.svg"
        self._section_icon = QIcon(os.path.join(ASSETS_DIR, asset))

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        self._section_icon.paint(painter, QRect(15, 11, 21, 21))
        painter.end()
