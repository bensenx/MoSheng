"""Application coordinator: QSystemTrayIcon + worker thread + component wiring."""

import logging
import queue
import threading

import os

import numpy as np

from PySide6.QtCore import QThread, Signal, Slot, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from config import ASSETS_DIR
from i18n import tr

from settings_manager import SettingsManager
from core.asr_base import ASRBase
from core.audio_recorder import AudioRecorder
from core.text_injector import TextInjector
from core.hotkey_manager import DualHotkeyManager
from ui.overlay_window import (
    OverlayWindow, STATE_RECORDING, STATE_RECOGNIZING,
    STATE_RESULT, STATE_ERROR, STATE_FILTERED, STATE_IDLE,
)

logger = logging.getLogger(__name__)

CMD_START = "start"
CMD_STOP = "stop"
CMD_QUIT = "quit"


class WorkerThread(QThread):
    """Processes recording/ASR commands from a queue, emits state signals."""

    state_changed = Signal(str, str)  # (state, text)

    def __init__(self, recorder: AudioRecorder, asr: ASRBase,
                 injector: TextInjector, settings: SettingsManager,
                 speaker_verifier=None):
        super().__init__()
        self._recorder = recorder
        self._asr = asr
        self._injector = injector
        self._settings = settings
        self._speaker_verifier = speaker_verifier
        self._cmd_queue: queue.Queue[str] = queue.Queue()
        self._hotword_context: str = ""
        self._progressive: bool = False
        self._silence_threshold: float = 0.01
        self._silence_duration: float = 0.8

    @property
    def speaker_verifier(self):
        return self._speaker_verifier

    @speaker_verifier.setter
    def speaker_verifier(self, value) -> None:
        self._speaker_verifier = value

    @property
    def hotword_context(self) -> str:
        return self._hotword_context

    @hotword_context.setter
    def hotword_context(self, value: str) -> None:
        self._hotword_context = value

    @property
    def progressive(self) -> bool:
        return self._progressive

    @progressive.setter
    def progressive(self, value: bool) -> None:
        self._progressive = value

    @property
    def silence_threshold(self) -> float:
        return self._silence_threshold

    @silence_threshold.setter
    def silence_threshold(self, value: float) -> None:
        self._silence_threshold = value

    @property
    def silence_duration(self) -> float:
        return self._silence_duration

    @silence_duration.setter
    def silence_duration(self, value: float) -> None:
        self._silence_duration = value

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
        logger.info("Recording start (progressive=%s)", self._progressive)
        self._recorder.start_recording()
        if self._settings.get("output", "sound_enabled", default=True):
            import winsound
            threading.Thread(
                target=lambda: winsound.Beep(800, 100), daemon=True
            ).start()

        if self._progressive:
            self._run_progressive_loop()

    def _run_progressive_loop(self) -> None:
        """Monitor for speech pauses and transcribe incrementally."""
        import time

        if self._settings.get("output", "restore_clipboard", default=True):
            self._injector.save_clipboard()

        silence_start: float | None = None
        had_speech = False
        injected_any = False

        while True:
            try:
                cmd = self._cmd_queue.get(timeout=0.05)
                if cmd == CMD_STOP:
                    break
                elif cmd == CMD_QUIT:
                    self._cmd_queue.put(CMD_QUIT)
                    break
            except queue.Empty:
                pass

            rms = self._recorder.current_rms
            if rms < self._silence_threshold:
                if had_speech and silence_start is None:
                    silence_start = time.monotonic()
                elif (had_speech and silence_start is not None
                      and time.monotonic() - silence_start >= self._silence_duration):
                    audio = self._recorder.drain_buffer()
                    if self._flush_and_inject(audio, use_clipboard_restore=False):
                        injected_any = True
                    self.state_changed.emit(STATE_RECORDING, "")
                    silence_start = None
                    had_speech = False
            else:
                had_speech = True
                silence_start = None

        # Final flush
        audio = self._recorder.stop_recording()
        if self._settings.get("output", "sound_enabled", default=True):
            import winsound
            threading.Thread(
                target=lambda: winsound.Beep(600, 100), daemon=True
            ).start()

        final_ok = False
        min_dur = self._settings.get("audio", "min_duration", default=0.3)
        if audio is not None and len(audio) / self._recorder.sample_rate >= min_dur:
            final_ok = self._flush_and_inject(audio, use_clipboard_restore=False)
            if final_ok:
                injected_any = True

        if self._settings.get("output", "restore_clipboard", default=True):
            self._injector.restore_saved_clipboard()

        if not injected_any:
            self.state_changed.emit(STATE_ERROR, tr("worker.no_content"))
        elif not final_ok:
            self.state_changed.emit(STATE_IDLE, "")

    def _handle_stop(self) -> None:
        audio = self._recorder.stop_recording()
        if self._settings.get("output", "sound_enabled", default=True):
            import winsound
            threading.Thread(
                target=lambda: winsound.Beep(600, 100), daemon=True
            ).start()

        if not self._flush_and_inject(audio):
            self.state_changed.emit(STATE_ERROR, tr("worker.too_short"))

    def _flush_and_inject(self, audio: np.ndarray | None,
                          use_clipboard_restore: bool = True) -> bool:
        """Transcribe audio and inject text. Returns True if text was injected."""
        min_duration = self._settings.get("audio", "min_duration", default=0.3)
        if audio is None or len(audio) / self._recorder.sample_rate < min_duration:
            return False

        # Speaker verification (if enabled and enrolled)
        if (self._speaker_verifier is not None
                and self._settings.get("speaker_verification", "enabled", default=False)):
            try:
                result = self._speaker_verifier.verify(audio, self._recorder.sample_rate)
                if not result.is_user:
                    logger.info("Speaker filtered: path=%s, score=%.4f", result.path, result.score)
                    self.state_changed.emit(STATE_FILTERED, "")
                    return False
                if result.audio is not None:
                    audio = result.audio
            except Exception:
                logger.exception("Speaker verification failed, proceeding with ASR")

        self.state_changed.emit(STATE_RECOGNIZING, "")

        try:
            text = self._asr.transcribe(audio, self._recorder.sample_rate,
                                          context=self._hotword_context)
            if text.strip():
                if use_clipboard_restore:
                    self._injector.inject_text(text)
                else:
                    self._injector.inject_text_no_restore(text)
                self.state_changed.emit(STATE_RESULT, text)
                return True
        except Exception:
            logger.exception("Transcription failed")
            self.state_changed.emit(STATE_ERROR, tr("worker.recognition_failed"))
        return False


