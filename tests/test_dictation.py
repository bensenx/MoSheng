"""Recorder, dictation lifecycle, and bilingual Qt layout regressions."""

import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from core.audio_recorder import AudioRecorder


def setUpModule():
    # config and SettingsManager create files on first import/use.
    profile = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(profile.cleanup)
    env = patch.dict(os.environ, HOME=profile.name, USERPROFILE=profile.name,
                     QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")
    env.start()
    unittest.addModuleCleanup(env.stop)
    global app
    app = QApplication.instance() or QApplication([])
    from ui.styles import FLUENT_DARK_STYLESHEET
    app.setStyleSheet(FLUENT_DARK_STYLESHEET)


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.rec = AudioRecorder()
        self.open_stream = self.enterContext(patch("core.audio_recorder.sd.InputStream"))

    def feed(self, samples):
        self.rec._audio_callback(samples[:, None], len(samples), None, None)

    def test_incremental_reads_and_full_audio_across_drains(self):
        data = np.arange(5500, dtype=np.float32)
        self.open_stream.return_value.start.side_effect = lambda: self.feed(data[:101])
        self.rec.start_recording()
        self.feed(data[101:430])
        np.testing.assert_array_equal(self.rec.get_new_samples(), data[:430])
        self.assertIsNone(self.rec.get_new_samples())
        self.feed(data[430:4700])
        np.testing.assert_array_equal(self.rec.get_new_samples(), data[430:4700])
        np.testing.assert_array_equal(self.rec.get_recent_samples(1024), data[3676:4700])
        np.testing.assert_array_equal(self.rec.drain_buffer(), data[:4700])
        self.assertIsNone(self.rec.get_new_samples())
        self.feed(data[4700:])
        np.testing.assert_array_equal(self.rec.stop_recording(), data[4700:])
        self.rec.start_recording()
        np.testing.assert_array_equal(self.rec.get_new_samples(), data[:101])
        self.rec.stop_recording()

    def test_open_and_start_failure_allow_retry(self):
        self.open_stream.side_effect = OSError("no device")
        with self.assertRaises(OSError):
            self.rec.start_recording()
        self.assertFalse(self.rec.is_recording)
        self.open_stream.side_effect = None
        self.open_stream.return_value.start.side_effect = OSError("device disconnected")
        with self.assertRaises(OSError):
            self.rec.start_recording()
        self.open_stream.return_value.close.assert_called_once()
        self.assertFalse(self.rec.is_recording)
        self.open_stream.return_value.start.side_effect = None
        self.rec.start_recording()
        self.assertTrue(self.rec.is_recording)
        self.rec.stop_recording()

    def test_failing_stop_still_closes_the_stream(self):
        self.rec.start_recording()
        self.open_stream.return_value.stop.side_effect = OSError("disconnected")
        with self.assertRaises(OSError):
            self.rec.stop_recording()
        self.open_stream.return_value.close.assert_called_once()
        self.assertFalse(self.rec.is_recording)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        from settings_manager import SettingsManager
        from ui.app import WorkerThread
        self.settings = SettingsManager()
        self.rec = AudioRecorder()
        self.engine = Mock(is_ready=True)
        self.injector = Mock()
        self.worker = WorkerThread(self.rec, self.engine, self.injector, self.settings)
        self.events = []
        self.worker.state_changed.connect(lambda state, msg: self.events.append((state, msg)),
                                          Qt.ConnectionType.DirectConnection)
        self.audio = np.ones(16000, dtype=np.float32)
        self.open_stream = self.enterContext(patch("core.audio_recorder.sd.InputStream"))
        self.open_stream.return_value.start.side_effect = lambda: self.rec._audio_callback(
            self.audio[:, None], len(self.audio), None, None)

    def session(self, *commands):
        for command in (*commands, "quit"):
            self.worker.enqueue(command)
        self.worker.run()

    def test_loading_press_and_release_do_not_record(self):
        self.engine.is_ready = False
        self.session("start", "stop")
        self.assertEqual([s for s, _ in self.events], ["loading"])
        self.open_stream.assert_not_called()

    def test_back_to_back_capture_during_inference(self):
        self._check_overlapping_recordings(progressive=False)

    def test_progressive_tail_and_next_recording_during_pause_inference(self):
        self._check_overlapping_recordings(progressive=True)

    def _check_overlapping_recordings(self, progressive):
        self.worker.progressive = progressive
        self.worker.silence_duration = 0
        self.worker._MIN_SPEECH_BEFORE_FLUSH = 0
        self.worker._vad = Mock(chunk_size=512)
        self.worker._vad.is_speech.return_value = True
        opened = [threading.Event(), threading.Event()]
        started_decode, resume = threading.Event(), threading.Event()
        levels = []

        def feed(level):
            block = np.full((16000, 1), level, dtype=np.float32)
            self.rec._audio_callback(block, len(block), None, None)

        def start_stream():
            i = int(opened[0].is_set())
            feed(3 if i else 1)
            opened[i].set()

        def transcribe(audio, *args, **kwargs):
            level = round(float(audio.mean()))
            levels.append(level)
            if len(levels) == 1:
                started_decode.set()
                self.assertTrue(resume.wait(5))
            return f"Segment {level}"

        self.open_stream.return_value.start.side_effect = start_stream
        self.engine.transcribe.side_effect = transcribe
        self.worker.start()
        try:
            self.worker.enqueue("start")
            self.assertTrue(opened[0].wait(2))
            if not progressive:
                self.worker.enqueue("stop")
            self.assertTrue(started_decode.wait(2))
            if progressive:
                feed(2)
                self.worker.enqueue("stop")
            self.worker.enqueue("start")
            self.assertTrue(opened[1].wait(2), "second microphone stream waited for ASR")
            self.worker.enqueue("stop")
        finally:
            resume.set()
            self.worker.enqueue("quit")
            self.assertTrue(self.worker.wait(5000))
        expected = [1, 2, 3] if progressive else [1, 3]
        self.assertEqual(levels, expected)
        paste = self.injector.inject_text_no_restore if progressive else self.injector.inject_text
        self.assertEqual([call.args[0] for call in paste.call_args_list],
                         [f"Segment {level}" for level in expected])

    def test_worker_recovers_after_microphone_failure(self):
        self.open_stream.side_effect = [OSError("disconnected"), self.open_stream.return_value]
        self.engine.transcribe.return_value = "Try again."
        with self.assertLogs("ui.app", level="ERROR"):
            self.session("start", "stop", "start", "stop")
        self.assertEqual([s for s, _ in self.events], ["error", "recording", "recognizing", "result"])
        self.injector.inject_text.assert_called_once_with("Try again.")

    def test_verification_waits_for_enrollment_and_blocks_errors(self):
        self.settings.set("speaker_verification", "enabled", True)
        self.session("start", "stop")
        self.assertEqual(self.events[-1][0], "loading")
        verifier = Mock(is_ready=True, is_enrolled=False)
        self.worker.speaker_verifier = verifier
        self.session("start", "stop")
        self.assertEqual(self.events[-1][0], "error")
        self.open_stream.assert_not_called()
        verifier.is_enrolled = True
        verifier.verify.side_effect = OSError("backend unavailable")
        with self.assertLogs("ui.app", level="ERROR"):
            self.session("start", "stop")
        from i18n import tr
        self.assertEqual(self.events[-1], ("error", tr("worker.verification_failed")))
        verifier.verify.side_effect = None
        verifier.verify.return_value = SimpleNamespace(is_user=False, path="fast_reject", score=0.)
        self.session("start", "stop")
        self.assertEqual(self.events[-1][0], "filtered")
        self.engine.transcribe.assert_not_called()
        self.injector.inject_text.assert_not_called()
        verifier.verify.return_value = SimpleNamespace(is_user=True, audio=self.audio)
        self.engine.transcribe.return_value = "Verified speech."
        self.session("start", "stop")
        self.injector.inject_text.assert_called_once_with("Verified speech.")

    def test_queued_recording_keeps_its_speaker_filter(self):
        self.settings.set("speaker_verification", "enabled", True)
        verifier = Mock(is_ready=True, is_enrolled=True)
        verifier.verify.return_value = SimpleNamespace(is_user=False, path="reject", score=0.)
        self.worker.speaker_verifier = verifier

        def disable():
            self.settings.set("speaker_verification", "enabled", False)
            self.worker.speaker_verifier = None

        self.open_stream.return_value.stop.side_effect = disable
        self.session("start", "stop")
        self.assertEqual(self.events[-1][0], "filtered")
        self.engine.transcribe.assert_not_called()
        self.injector.inject_text.assert_not_called()

    def test_enabling_verification_during_inference_blocks_insertion(self):
        def enable_verification(*args, **kwargs):
            self.settings.set("speaker_verification", "enabled", True)
            return "Unverified speech."
        self.engine.transcribe.side_effect = enable_verification
        self.session("start", "stop")
        self.assertEqual(self.events[-1][0], "error")
        self.injector.inject_text.assert_not_called()

    def test_recognition_error_survives_normal_and_progressive_stop(self):
        from i18n import tr
        self.engine.transcribe.side_effect = RuntimeError("inference failed")
        for progressive in (False, True):
            with self.subTest(progressive=progressive), self.assertLogs("ui.app", level="ERROR"):
                self.worker.progressive = progressive
                self.events.clear()
                self.session("start", "stop")
                self.assertEqual([s for s, _ in self.events], ["recording", "recognizing", "error"])
                self.assertEqual(self.events[-1][1], tr("worker.recognition_failed"))
        self.injector.restore_saved_clipboard.assert_called_once()

    def test_short_audio_and_empty_transcription_are_distinct(self):
        from i18n import tr
        self.engine.transcribe.return_value = ""
        self.assertEqual(self.worker._flush_and_inject(self.audio[:10]), ("error", tr("worker.too_short")))
        self.assertEqual(self.worker._flush_and_inject(self.audio), ("error", tr("worker.no_content")))

    def test_clipboard_failure_never_pastes_or_reports_success(self):
        from core.text_injector import TextInjector
        from i18n import tr
        self.worker._injector = TextInjector(restore_clipboard=False)
        self.engine.transcribe.return_value = "Clipboard busy."
        self.enterContext(patch.object(self.worker._injector, "_set_clipboard", return_value=False))
        paste = self.enterContext(patch("core.text_injector._send_paste"))
        for progressive in (False, True):
            self.worker.progressive = progressive
            self.settings.set("output", "restore_clipboard", False)
            with self.assertLogs("ui.app", level="ERROR"):
                self.session("start", "stop")
            self.assertEqual(self.events[-1], ("error", tr("worker.insertion_failed")))
        paste.assert_not_called()


class ReadinessTests(unittest.TestCase):
    def test_application_quit_stops_the_worker_while_loading(self):
        from settings_manager import SettingsManager
        from ui.app import MoShengApp
        self.enterContext(patch("ui.app.OverlayWindow"))
        self.enterContext(patch("ui.app.DualHotkeyManager"))
        self.enterContext(patch("ui.app.QSystemTrayIcon"))
        self.enterContext(patch.object(AudioRecorder, "check_device"))
        coordinator = MoShengApp(None, SettingsManager())
        coordinator.start()
        self.assertTrue(coordinator._worker.isRunning())
        QTimer.singleShot(0, app.quit)
        app.exec()
        self.assertFalse(coordinator._worker.isRunning())
        coordinator._hotkey.stop.assert_called_once()

    def test_cancelling_and_retrying_verifier_loading(self):
        from i18n import tr
        from settings_manager import SettingsManager
        from ui.app import MoShengApp
        settings = SettingsManager()
        settings.set("asr", "device", "cpu")
        settings.set("speaker_verification", "enabled", True)
        verifier = Mock(is_ready=True, is_enrolled=True)
        entered, release = threading.Event(), threading.Event()

        def load():
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test loader timed out")

        verifier.load_model.side_effect = load
        self.enterContext(patch.dict("sys.modules", {
            "core.speaker_verifier": SimpleNamespace(SpeakerVerifier=lambda **kw: verifier),
        }))
        self.enterContext(patch("ui.app.OverlayWindow"))
        self.enterContext(patch("ui.app.DualHotkeyManager"))
        self.enterContext(patch("ui.app.QSystemTrayIcon"))
        coordinator = MoShengApp(None, settings)
        self.assertEqual(coordinator._tray.setToolTip.call_args.args, (tr("tray.loading"),))
        coordinator.attach_asr(Mock(is_ready=True))
        loader = coordinator._verifier_loader
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(coordinator._worker.readiness_issue()[0], "loading")
            settings.set("speaker_verification", "enabled", False)
            coordinator._sync_speaker_verifier()
        finally:
            release.set()
            self.assertTrue(loader.wait(5000))
        app.processEvents()
        self.assertIsNone(coordinator._worker.speaker_verifier)
        settings.set("speaker_verification", "enabled", True)
        verifier.load_model.side_effect = RuntimeError("offline")
        with self.assertLogs("ui.app", level="ERROR"):
            coordinator._sync_speaker_verifier()
            self.assertTrue(coordinator._verifier_loader.wait(5000))
            app.processEvents()
        self.assertEqual(coordinator._worker.readiness_issue(), ("error", tr("worker.verifier_load_failed")))
        verifier.load_model.side_effect = None
        coordinator._sync_speaker_verifier()
        self.assertTrue(coordinator._verifier_loader.wait(5000))
        app.processEvents()
        self.assertIsNone(coordinator._worker.readiness_issue())
        self.assertEqual(coordinator._tray.setToolTip.call_args.args, (tr("tray.ready"),))

    def test_warmup_leaves_dictation_generation_limit_intact(self):
        from core.asr_qwen import QwenASREngine
        observed_limits = []

        class Model:
            max_new_tokens = 128

            def transcribe(self, **kwargs):
                observed_limits.append(self.max_new_tokens)

        engine = QwenASREngine(device="cpu", max_new_tokens=128)
        engine._model = Model()
        engine.warmup()
        self.assertEqual(observed_limits, [2])
        self.assertEqual(engine._model.max_new_tokens, 128)


class SettingsTests(unittest.TestCase):
    def test_layout_and_keyboard_at_default_width(self):
        from i18n import set_language
        from settings_manager import SettingsManager
        from ui.settings_window import SettingsWindow
        from ui.styles import ToggleSwitch

        class OfflineSettingsWindow(SettingsWindow):
            def _get_input_devices(self):
                return [(None, "Default")]

            def _get_cuda_devices(self):
                return ["auto", "cpu"]

        for lang in ("en", "zh"):
            with self.subTest(lang=lang):
                set_language(lang)
                window = OfflineSettingsWindow(SettingsManager())
                window.show()
                try:
                    app.processEvents()
                    scroll = window.findChild(QScrollArea)
                    self.assertEqual(window.width(), 560)
                    toggle = window._progressive_toggle
                    toggle.setChecked(False)
                    scroll.ensureWidgetVisible(toggle)
                    toggle.setFocus()
                    QTest.keyClick(toggle, Qt.Key.Key_Space)
                    app.processEvents()
                    self.assertTrue(toggle.isChecked())
                    self.assertTrue(window._progressive_opts.isVisible())
                    self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                    for switch in window.findChildren(ToggleSwitch):
                        self.assertGreaterEqual(switch.width(), switch.sizeHint().width(), switch.text())
                finally:
                    window.close()
