"""Click-through Windows input-mode indicator attached to the text caret."""

from threading import Event

from PySide6.QtCore import QRect, QThread, QTimer, Qt, Slot, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QLabel

from core.windows_input_mode import BadgeAnchor, badge_anchor, focused_mode, user32
from core.windows_uia_caret import AutomationCaret
from ui.styles import COLOR_ACCENT, COLOR_BASE_SOLID, COLOR_RESULT


class ModeWatcher(QThread):
    changed = Signal(object, object)

    def __init__(self, parent):
        super().__init__(parent)
        self.stopped = Event()

    def run(self):
        previous = None
        with AutomationCaret() as automation:
            while not self.stopped.is_set():
                focus, mode, info = focused_mode()
                anchor = badge_anchor(info, automation) if mode else None
                current = (focus, mode, anchor) if anchor else None
                if current != previous:
                    self.changed.emit(mode, anchor)
                    previous = current
                self.stopped.wait(0.12 if anchor else 0.28)


class InputModeBadge(QLabel):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._stem = QRect()
        self._label = QRect()
        self._watcher = None
        self._lit = True
        self._blink = QTimer(self)
        self._blink.timeout.connect(self._toggle_stem)

    def set_enabled(self, enabled: bool):
        if enabled and self._watcher is None:
            self._watcher = ModeWatcher(self)
            self._watcher.changed.connect(self._mode_changed, Qt.ConnectionType.QueuedConnection)
            self._watcher.start()
        elif not enabled and self._watcher is not None:
            watcher, self._watcher = self._watcher, None
            watcher.stopped.set()
            watcher.wait()
            watcher.deleteLater()
            self.display(None, None)

    @Slot(object, object)
    def _mode_changed(self, mode: str | None, anchor: BadgeAnchor | None):
        if self._watcher is not None and self.sender() is self._watcher:
            self.display(mode, anchor)

    def display(self, mode: str | None, anchor: BadgeAnchor | None):
        # Windows Qt keeps native monitor origins even at fractional scaling.
        # Its screen name can be the monitor's model, while GDI uses DISPLAYn.
        screen = next((s for s in QGuiApplication.screens()
                       if anchor and s.geometry().topLeft().toTuple() == anchor.monitor_origin), None)
        if not mode or screen is None:
            self._blink.stop()
            self.hide()
            return

        work = screen.availableGeometry()
        origin = screen.geometry().topLeft()
        scale = screen.devicePixelRatio()
        x = origin.x() + round(anchor.caret[0] / scale)
        bottom = origin.y() + round(anchor.caret[1] / scale)
        height = max(2, min(28, round(anchor.height / scale)))
        stem = QRect(x, bottom - height, 2, height)
        label_x = max(work.left(), min(x + 3, work.right() - 24))
        label_y = bottom + 2 if bottom + 19 <= work.bottom() + 1 else stem.top() - 19
        label = QRect(label_x, max(work.top(), label_y), 25, 17)
        bounds = stem.united(label).intersected(work)
        if bounds.isEmpty():
            self._blink.stop()
            self.hide()
            return
        self._stem = stem.translated(-bounds.topLeft())
        self._label = label.translated(-bounds.topLeft())
        self.setGeometry(bounds)
        self.setText(mode)
        self._lit = True
        interval = user32.GetCaretBlinkTime()
        if 0 < interval < 0xffffffff:  # INFINITE disables blinking in Windows.
            self._blink.start(interval)
        else:
            self._blink.stop()
        self.show()
        self.update()

    def _toggle_stem(self):
        self._lit = not self._lit
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(COLOR_ACCENT if self.text() == "中" else COLOR_RESULT)
        painter.setPen(Qt.PenStyle.NoPen)
        if self._lit:
            painter.setBrush(accent)
            painter.drawRoundedRect(self._stem, 1, 1)
        painter.setBrush(QColor(COLOR_BASE_SOLID))
        painter.drawRoundedRect(self._label, 5, 5)
        font = self.font()
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(accent)
        painter.drawText(self._label, Qt.AlignmentFlag.AlignCenter, self.text())
        painter.end()
