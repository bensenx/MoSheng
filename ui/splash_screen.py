"""Glassmorphism splash screen shown during model loading."""

from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QTimer, Property, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.styles import (
    COLOR_ACCENT,
    COLOR_OVERLAY_BG,
    COLOR_TEXT,
    COLOR_TEXT_SECONDARY,
    FONT_FAMILY,
    load_icon_pixmap,
)


class SplashScreen(QWidget):
    """Centered splash window with glassmorphism backdrop and animated status."""

    WIDTH = 360
    HEIGHT = 180
    BG_RADIUS = 16
    FADE_DURATION_MS = 300

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._opacity = 0.0
        self._dot_count = 0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.WIDTH, self.HEIGHT)

        self._build_ui()
        self._center_on_screen()

        # Dot animation timer
        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._animate_dots)
        self._dot_timer.start(500)
        self._status_base = ""

        # Fade animation
        self._fade_anim = QPropertyAnimation(self, b"splashOpacity", self)
        self._fade_anim.setDuration(self.FADE_DURATION_MS)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        # Start fully visible (no fade-in — main thread blocks during model load
        # so QPropertyAnimation frames would never run)
        self.setWindowOpacity(1.0)
        self._opacity = 1.0

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(0)

        # Icon + title row
        title_row = QHBoxLayout()
        title_row.setSpacing(12)

        icon_label = QLabel(self)
        icon_label.setFixedSize(36, 36)
        pm = load_icon_pixmap(36)
        if pm:
            icon_label.setPixmap(pm)
        icon_label.setStyleSheet("background: transparent;")
        title_row.addWidget(icon_label)

        title = QLabel("MoSheng", self)
        title.setFont(QFont("Segoe UI Variable", 20, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; background: transparent;")
        title_row.addWidget(title)
        title_row.addStretch()

        root.addLayout(title_row)
        root.addSpacing(20)

        # Status text
        self._status_label = QLabel("Starting...", self)
        self._status_label.setFont(QFont("Segoe UI Variable", 12))
        self._status_label.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; background: transparent;"
        )
        root.addWidget(self._status_label)
        root.addStretch()

        # Accent bar at bottom
        bar = QWidget(self)
        bar.setFixedHeight(3)
        bar.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 transparent, stop:0.5 {COLOR_ACCENT}, stop:1 transparent);"
            f"border-radius: 1px;"
        )
        root.addWidget(bar)

    # --- Opacity property for fade ---

    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, value: float) -> None:
        self._opacity = value
        self.setWindowOpacity(value)
        if value <= 0.01:
            super().hide()
            self.close()

    splashOpacity = Property(float, _get_opacity, _set_opacity)

    # --- Painting ---

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg = QColor(COLOR_OVERLAY_BG)
        bg.setAlphaF(0.88)
        p.setBrush(bg)

        p.setPen(Qt.PenStyle.NoPen)

        p.drawRoundedRect(
            self.rect(),
            self.BG_RADIUS, self.BG_RADIUS,
        )
        p.end()

    # --- Positioning ---

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.WIDTH) // 2
        y = geo.y() + (geo.height() - self.HEIGHT) // 2
        self.move(x, y)

    # --- Dot animation ---

    def _animate_dots(self) -> None:
        if not self._status_base:
            return
        self._dot_count = (self._dot_count + 1) % 4
        dots = "." * self._dot_count if self._dot_count > 0 else ""
        self._status_label.setText(self._status_base + dots)

    # --- Public API ---

    def set_status(self, text: str) -> None:
        """Update status text. Trailing '...' is animated automatically."""
        if text.endswith("..."):
            self._status_base = text[:-3]
            self._dot_count = 0
            self._status_label.setText(self._status_base)
        else:
            self._status_base = ""
            self._status_label.setText(text)

    def show(self) -> None:
        """Show immediately at full opacity (no fade-in)."""
        self.setWindowOpacity(1.0)
        self._opacity = 1.0
        super().show()

    def finish(self) -> None:
        """Fade out and close the splash screen."""
        self._dot_timer.stop()
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()
