"""Recorder, dictation lifecycle, and bilingual Qt layout regressions."""

import os
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStackedWidget

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
    @unittest.skipUnless(sys.platform == "win32", "Windows login startup")
    def test_both_startup_modes_attach_the_warmed_model_after_download(self):
        import main
        self.enterContext(patch.object(main, "_acquire_single_instance", return_value=True))
        self.enterContext(patch.object(main, "refresh_autostart_command"))
        self.enterContext(patch.object(main, "setup_logging"))
        self.enterContext(patch("utils.windows_taskbar.set_process_identity"))
        self.enterContext(patch("PySide6.QtWidgets.QApplication", return_value=app))
        self.enterContext(patch("core.model_downloader.cached_snapshot", return_value=None))
        self.enterContext(patch("core.model_downloader.ModelDownloadThread")).return_value.snapshot = "model"
        self.enterContext(patch.object(main.atexit, "register"))
        settings = self.enterContext(patch.object(main, "SettingsManager")).return_value
        settings.get.side_effect = lambda *keys, default=None: default
        splash = Mock()
        self.enterContext(patch.dict(sys.modules, {"ui.splash_screen": SimpleNamespace(SplashScreen=splash)}))
        desktop = self.enterContext(patch("ui.app.MoShengApp")).return_value
        desktop.attach_asr.side_effect = lambda engine: app.quit()
        engine = self.enterContext(patch.object(main, "load_asr_engine")).return_value
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(app.quit)
        for login in (True, False):
            with self.subTest(login=login), patch.object(sys, "argv", ["main.py"] + (["--autostart"] if login else [])):
                timeout.start(5000)
                with self.assertRaises(SystemExit):
                    main.main()
                timeout.stop()
                worker = app._startup_worker
                app.aboutToQuit.disconnect(worker.wait)
                del app._startup_worker
                worker.deleteLater()
                desktop.start.assert_called_once()
                engine.warmup.assert_called_once()
                desktop.attach_asr.assert_called_once_with(engine)
                if login:
                    splash.assert_not_called()
                else:
                    splash.return_value.show.assert_called_once()
                    splash.return_value.finish.assert_called_once()
                desktop.reset_mock()
                engine.reset_mock()

    def test_standby_close_skips_device_discovery_and_weights(self):
        from core.windows_model_host import _serve
        pipe = Mock()
        pipe.poll.return_value = True
        pipe.recv.return_value = ("close", ())
        self.enterContext(patch("utils.logger.setup_logging"))
        self.enterContext(patch.dict(sys.modules, {"qwen_asr": Mock()}))
        self.enterContext(patch("torch.cuda.is_initialized", return_value=False))
        available = self.enterContext(patch("torch.cuda.is_available"))
        engine = self.enterContext(patch("core.asr_qwen.QwenASREngine"))
        _serve(pipe, None)
        available.assert_not_called()
        engine.assert_not_called()
        pipe.close.assert_called_once()

    def test_early_resume_uses_current_config_and_a_crashed_standby_cold_starts(self):
        from core.windows_model_host import WindowsModelHost, WindowsModelStandby
        for crashed in (False, True):
            with self.subTest(crashed=crashed), patch("core.windows_model_host._spawn") as spawn:
                waiting, cold = (Mock(), Mock()), (Mock(), Mock())
                waiting[1].recv.side_effect = EOFError() if crashed else [(True, None)]
                cold[1].recv.return_value = (True, None)
                spawn.side_effect = [waiting, cold]
                standby = WindowsModelStandby()
                standby.prepare()
                standby.prepare()
                host = WindowsModelHost(device="cuda:1")
                host.load_model(standby)
                waiting[1].send.assert_any_call(("load", {"device": "cuda:1"}))
                self.assertEqual(spawn.call_count, 2 if crashed else 1)
                self.assertIsNone(standby.take())
                host.unload_model()

    def test_host_handles_dictation_and_shared_speaker_lifetimes(self):
        from core.windows_model_host import _serve
        pipe = Mock()
        pipe.recv.side_effect = [
            ("warmup", ()), ("speaker_load", ("old",)), ("speaker_load", ("new",)),
            ("speaker_release", ("old",)), ("embedding", ("audio", 16000)),
            ("speaker_release", ("new",)), ("transcribe", ("audio", 16000, "vocabulary")),
            ("close", ()),
        ]
        asr = self.enterContext(patch("core.asr_qwen.QwenASREngine")).return_value
        from unittest.mock import MagicMock
        speaker_class = MagicMock()
        speaker = speaker_class.return_value
        self.enterContext(patch.dict(sys.modules, {
            "core.speaker_verifier": SimpleNamespace(SpeakerVerifier=speaker_class),
        }))
        self.enterContext(patch("utils.logger.setup_logging"))
        _serve(pipe, {"device": "cpu"})
        asr.load_model.assert_called_once()
        asr.warmup.assert_called_once()
        asr.transcribe.assert_called_once_with("audio", 16000, "vocabulary")
        speaker.load_model.assert_called_once()
        speaker.extract_embedding.assert_called_once_with("audio", 16000)
        speaker.unload_model.assert_called_once()
        pipe.send.assert_called_with((True, asr.transcribe.return_value))
        pipe.close.assert_called_once()

    def test_tray_pause_drains_audio_and_manual_resume_retries(self):
        from settings_manager import SettingsManager
        from ui.app import MoShengApp
        from i18n import tr
        settings = SettingsManager()
        settings.set("speaker_verification", "enabled", False)
        settings.set("hotkey", "progressive", False)
        settings.set("dictation_paused", False)
        settings.save = Mock()
        hook = self.enterContext(patch("ui.app.DualHotkeyManager")).return_value
        self.enterContext(patch("ui.app.OverlayWindow"))
        if sys.platform == "win32":
            self.enterContext(patch("ui.input_mode_badge.InputModeBadge"))
        self.enterContext(patch("ui.app.QSystemTrayIcon"))
        self.enterContext(patch.object(AudioRecorder, "check_device"))
        opened, decoding, finish = threading.Event(), threading.Event(), threading.Event()
        stream = self.enterContext(patch("core.audio_recorder.sd.InputStream"))
        first, second = Mock(is_ready=True), Mock(is_ready=True)
        factory = Mock(side_effect=[RuntimeError("out of memory"), second])
        ctl = MoShengApp(first, settings, resume_engine=factory)
        ctl._worker._injector = Mock()
        ctl._worker._sound_player = None

        def start_stream():
            ctl._recorder._audio_callback(np.ones((16000, 1), dtype=np.float32), 16000, None, None)
            opened.set()

        def transcribe(*args, **kwargs):
            decoding.set()
            self.assertTrue(finish.wait(3))
            return "Finished."

        def until(phase):
            limit = time.monotonic() + 4
            while ctl._phase != phase and time.monotonic() < limit:
                app.processEvents()
                time.sleep(.01)
            self.assertEqual(ctl._phase, phase)

        stream.return_value.start.side_effect = start_stream
        first.transcribe.side_effect = transcribe
        ctl.start()
        try:
            ctl._on_hotkey_start()
            self.assertTrue(opened.wait(2))
            ctl._update_pause_action()
            self.assertEqual(ctl._pause_action.text(), tr("tray.pause_after"))
            ctl._pause_action.trigger()
            self.assertTrue(settings.get("dictation_paused"))
            ctl._worker.enqueue("stop")
            self.assertTrue(decoding.wait(2))
            first.unload_model.assert_not_called()
            finish.set()
            until("paused")
            first.unload_model.assert_called_once()
            ctl._worker._injector.inject_text.assert_called_once()
            ctl._on_hotkey_start()
            factory.assert_not_called()
            if ctl._mode_badge:
                ctl._mode_badge.set_enabled.assert_called_once_with(True)
            with self.assertLogs("ui.app", level="ERROR"):
                ctl._pause_action.trigger()
                until("retry")
            self.assertTrue(settings.get("dictation_paused"))
            ctl._pause_action.trigger()
            until("active")
            self.assertFalse(settings.get("dictation_paused"))
            self.assertIs(ctl._worker._asr, second)
            self.assertEqual(hook.start.call_count, 2)
        finally:
            finish.set()
            ctl._shutdown()
            app.aboutToQuit.disconnect(ctl._shutdown)

    def test_persisted_pause_starts_only_the_resident_services(self):
        from settings_manager import SettingsManager
        from ui.app import MoShengApp
        settings = SettingsManager()
        settings.set("dictation_paused", True)
        settings.set("hotkey", "progressive", True)
        settings.set("speaker_verification", "enabled", True)
        self.enterContext(patch("ui.app.OverlayWindow"))
        self.enterContext(patch("ui.app.QSystemTrayIcon"))
        hook = self.enterContext(patch("ui.app.DualHotkeyManager")).return_value
        self.enterContext(patch.object(MoShengApp, "_load_vad", lambda ctl: self.fail("VAD loaded while paused")))
        if sys.platform == "win32":
            self.enterContext(patch("ui.input_mode_badge.InputModeBadge"))
        factory = Mock()
        ctl = MoShengApp(None, settings, resume_engine=factory)
        ctl.start()
        try:
            ctl._on_hotkey_start()
            ctl._sync_speaker_verifier()
            hook.start.assert_not_called()
            factory.assert_not_called()
            self.assertIsNone(ctl._verifier_loader)
            self.assertEqual(ctl._phase, "paused")
            if ctl._mode_badge:
                ctl._mode_badge.set_enabled.assert_called_once_with(True)
        finally:
            ctl._shutdown()
            app.aboutToQuit.disconnect(ctl._shutdown)

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
    @unittest.skipUnless(sys.platform == "win32", "Windows tray activation")
    def test_tray_double_click_opens_and_restores_settings(self):
        from PySide6.QtWidgets import QSystemTrayIcon
        from settings_manager import SettingsManager
        from ui.app import MoShengApp
        from ui.settings_window import SettingsWindow

        self.enterContext(patch("ui.app.OverlayWindow"))
        self.enterContext(patch("ui.app.DualHotkeyManager"))
        self.enterContext(patch.object(SettingsWindow, "_get_input_devices", lambda self: [(None, "Default")]))
        self.enterContext(patch.object(SettingsWindow, "_get_cuda_devices", lambda self: ["auto", "cpu"]))
        coordinator = MoShengApp(None, SettingsManager())
        activate = coordinator._tray.activated.emit
        reason = QSystemTrayIcon.ActivationReason
        for click in (reason.Trigger, reason.Context, reason.MiddleClick):
            activate(click)
            self.assertIsNone(coordinator._settings_window)

        activate(reason.DoubleClick)
        window = coordinator._settings_window
        self.assertIsNotNone(window)
        self.assertTrue(window.isVisible())
        window._tabs.setCurrentIndex(1)
        window.showMinimized()
        activate(reason.DoubleClick)
        self.assertIs(coordinator._settings_window, window)
        self.assertFalse(window.isMinimized())
        self.assertEqual(window._tabs.currentIndex(), 1)
        window.close()

        coordinator._tray.contextMenu().actions()[0].trigger()
        reopened = coordinator._settings_window
        self.assertIsNot(reopened, window)
        self.assertTrue(reopened.isVisible())
        reopened.close()

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
                    pages = window.findChild(QStackedWidget)
                    scroll = pages.currentWidget()
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
                    window._tabs.setFocus()
                    for index in range(3):
                        app.processEvents()
                        self.assertEqual(pages.currentIndex(), index)
                        page = pages.currentWidget()
                        self.assertEqual(page.horizontalScrollBar().maximum(), 0)
                        for switch in page.findChildren(ToggleSwitch):
                            self.assertGreaterEqual(switch.width(), switch.sizeHint().width(), switch.text())
                        if index < 2:
                            QTest.keyClick(window._tabs, Qt.Key.Key_Right)
                    self.assertTrue(toggle.isChecked())
                finally:
                    window.close()

    def test_shortcut_button_capture_cancel_and_save_across_tabs(self):
        from i18n import get_language
        from settings_manager import SettingsManager
        from ui.settings_window import SettingsWindow
        settings = SettingsManager()
        settings.set("language", get_language())
        self.enterContext(patch.object(SettingsWindow, "_get_cuda_devices", lambda self: ["auto", "cpu"]))
        self.enterContext(patch.object(SettingsWindow, "_get_input_devices", lambda self: [(None, "Default")]))
        self.enterContext(patch("ui.settings_window.set_autostart"))
        save = self.enterContext(patch.object(settings, "save"))
        window = SettingsWindow(settings)
        window.show()
        try:
            btn = window._ptt_bind_btn
            original = btn.text()
            btn.click()
            QTest.keyClick(window, Qt.Key.Key_Escape)
            self.assertEqual(btn.text(), original)
            btn.click()
            QTest.keyClick(window, Qt.Key.Key_F8)
            self.assertEqual(btn.text(), "F8")
            btn.click()
            window._tabs.setCurrentIndex(2)
            self.assertIsNone(window._capture_target)
            self.assertEqual(btn.text(), "F8")
            if sys.platform == "win32":
                window._mode_badge_toggle.setChecked(False)
            window._on_save_click()
            save.assert_called_once()
            if sys.platform == "win32":
                self.assertFalse(settings.get("output", "input_mode_badge"))
            self.assertEqual(settings.get("hotkey", "push_to_talk")["keys"], ["f8"])
        finally:
            window.close()


class OverlayTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows IME")
    def test_input_mode_badge_transitions_and_disable(self):
        from ui.input_mode_badge import InputModeBadge
        from core.windows_input_mode import BadgeAnchor
        badge = InputModeBadge()
        screen = app.primaryScreen()
        anchor = BadgeAnchor(screen.geometry().topLeft().toTuple(), (40, 50), 20)
        state = [(1, "EN", None)]
        read = threading.Event()

        def sample():
            read.set()
            return state[0]

        self.enterContext(patch("ui.input_mode_badge.focused_mode", side_effect=sample))
        locate = self.enterContext(patch("ui.input_mode_badge.badge_anchor", return_value=anchor))
        try:
            badge.set_enabled(True)
            for focus, mode, visible in ((1, "EN", True), (1, "中", True),
                                         (2, "中", True), (2, None, False)):
                state[0] = (focus, mode, None)
                read.clear()
                self.assertTrue(read.wait(2))
                # Let the sampling thread run between Qt event-loop iterations.
                for _ in range(60):
                    app.processEvents()
                    if badge.isVisible() == visible and (not visible or badge.text() == mode):
                        break
                    time.sleep(0.02)
                self.assertEqual(badge.isVisible(), visible)
                if visible:
                    self.assertEqual(badge.text(), mode)
                    self.assertTrue(badge.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
            state[0] = (2, "EN", None)
            until = time.monotonic() + 2
            while not badge.isVisible() and time.monotonic() < until:
                app.processEvents()
                time.sleep(0.02)
            old_pos = badge.pos()
            locate.return_value = BadgeAnchor(screen.geometry().topLeft().toTuple(), (110, 120), 20)
            until = time.monotonic() + 2
            while badge.pos() == old_pos and time.monotonic() < until:
                app.processEvents()
                time.sleep(0.02)
            self.assertNotEqual(badge.pos(), old_pos)
            self.assertTrue(badge.isVisible())
            locate.return_value = None
            until = time.monotonic() + 2
            while badge.isVisible() and time.monotonic() < until:
                app.processEvents()
                time.sleep(0.02)
            self.assertFalse(badge.isVisible())
            offset = (int(screen.geometry().width() * screen.devicePixelRatio()) - 1,
                      int(screen.geometry().height() * screen.devicePixelRatio()) - 1)
            badge.display("EN", BadgeAnchor(screen.geometry().topLeft().toTuple(), offset, 20))
            self.assertTrue(screen.availableGeometry().contains(badge.geometry()))
            badge.set_enabled(False)
            self.assertFalse(badge.isVisible())
            self.assertIsNone(badge._watcher)
            self.assertFalse(badge._blink.isActive())
        finally:
            badge.set_enabled(False)
            badge.close()

    def test_localized_statuses_and_hidden_meter(self):
        from i18n import set_language, tr
        from ui.overlay_window import OverlayWindow
        overlay = OverlayWindow()
        try:
            self.assertTrue(overlay._ready)
            for lang in ("en", "zh"):
                set_language(lang)
                overlay.set_state("recording")
                self.assertTrue(overlay._frame_timer.isActive())
                self.assertEqual(overlay._root.property("statusMessage"), tr("overlay.recording"))
                overlay.set_state("error", tr("worker.recording_failed"))
                app.processEvents()
                self.assertFalse(overlay._frame_timer.isActive())
                self.assertGreaterEqual(overlay._view.height(), overlay._root.implicitHeight())
                self.assertEqual(overlay._root.property("statusMessage"), tr("worker.recording_failed"))
                overlay.set_state("result", "spoken text")
                self.assertEqual(overlay._root.property("statusMessage"), tr("overlay.inserted"))
                self.assertFalse(overlay._root.property("showMeter"))
                overlay.set_state("idle")
                self.assertFalse(overlay._frame_timer.isActive())
        finally:
            overlay.close()
