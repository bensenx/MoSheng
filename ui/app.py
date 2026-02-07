"""Application coordinator: QSystemTrayIcon + worker thread + component wiring."""

import logging
import queue
import threading

from PySide6.QtCore import QThread, Signal, Slot, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from settings_manager import SettingsManager
from core.asr_base import ASRBase
from core.audio_recorder import AudioRecorder
from core.text_injector import TextInjector
from core.hotkey_manager import HotkeyManager
from ui.overlay_window import (
    OverlayWindow, STATE_RECORDING, STATE_RECOGNIZING,
    STATE_RESULT, STATE_ERROR, STATE_IDLE,
)
from ui.styles import (
    COLOR_IDLE_TRAY, COLOR_RECORDING, COLOR_RECOGNIZING,
)

logger = logging.getLogger(__name__)

CMD_START = "start"
CMD_STOP = "stop"
CMD_QUIT = "quit"


class WorkerThread(QThread):
    """Processes recording/ASR commands from a queue, emits state signals."""

    state_changed = Signal(str, str)  # (state, text)

    def __init__(self, recorder: AudioRecorder, asr: ASRBase,
                 injector: TextInjector, settings: SettingsManager):
        super().__init__()
        self._recorder = recorder
        self._asr = asr
        self._injector = injector
        self._settings = settings
        self._cmd_queue: queue.Queue[str] = queue.Queue()
        self._hotword_context: str = ""

    @property
    def hotword_context(self) -> str:
        return self._hotword_context

    @hotword_context.setter
    def hotword_context(self, value: str) -> None:
        self._hotword_context = value

    def enqueue(self, cmd: str) -> None:
        self._cmd_queue.put(cmd)

    def run(self) -> None:
        while True:
            cmd = self._cmd_queue.get()
            if cmd == CMD_QUIT:
                break
            elif cmd == CMD_START:
                self._handle_start()
            elif cmd == CMD_STOP:
                self._handle_stop()

    def _handle_start(self) -> None:
        self._recorder.start_recording()
        self.state_changed.emit(STATE_RECORDING, "")
        if self._settings.get("output", "sound_enabled", default=True):
            import winsound
            threading.Thread(
                target=lambda: winsound.Beep(800, 100), daemon=True
            ).start()

    def _handle_stop(self) -> None:
        audio = self._recorder.stop_recording()
        if self._settings.get("output", "sound_enabled", default=True):
            import winsound
            threading.Thread(
                target=lambda: winsound.Beep(600, 100), daemon=True
            ).start()

        min_duration = self._settings.get("audio", "min_duration", default=0.3)
        if audio is None or len(audio) / self._recorder.sample_rate < min_duration:
            self.state_changed.emit(STATE_ERROR, "录音太短")
            return

        self.state_changed.emit(STATE_RECOGNIZING, "")

        try:
            text = self._asr.transcribe(audio, self._recorder.sample_rate,
                                          context=self._hotword_context)
            if text.strip():
                self._injector.inject_text(text)
                self.state_changed.emit(STATE_RESULT, text)
            else:
                self.state_changed.emit(STATE_ERROR, "未识别到内容")
        except Exception:
            logger.exception("Transcription failed")
            self.state_changed.emit(STATE_ERROR, "识别失败")


