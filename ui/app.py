"""Application coordinator: QSystemTrayIcon + worker thread + component wiring."""

from dataclasses import dataclass, field
import logging
import threading
import queue
import sys

import os

import numpy as np

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from config import ASSETS_DIR
from i18n import tr

from settings_manager import SettingsManager
from core.asr_base import ASRBase
from core.audio_recorder import AudioRecorder
from core.sound_player import SoundPlayer
from core.text_injector import TextInjector
from core.text_processor import TextProcessor
from core.hotkey_manager import DualHotkeyManager
from ui.overlay_window import (
    OverlayWindow, STATE_RECORDING, STATE_RECOGNIZING,
    STATE_RESULT, STATE_ERROR, STATE_FILTERED, STATE_IDLE,
    STATE_LOADING,
)

logger = logging.getLogger(__name__)

CMD_START = "start"
CMD_STOP = "stop"
CMD_QUIT = "quit"


@dataclass(eq=False)
class Recording:
    progressive: bool
    restore_clipboard: bool
    verifier: object | None
    # A final chunk can be empty. A bare None cancels an unfinished capture.
    chunks: queue.Queue[tuple[np.ndarray | None, bool] | None] = field(default_factory=queue.Queue)


class WorkerThread(QThread):
    """Processes recording/ASR commands from a queue, emits state signals."""

    state_changed = Signal(str, str)  # (state, text)

    _MIN_SPEECH_BEFORE_FLUSH = 0.5   # seconds of speech required before allowing flush
    _MAX_SILENCE_FORCE_FLUSH = 3.0   # seconds of continuous silence to force-flush

    def __init__(self, recorder: AudioRecorder, asr: ASRBase | None,
                 injector: TextInjector, settings: SettingsManager,
                 speaker_verifier=None):
        super().__init__()
        self._recorder = recorder
        self._asr = asr
        self._injector = injector
        self._settings = settings
        self._speaker_verifier = speaker_verifier
        self.verifier_error = ""
        self._recordings: queue.Queue[Recording | None] = queue.Queue()
        self._capture: Recording | None = None
        self._latest_recording: Recording | None = None
        self._cmd_queue: queue.Queue[str] = queue.Queue()
        self._shutting_down = threading.Event()
        self._text_processor = TextProcessor(
            remove_fillers=settings.get("text_processing", "remove_fillers", default=True),
            smart_punctuation=settings.get("text_processing", "smart_punctuation", default=True),
        )
        self._hotword_context: str = ""
        self._progressive: bool = False
        self._silence_duration: float = 0.8
        self._vad = None  # SileroVAD instance, set by MoShengApp
        self._sound_player = None  # Assigned by MoShengApp after construction

    @property
    def speaker_verifier(self):
        return self._speaker_verifier

    @speaker_verifier.setter
    def speaker_verifier(self, value) -> None:
        self._speaker_verifier = value

    @property
    def text_processor(self) -> TextProcessor:
        return self._text_processor


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
    def silence_duration(self) -> float:
        return self._silence_duration

    @silence_duration.setter
    def silence_duration(self, value: float) -> None:
        self._silence_duration = value

    def enqueue(self, cmd: str) -> None:
        self._cmd_queue.put(cmd)

    def shutdown(self) -> None:
        self._shutting_down.set()
        self.enqueue(CMD_QUIT)

    def readiness_issue(self) -> tuple[str, str] | None:
        if self._asr is None or not self._asr.is_ready:
            return STATE_LOADING, tr("tray.loading")
        if self._settings.get("speaker_verification", "enabled", default=False):
            verifier = self._speaker_verifier
            if self.verifier_error:
                return STATE_ERROR, self.verifier_error
            if verifier is None or not verifier.is_ready:
                return STATE_LOADING, tr("worker.loading_verifier")
            if not verifier.is_enrolled:
                return STATE_ERROR, tr("worker.enroll_first")
        return None

    def run(self) -> None:
        decoder = threading.Thread(target=self._decode_recordings, name="DictationDecoder")
        decoder.start()
        try:
            while True:
                cmd = self._cmd_queue.get()
                if cmd == CMD_QUIT:
                    break
                try:
                    if cmd == CMD_START and self._capture is None:
                        self._handle_start()
                    elif cmd == CMD_STOP and self._capture is not None:
                        self._handle_stop()
                except Exception:
                    logger.exception("Recording session failed")
                    self._cancel_capture()
                    self.state_changed.emit(STATE_ERROR, tr("worker.recording_failed"))
        finally:
            self._cancel_capture()
            self._recordings.put(None)
            decoder.join()

    def _cancel_capture(self) -> None:
        if self._capture is not None:
            self._capture.chunks.put(None)
            self._capture = None
        if self._recorder.is_recording:
            try:
                self._recorder.stop_recording()
            except Exception:
                logger.exception("Could not close microphone")

    def _handle_start(self) -> None:
        issue = self.readiness_issue()
        if issue:
            self.state_changed.emit(*issue)
            return
        logger.info("Recording start (progressive=%s)", self._progressive)
        self._recorder.start_recording()
        session = Recording(
            progressive=self._progressive,
            restore_clipboard=self._settings.get("output", "restore_clipboard", default=True),
            verifier=self._speaker_verifier if self._settings.get("speaker_verification", "enabled", default=False) else None,
        )
        self._capture = self._latest_recording = session
        self._recordings.put(session)
        self.state_changed.emit(STATE_RECORDING, "")
        if self._sound_player:
            self._sound_player.play_start()

        if session.progressive:
            vad = self._vad
            if vad is not None:
                vad.reset_states()
            self._process_progressive_audio(session, vad)

    def _process_progressive_audio(self, session: Recording, vad) -> None:
        import time

        silence_start: float | None = None
        speech_start: float | None = None
        vad_leftover = np.array([], dtype=np.float32)

        while True:
            try:
                cmd = self._cmd_queue.get(timeout=0.05)
                if cmd == CMD_STOP:
                    self._handle_stop()
                    return
                elif cmd == CMD_QUIT:
                    self._cmd_queue.put(CMD_QUIT)
                    return
            except queue.Empty:
                pass

            # Determine speech/silence via VAD (or fallback to RMS)
            is_speech = False
            if vad is not None:
                new_samples = self._recorder.get_new_samples()
                if new_samples is not None:
                    combined = np.concatenate([vad_leftover, new_samples])
                    chunk_size = vad.chunk_size
                    pos = 0
                    while pos + chunk_size <= len(combined):
                        chunk = combined[pos:pos + chunk_size]
                        if vad.is_speech(chunk):
                            is_speech = True
                        pos += chunk_size
                    vad_leftover = combined[pos:]
            else:
                # Fallback: RMS-based (should not happen with VAD loaded)
                is_speech = self._recorder.current_rms >= 0.01

            if not is_speech:
                if speech_start is not None and silence_start is None:
                    silence_start = time.monotonic()
                elif speech_start is not None and silence_start is not None:
                    silence_elapsed = time.monotonic() - silence_start
                    speech_duration = silence_start - speech_start
                    pause = (silence_elapsed >= self._silence_duration
                             and speech_duration >= self._MIN_SPEECH_BEFORE_FLUSH)
                    if pause or silence_elapsed >= self._MAX_SILENCE_FORCE_FLUSH:
                        audio = self._recorder.drain_buffer()
                        session.chunks.put((audio, False))
                        silence_start = None
                        speech_start = None
                        vad_leftover = np.array([], dtype=np.float32)
            else:
                if speech_start is None:
                    speech_start = time.monotonic()
                silence_start = None

    def _handle_stop(self) -> None:
        audio = self._recorder.stop_recording()
        session, self._capture = self._capture, None
        if audio is not None:
            self.state_changed.emit(STATE_RECOGNIZING, "")
        session.chunks.put((audio, True))
        if self._sound_player:
            self._sound_player.play_stop()

    def _decode_recordings(self) -> None:
        while (session := self._recordings.get()) is not None:
            try:
                self._decode_session(session)
            except Exception:
                logger.exception("Could not process dictation")
                self._emit_for_session(session, STATE_ERROR, tr("worker.recognition_failed"))
            finally:
                # The UI keeps the latest recording for status. Release its model.
                session.verifier = None

    def _emit_for_session(self, session: Recording | None, state: str, text: str) -> None:
        if session is None or session is self._latest_recording:
            self.state_changed.emit(state, text)

    def _decode_session(self, session: Recording) -> None:
        self._text_processor.reset_session()
        restore = session.progressive and session.restore_clipboard
        if restore:
            self._injector.save_clipboard()
        injected_any = False
        last_outcome = None
        try:
            while (chunk := session.chunks.get()) is not None:
                audio, final = chunk
                if self._shutting_down.is_set():
                    return
                minimum = self._settings.get("audio", "min_duration", default=0.3)
                if session.progressive and final and (audio is None or len(audio) < minimum * self._recorder.sample_rate):
                    if last_outcome is None:
                        self._emit_for_session(session, STATE_ERROR, tr("worker.no_content"))
                    elif last_outcome[0] == STATE_RESULT:
                        self._emit_for_session(session, STATE_IDLE, "")
                else:
                    last_outcome = self._flush_and_inject(audio, use_clipboard_restore=not session.progressive,
                                                          use_deferred_period=session.progressive, session=session)
                    if last_outcome[0] == STATE_RESULT:
                        injected_any = True
                    if not final and last_outcome[0] == STATE_RESULT and self._recorder.is_recording:
                        self._emit_for_session(session, STATE_RECORDING, "")
                    else:
                        self._emit_for_session(session, *last_outcome)
                if final:
                    if session.progressive and injected_any:
                        period = self._text_processor.consume_pending_period()
                        if period and not self._shutting_down.is_set():
                            self._injector.inject_char_unicode(period)
                    return
        finally:
            if restore:
                self._injector.restore_saved_clipboard()

    def _flush_and_inject(self, audio: np.ndarray | None,
                          use_clipboard_restore: bool = True,
                          use_deferred_period: bool = True, session: Recording | None = None) -> tuple[str, str]:
        """Return one terminal state and its message for this segment."""
        min_duration = self._settings.get("audio", "min_duration", default=0.3)
        if audio is None or len(audio) / self._recorder.sample_rate < min_duration:
            return STATE_ERROR, tr("worker.too_short")

        issue = self.readiness_issue()
        if issue:
            return issue
        verified_by = session.verifier if session is not None else None
        if self._settings.get("speaker_verification", "enabled", default=False):
            verified_by = self._speaker_verifier
            if verified_by is None:
                return STATE_ERROR, tr("worker.verification_failed")
        if verified_by is not None:
            try:
                result = verified_by.verify(audio, self._recorder.sample_rate)
                if not result.is_user:
                    logger.info("Speaker filtered: path=%s, score=%.4f", result.path, result.score)
                    return STATE_FILTERED, tr("overlay.filtered")
                if result.audio is not None:
                    audio = result.audio
            except Exception:
                logger.exception("Speaker verification failed")
                return STATE_ERROR, tr("worker.verification_failed")

        if session is not None and session is self._capture and session.progressive:
            self._emit_for_session(session, STATE_RECOGNIZING, "")

        try:
            text = self._asr.transcribe(audio, self._recorder.sample_rate,
                                          context=self._hotword_context)
            text = (self._text_processor.process(text) if use_deferred_period
                    else self._text_processor.process_simple(text))

            # Quality filter: reject single-char garbage from short audio
            audio_duration = len(audio) / self._recorder.sample_rate
            if (self._text_processor.meaningful_length(text) <= 1
                    and audio_duration < 1.0):
                logger.debug("Quality filter: rejected '%s' (%.2fs audio)", text, audio_duration)
                return STATE_ERROR, tr("worker.no_content")

        except Exception:
            logger.exception("Transcription failed")
            return STATE_ERROR, tr("worker.recognition_failed")
        if self._shutting_down.is_set():
            return STATE_IDLE, ""
        if not text.strip():
            return STATE_ERROR, tr("worker.no_content")
        # A settings change during inference can enable or replace the verifier.
        if self._settings.get("speaker_verification", "enabled", default=False):
            if verified_by is None or verified_by is not self._speaker_verifier:
                return STATE_ERROR, tr("worker.verification_failed")
        try:
            if use_clipboard_restore:
                self._injector.inject_text(text)
            else:
                self._injector.inject_text_no_restore(text)
        except Exception:
            logger.exception("Text insertion failed")
            return STATE_ERROR, tr("worker.insertion_failed")
        return STATE_RESULT, text


