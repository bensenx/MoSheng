"""Prism splash screen shown during model loading."""

from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QTimer, Property, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from i18n import tr
from ui.styles import COLOR_ACCENT, COLOR_BASE_SOLID, COLOR_PINK, COLOR_RESULT, COLOR_TEXT_SECONDARY, PrismHeader


class SplashScreen(QWidget):
    """Centered startup window with the Prism ribbon and loading status."""

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
        root.setContentsMargins(12, 10, 12, 14)
        root.setSpacing(5)
        root.addWidget(PrismHeader("MoSheng", compact=True))
        self._status_label = QLabel(tr("overlay.loading"), self)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("font-size: 15px; font-weight: 600; padding-left: 8px;")
        root.addWidget(self._status_label)
        self._hint_label = QLabel(self)
        self._hint_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px; padding-left: 8px;")
        self._hint_label.setWordWrap(True)
        self._hint_label.hide()
        root.addWidget(self._hint_label)
        root.addStretch()

        # Accent bar at bottom
        bar = QWidget(self)
        bar.setFixedHeight(3)
        bar.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {COLOR_PINK}, stop:0.5 {COLOR_ACCENT}, stop:1 {COLOR_RESULT});"
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

        bg = QColor(COLOR_BASE_SOLID)
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

    def set_hint(self, text: str) -> None:
        """Show or hide a secondary hint line below the status."""
        if text:
            self._hint_label.setText(text)
            self._hint_label.show()
        else:
            self._hint_label.hide()

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