class MoShengApp:
    """Main application: tray icon, overlay, worker thread, hotkey manager."""

    def __init__(self, asr_engine: ASRBase, settings: SettingsManager,
                 speaker_verifier=None):
        self._settings = settings
        self._speaker_verifier = speaker_verifier

        # Migrate old single-hotkey config to dual-binding format
        self._migrate_hotkey_settings()

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
            enabled=settings.get("output", "overlay_enabled", default=True),
            recorder=self._recorder,
        )

        # Worker thread
        self._worker = WorkerThread(
            self._recorder, asr_engine, self._injector, settings,
            speaker_verifier=speaker_verifier,
        )
        self._worker.state_changed.connect(self._on_state_changed,
                                            Qt.ConnectionType.QueuedConnection)
        self._worker.hotword_context = self._build_hotword_context()
        self._worker.progressive = settings.get("hotkey", "progressive", default=False)
        self._worker.silence_threshold = settings.get("hotkey", "silence_threshold", default=0.01)
        self._worker.silence_duration = settings.get("hotkey", "silence_duration", default=0.8)

        # Dual hotkey manager
        ptt = settings.get("hotkey", "push_to_talk", default={})
        toggle = settings.get("hotkey", "toggle", default={})
        self._hotkey = DualHotkeyManager(
            ptt_keys=ptt.get("keys", ["caps lock"]),
            ptt_enabled=ptt.get("enabled", True),
            ptt_long_press_ms=ptt.get("long_press_ms", 300),
            toggle_keys=toggle.get("keys", ["right ctrl"]),
            toggle_enabled=toggle.get("enabled", True),
            on_start=self._on_hotkey_start,
            on_stop=lambda: self._worker.enqueue(CMD_STOP),
        )

        # Wire hotkey VK codes to the text injector
        self._injector.hotkey_vks = self._hotkey.hotkey_vks

        # Application icon (loaded from assets if available)
        self._app_icon = self._load_app_icon()

        # System tray — use the app icon
        self._tray = QSystemTrayIcon()
        if self._app_icon:
            self._tray.setIcon(self._app_icon)
        self._tray.setToolTip(tr("tray.ready"))

        menu = QMenu()
        settings_action = QAction(tr("tray.settings"), menu)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)
        menu.addSeparator()
        quit_action = QAction(tr("tray.quit"), menu)
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

        logger.info("MoSheng ready (dual hotkey mode)")

    # ---- Hotkey callbacks (run on hook/timer threads) ----

    def _on_hotkey_start(self) -> None:
        """Called from hook thread when recording is triggered.

        Immediately emit STATE_RECORDING so the overlay appears without
        waiting for the worker thread to dequeue and process CMD_START.
        """
        self._worker.state_changed.emit(STATE_RECORDING, "")
        self._worker.enqueue(CMD_START)

    # ---- State handling (main thread, via signal) ----

    @Slot(str, str)
    def _on_state_changed(self, state: str, text: str) -> None:
        self._overlay.set_state(state, text)

        if state == STATE_RECORDING:
            self._tray.setToolTip(tr("tray.recording"))
        elif state == STATE_RECOGNIZING:
            self._tray.setToolTip(tr("tray.recognizing"))
        else:
            self._tray.setToolTip(tr("tray.ready"))

    # ---- Icons ----

    def _load_app_icon(self) -> QIcon | None:
        """Load main app icon from assets/ (ico or png)."""
        for ext in ("ico", "png"):
            path = os.path.join(ASSETS_DIR, f"icon.{ext}")
            if os.path.isfile(path):
                icon = QIcon(path)
                if not icon.isNull():
                    return icon
        return None

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
        # Update dual hotkey bindings
        ptt = self._settings.get("hotkey", "push_to_talk", default={})
        toggle = self._settings.get("hotkey", "toggle", default={})
        self._hotkey.update_bindings(
            ptt_keys=ptt.get("keys", ["caps lock"]),
            ptt_enabled=ptt.get("enabled", True),
            ptt_long_press_ms=ptt.get("long_press_ms", 300),
            toggle_keys=toggle.get("keys", ["right ctrl"]),
            toggle_enabled=toggle.get("enabled", True),
        )
        self._injector.hotkey_vks = self._hotkey.hotkey_vks

        self._injector.restore_clipboard = self._settings.get(
            "output", "restore_clipboard", default=True
        )
        self._overlay.enabled = self._settings.get(
            "output", "overlay_enabled", default=True
        )
        self._recorder.device = self._settings.get(
            "audio", "input_device", default=None
        )
        self._worker.progressive = self._settings.get(
            "hotkey", "progressive", default=False
        )
        self._worker.silence_threshold = self._settings.get(
            "hotkey", "silence_threshold", default=0.01
        )
        self._worker.silence_duration = self._settings.get(
            "hotkey", "silence_duration", default=0.8
        )
        self._worker.hotword_context = self._build_hotword_context()

        # Speaker verification: lazy load/unload on toggle change
        sv_enabled = self._settings.get("speaker_verification", "enabled", default=False)
        if sv_enabled and self._speaker_verifier is None:
            self._load_speaker_verifier()
        elif not sv_enabled and self._speaker_verifier is not None:
            self._speaker_verifier.unload_model()
            self._speaker_verifier = None
            self._worker.speaker_verifier = None
            logger.info("Speaker verifier unloaded (disabled)")
        if self._speaker_verifier is not None:
            self._speaker_verifier.update_thresholds(
                self._settings.get("speaker_verification", "threshold", default=0.25),
                self._settings.get("speaker_verification", "high_threshold", default=0.40),
                self._settings.get("speaker_verification", "low_threshold", default=0.10),
            )
        logger.info("Settings applied")

    def _migrate_hotkey_settings(self) -> None:
        """Migrate old single-hotkey config to dual-binding format."""
        old_keys = self._settings.get("hotkey", "keys")
        if old_keys is None:
            return  # Already new format or fresh install

        old_mode = self._settings.get("mode", default="push_to_talk")
        old_display = self._settings.get("hotkey", "display", default="")

        # Build new structure: old binding goes to whichever mode was selected
        if old_mode == "toggle":
            ptt_cfg = {"enabled": False, "keys": ["caps lock"],
                       "display": "Caps Lock", "long_press_ms": 300}
            toggle_cfg = {"enabled": True, "keys": old_keys,
                          "display": old_display}
        else:
            ptt_cfg = {"enabled": True, "keys": old_keys,
                       "display": old_display, "long_press_ms": 300}
            toggle_cfg = {"enabled": False, "keys": ["right ctrl"],
                          "display": "Right Ctrl"}

        self._settings.set("hotkey", "push_to_talk", ptt_cfg)
        self._settings.set("hotkey", "toggle", toggle_cfg)

        # Remove old fields
        hotkey_data = self._settings.get("hotkey")
        if isinstance(hotkey_data, dict):
            hotkey_data.pop("keys", None)
            hotkey_data.pop("display", None)
        # Remove top-level "mode"
        all_settings = self._settings.all
        if "mode" in all_settings:
            # SettingsManager doesn't have a delete, so we set it via internal access
            # We just leave it; it won't interfere with new code
            pass

        self._settings.save()
        logger.info("Migrated old hotkey config (mode=%s) to dual-binding format",
                     old_mode)

    def _load_speaker_verifier(self) -> None:
        """Load speaker verification model on demand (when enabled at runtime)."""
        from config import SPEAKER_DIR
        from core.speaker_verifier import SpeakerVerifier

        device = self._settings.get("asr", "device", default="cuda:0")
        verifier = SpeakerVerifier(device=device)
        verifier.load_model()
        verifier.load_enrollment(SPEAKER_DIR)

        self._speaker_verifier = verifier
        self._worker.speaker_verifier = verifier
        logger.info("Speaker verifier loaded on demand")

    def _build_hotword_context(self) -> str:
        enabled = self._settings.get("vocabulary", "enabled", default=True)
        if not enabled:
            return ""
        from config import VOCABULARY_FILE
        try:
            with open(VOCABULARY_FILE, encoding="utf-8-sig") as f:
                words = [line.strip() for line in f
                         if line.strip() and not line.startswith("#")]
        except FileNotFoundError:
            return ""
        if not words:
            return ""
        return ", ".join(words)

    # ---- Shutdown ----

    def _quit(self) -> None:
        logger.info("Shutting down...")
        self._worker.enqueue(CMD_QUIT)
        self._worker.wait(5000)
        self._hotkey.stop()
        self._overlay.close()
        self._tray.hide()
        QApplication.instance().quit()
