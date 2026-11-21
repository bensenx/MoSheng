"""Transient, non-activating Windows keyboard-mode badge."""

from threading import Event

from PySide6.QtCore import QThread, QTimer, Qt, Slot, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel

from core.windows_input_mode import BadgeAnchor, badge_anchor, focused_mode
from ui.styles import COLOR_ACCENT, COLOR_BASE_SOLID, COLOR_RESULT


class ModeWatcher(QThread):
    changed = Signal(object, object)

    def __init__(self, parent):
        super().__init__(parent)
        self.stopped = Event()

    def run(self):
        previous = candidate = (0, None)
        while not self.stopped.is_set():
            focus, mode, info = focused_mode()
            current = focus, mode
            # Let Windows finish switching IME contexts when focus changes.
            if current == candidate and current != previous:
                anchor = badge_anchor(info) if mode and mode != previous[1] else None
                self.changed.emit(mode, anchor)
                previous = current
            candidate = current
            self.stopped.wait(0.18)


class InputModeBadge(QLabel):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(42, 28)
        self._watcher = None
        self._expiry = QTimer(self)
        self._expiry.setSingleShot(True)
        self._expiry.timeout.connect(self.hide)

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
            self._expiry.stop()
            self.hide()

    @Slot(object, object)
    def _mode_changed(self, mode: str | None, anchor: BadgeAnchor | None):
        if self._watcher is not None and self.sender() is self._watcher:
            self.display(mode, anchor)

    def display(self, mode: str | None, anchor: BadgeAnchor | None):
        self._expiry.stop()
        if anchor is None or mode is None:
            self.hide()
            return
        screen = next((s for s in QGuiApplication.screens()
                       if s.name().casefold() == anchor.screen.casefold()), None)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
            anchor = BadgeAnchor("", None)
        if screen is None:
            self.hide()
            return
        work = screen.availableGeometry()
        if anchor.caret is None:
            x = work.right() - self.width() - 18
            y = work.bottom() - self.height() - 18
        else:
            origin = screen.geometry().topLeft()
            x = origin.x() + round(anchor.caret[0] / screen.devicePixelRatio()) + 8
            y = origin.y() + round(anchor.caret[1] / screen.devicePixelRatio()) + 6
            if y + self.height() > work.bottom() + 1:
                y -= self.height() + 28
        self.move(max(work.left(), min(x, work.right() - self.width() + 1)),
                  max(work.top(), min(y, work.bottom() - self.height() + 1)))
        color = COLOR_ACCENT if mode == "中" else COLOR_RESULT
        self.setStyleSheet(f"QLabel {{ background: {COLOR_BASE_SOLID}; color: {color}; "
                           f"border: 1px solid {color}; border-radius: 9px; "
                           "font-size: 14px; font-weight: 600; }")
        self.setText(mode)
        self.show()
        self._expiry.start(1100)