class SpeakerLoader(QThread):
    def __init__(self, settings):
        super().__init__()
        self._settings = settings
        self.verifier = None

    def run(self):
        try:
            from core.speaker_verifier import SpeakerVerifier
            verifier = SpeakerVerifier(device=self._settings.asr_device())
            verifier.load_model()
            self.verifier = verifier
        except Exception:
            logger.exception("Could not load the speaker verifier")


class MoShengApp(QObject):
    """Main application: tray icon, overlay, worker thread, hotkey manager."""

    def __init__(self, asr_engine: ASRBase | None, settings: SettingsManager,
                 speaker_verifier=None):
        super().__init__()
        self._settings = settings
        self._verifier_loader = None
        self._microphone_error = ""
        self._reported_ready = False
        self._speaker_verifier = speaker_verifier

        # Migrate old single-hotkey config to dual-binding format
        self._migrate_hotkey_settings()
        self._migrate_sound_settings()

        # Sound player
        sound_style = self._settings.get("output", "sound_style", default="bell")
        self._sound_player = SoundPlayer(style=sound_style)

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
        self._worker._sound_player = self._sound_player
        self._worker.state_changed.connect(self._on_state_changed,
                                            Qt.ConnectionType.QueuedConnection)
        self._worker.hotword_context = self._build_hotword_context()
        self._worker.progressive = settings.get("hotkey", "progressive", default=False)
        self._worker.silence_duration = settings.get("hotkey", "silence_duration", default=0.8)

        # Load VAD for progressive mode
        self._vad = None
        if self._worker.progressive:
            self._load_vad()

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

        # Wire hotkey VK codes to the text injector (Windows needs this)
        if sys.platform == "win32":
            self._injector.hotkey_vks = self._hotkey.hotkey_vks

        # Application icon
        self._app_icon = self._load_app_icon()

        # System tray
        self._tray = QSystemTrayIcon()
        if self._app_icon:
            self._tray.setIcon(self._app_icon)
        self._refresh_readiness()

        menu = QMenu()
        settings_action = QAction(tr("tray.settings"), menu)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)
        menu.addSeparator()
        quit_action = QAction(tr("tray.quit"), menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._tray_menu = menu

        # macOS: Dock integration
        if sys.platform == "darwin":
            self._tray.activated.connect(self._on_tray_activated)
            QApplication.instance().applicationStateChanged.connect(
                self._on_app_state_changed
            )

        self._settings_window = None

        # Periodic hook reinstall to recover from silent removal by Windows
        self._hook_health_timer = QTimer()
        self._hook_health_timer.timeout.connect(self._reinstall_hook)
        self._hook_health_timer.start(60_000)

    def start(self) -> None:
        self._check_microphone()
        self._sync_speaker_verifier()
        self._refresh_readiness()
        self._hotkey.start()
        self._worker.start()
        self._tray.show()
        QApplication.instance().aboutToQuit.connect(self._shutdown)
        logger.info("MoSheng tray and hotkeys active")

    # ---- Hotkey callbacks ----

    def _on_hotkey_start(self) -> None:
        issue = self._worker.readiness_issue()
        if issue:
            self._worker.state_changed.emit(*issue)
            return
        self._worker.enqueue(CMD_START)

    # ---- Deferred attach for background-loaded engine ----

    def attach_asr(self, engine: ASRBase) -> None:
        """Wire in the ASR engine after the background loader finishes."""
        self._worker._asr = engine
        self._sync_speaker_verifier()
        self._refresh_readiness()

    def _refresh_readiness(self) -> None:
        issue = self._worker.readiness_issue()
        self._tray.setToolTip(issue[1] if issue else self._microphone_error or tr("tray.ready"))
        if not issue and not self._microphone_error and not self._reported_ready:
            self._reported_ready = True
            logger.info("[startup] model_ready")

    def _check_microphone(self) -> None:
        try:
            self._recorder.check_device()
            self._microphone_error = ""
        except Exception as exc:
            logger.warning("Selected microphone unavailable: %s", exc)
            self._microphone_error = tr("worker.recording_failed")

    # ---- State handling ----

    @Slot(str, str)
    def _on_state_changed(self, state: str, text: str) -> None:
        if state == STATE_LOADING:
            issue = self._worker.readiness_issue()
            if issue is None:
                self._refresh_readiness()
                return
            state, text = issue
        self._overlay.set_state(state, text)
        if state == STATE_RECORDING:
            self._microphone_error = ""
            self._tray.setToolTip(tr("tray.recording"))
        elif state == STATE_RECOGNIZING:
            self._tray.setToolTip(tr("tray.recognizing"))
        elif state in (STATE_LOADING, STATE_FILTERED, STATE_ERROR):
            if state == STATE_ERROR and text == tr("worker.recording_failed"):
                self._microphone_error = text
            self._tray.setToolTip(text)
        else:
            self._refresh_readiness()

    # ---- Icons ----

    def _load_app_icon(self) -> QIcon | None:
        exts = ("icns", "png") if sys.platform == "darwin" else ("ico", "png")
        for ext in exts:
            path = os.path.join(ASSETS_DIR, f"icon.{ext}")
            if os.path.isfile(path):
                icon = QIcon(path)
                if not icon.isNull():
                    return icon
        return None

    # ---- macOS Dock integration ----

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._open_settings()

    def _on_app_state_changed(self, state) -> None:
        from PySide6.QtCore import Qt as QtConst
        if state == QtConst.ApplicationState.ApplicationActive:
            if self._settings_window is None:
                self._open_settings()

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
        ptt = self._settings.get("hotkey", "push_to_talk", default={})
        toggle = self._settings.get("hotkey", "toggle", default={})
        self._hotkey.update_bindings(
            ptt_keys=ptt.get("keys", ["caps lock"]),
            ptt_enabled=ptt.get("enabled", True),
            ptt_long_press_ms=ptt.get("long_press_ms", 300),
            toggle_keys=toggle.get("keys", ["right ctrl"]),
            toggle_enabled=toggle.get("enabled", True),
        )
        if sys.platform == "win32":
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
        self._check_microphone()
        progressive = self._settings.get("hotkey", "progressive", default=False)
        self._worker.progressive = progressive
        self._worker.silence_duration = self._settings.get(
            "hotkey", "silence_duration", default=0.8
        )

        # Load/unload VAD on progressive toggle
        if progressive and self._vad is None:
            self._load_vad()
        elif not progressive and self._vad is not None:
            # An active capture keeps its own reference until it stops.
            self._vad = None
            self._worker._vad = None
            logger.info("VAD unloaded (progressive disabled)")
        self._worker.hotword_context = self._build_hotword_context()

        self._sound_player.style = self._settings.get("output", "sound_style", default="bell")

        self._sync_speaker_verifier()
        self._refresh_readiness()
        self._worker.text_processor.update(
            remove_fillers=self._settings.get("text_processing", "remove_fillers", default=True),
            smart_punctuation=self._settings.get("text_processing", "smart_punctuation", default=True),
        )
        logger.info("Settings applied")

    def _migrate_hotkey_settings(self) -> None:
        old_keys = self._settings.get("hotkey", "keys")
        if old_keys is None:
            return

        old_mode = self._settings.get("mode", default="push_to_talk")
        old_display = self._settings.get("hotkey", "display", default="")

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

        hotkey_data = self._settings.get("hotkey")
        if isinstance(hotkey_data, dict):
            hotkey_data.pop("keys", None)
            hotkey_data.pop("display", None)

        self._settings.save()
        logger.info("Migrated old hotkey config (mode=%s) to dual-binding format", old_mode)

    def _migrate_sound_settings(self) -> None:
        """Migrate old boolean sound_enabled to new sound_style string."""
        old = self._settings.get("output", "sound_enabled")
        if old is not None:
            style = "bell" if old else "off"
            self._settings.set("output", "sound_style", style)
            output_settings = self._settings.get("output")
            if isinstance(output_settings, dict):
                output_settings.pop("sound_enabled", None)
            self._settings.save()

    def _load_vad(self) -> None:
        from core.vad import SileroVAD
        vad = SileroVAD()
        vad.load_model()
        self._vad = vad
        self._worker._vad = vad

    def _sync_speaker_verifier(self) -> None:
        self._worker.verifier_error = ""
        if not self._settings.get("speaker_verification", "enabled", default=False):
            # An in-flight verification keeps its local reference until it finishes.
            self._worker.speaker_verifier = self._speaker_verifier = None
        elif self._speaker_verifier is not None:
            self._apply_enrollment()
        elif self._worker._asr is not None and self._verifier_loader is None:
            self._verifier_loader = SpeakerLoader(self._settings)
            self._verifier_loader.finished.connect(self._on_verifier_loaded)
            self._verifier_loader.start()

    @Slot()
    def _on_verifier_loaded(self) -> None:
        verifier = self._verifier_loader.verifier
        self._verifier_loader = None
        if self._settings.get("speaker_verification", "enabled", default=False):
            self._speaker_verifier = verifier
            if verifier is None:
                self._worker.verifier_error = tr("worker.verifier_load_failed")
            else:
                self._apply_enrollment()
        self._refresh_readiness()

    def _apply_enrollment(self) -> None:
        from config import SPEAKER_DIR
        verifier = self._speaker_verifier
        try:
            verifier.load_enrollment(SPEAKER_DIR)
            verifier.update_thresholds(
                self._settings.get("speaker_verification", "threshold", default=0.25),
                self._settings.get("speaker_verification", "high_threshold", default=0.40),
                self._settings.get("speaker_verification", "low_threshold", default=0.10),
            )
            self._worker.speaker_verifier = verifier
        except Exception:
            logger.exception("Could not read speaker enrollment")
            self._worker.speaker_verifier = None
            self._worker.verifier_error = tr("worker.enroll_first")

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

    # ---- Hook health ----

    def _reinstall_hook(self) -> None:
        self._hotkey.reinstall_hook()

    # ---- Shutdown ----

    def _quit(self) -> None:
        QApplication.instance().quit()

    @Slot()
    def _shutdown(self) -> None:
        logger.info("Shutting down...")
        self._hotkey.stop()
        self._worker.shutdown()
        self._worker.wait()
        if self._verifier_loader is not None:
            self._verifier_loader.wait()
        self._overlay.close()
        self._tray.hide()