class VoiceInputApp:
    """Main application: tray icon, overlay, worker thread, hotkey manager."""

    def __init__(self, asr_engine: ASRBase, settings: SettingsManager):
        self._settings = settings

        # Audio recorder
        sr = settings.get("audio", "sample_rate", default=16000)
        input_dev = settings.get("audio", "input_device", default=None)
        self._recorder = AudioRecorder(sample_rate=sr, device=input_dev)

        # Text injector
        self._injector = TextInjector(
            restore_clipboard=settings.get("output", "restore_clipboard", default=True)
        )

        # Overlay
        self._overlay = OverlayWindow(
            enabled=settings.get("output", "overlay_enabled", default=True)
        )

        # Worker thread
        self._worker = WorkerThread(
            self._recorder, asr_engine, self._injector, settings
        )
        self._worker.state_changed.connect(self._on_state_changed,
                                            Qt.ConnectionType.QueuedConnection)
        self._worker.hotword_context = self._build_hotword_context()

        # Hotkey manager
        hotkey_keys = settings.get("hotkey", "keys", default=["ctrl", "left windows"])
        hotkey_mode = settings.get("mode", default="push_to_talk")
        self._hotkey = HotkeyManager(
            hotkey_keys=hotkey_keys,
            on_start=lambda: self._worker.enqueue(CMD_START),
            on_stop=lambda: self._worker.enqueue(CMD_STOP),
            mode=hotkey_mode,
        )

        # System tray
        self._tray = QSystemTrayIcon()
        self._tray.setIcon(self._create_icon(COLOR_IDLE_TRAY))
        self._tray.setToolTip("VoiceInput - 就绪")

        menu = QMenu()
        settings_action = QAction("设置", menu)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)
        menu.addSeparator()
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)

        # Keep a reference to prevent GC of the menu
        self._tray_menu = menu

        self._settings_window = None

    def start(self) -> None:
        """Start background threads and show tray icon."""
        self._hotkey.start()
        self._worker.start()
        self._tray.show()

        logger.info("VoiceInput ready. Hotkey: %s",
                     self._settings.get("hotkey", "display"))

    # ---- State handling (main thread, via signal) ----

    @Slot(str, str)
    def _on_state_changed(self, state: str, text: str) -> None:
        self._overlay.set_state(state, text)

        if state == STATE_RECORDING:
            self._tray.setIcon(self._create_icon(COLOR_RECORDING))
            self._tray.setToolTip("VoiceInput - 录音中")
        elif state == STATE_RECOGNIZING:
            self._tray.setIcon(self._create_icon(COLOR_RECOGNIZING))
            self._tray.setToolTip("VoiceInput - 识别中")
        else:
            self._tray.setIcon(self._create_icon(COLOR_IDLE_TRAY))
            self._tray.setToolTip("VoiceInput - 就绪")

    # ---- Tray icon ----

    def _create_icon(self, color: str) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(0, 0, 0, 0))
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Circle background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(8, 8, 48, 48)

        # Microphone body
        p.setBrush(QColor("white"))
        p.drawRoundedRect(24, 16, 16, 22, 6, 6)

        # Arc under mic
        p.setPen(QColor("white"))
        p.setPen(p.pen())  # ensure pen is set
        from PySide6.QtGui import QPen
        arc_pen = QPen(QColor("white"), 2)
        p.setPen(arc_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(20, 28, 24, 20, 0, 180 * 16)

        # Stand
        p.drawLine(32, 48, 32, 54)
        p.drawLine(26, 54, 38, 54)

        p.end()
        return QIcon(pixmap)

    # ---- Settings ----

    def _open_settings(self) -> None:
        if self._settings_window is not None:
            try:
                self._settings_window.raise_()
                self._settings_window.activateWindow()
                return
            except RuntimeError:
                self._settings_window = None

        from ui.settings_window import SettingsWindow
        self._settings_window = SettingsWindow(
            self._settings,
            on_save=self._apply_settings,
        )
        self._settings_window.show()

    def _apply_settings(self) -> None:
        new_keys = self._settings.get("hotkey", "keys", default=["ctrl", "left windows"])
        self._hotkey.update_hotkey(new_keys)

        new_mode = self._settings.get("mode", default="push_to_talk")
        self._hotkey.update_mode(new_mode)

        self._injector.restore_clipboard = self._settings.get(
            "output", "restore_clipboard", default=True
        )
        self._overlay.enabled = self._settings.get(
            "output", "overlay_enabled", default=True
        )
        self._recorder.device = self._settings.get(
            "audio", "input_device", default=None
        )
        self._worker.hotword_context = self._build_hotword_context()
        logger.info("Settings applied")

    def _build_hotword_context(self) -> str:
        enabled = self._settings.get("vocabulary", "enabled", default=True)
        word_list = self._settings.get("vocabulary", "word_list", default=[])
        if not enabled or not word_list:
            return ""
        return ", ".join(word_list)

    # ---- Shutdown ----

    def _quit(self) -> None:
        logger.info("Shutting down...")
        self._worker.enqueue(CMD_QUIT)
        self._worker.wait(5000)
        self._hotkey.stop()
        self._overlay.close()
        self._tray.hide()
        QApplication.instance().quit()
