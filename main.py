"""MoSheng (墨声) - Local voice input tool powered by Qwen3-ASR."""

import atexit
import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# pythonw.exe sets stdout/stderr to None — redirect to devnull to prevent crashes
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from utils.logger import setup_logging
from config import APP_NAME, APP_VERSION
from settings_manager import SettingsManager

# ---- Platform-specific single instance & msgbox ----

if sys.platform == "win32":
    import ctypes
    from utils.autostart import AUTOSTART_ARG, refresh_autostart_command
    _ERROR_ALREADY_EXISTS = 183

    def _fatal_msgbox(msg: str, title: str = "MoSheng - Error") -> None:
        if AUTOSTART_ARG in sys.argv[1:]:
            logging.getLogger(__name__).error("%s: %s", title, msg)
            return
        ctypes.windll.user32.MessageBoxW(0, msg, title, 0x10)

    def _acquire_single_instance():
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "MoSheng_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            ctypes.windll.kernel32.CloseHandle(mutex)
            return None
        return mutex

elif sys.platform == "darwin":
    import fcntl
    import subprocess

    _LOCK_FILE = os.path.expanduser("~/.mosheng/.lock")

    def _fatal_msgbox(msg: str, title: str = "MoSheng - Error") -> None:
        try:
            escaped = msg.replace('\\', '\\\\').replace('"', '\\"')
            subprocess.run([
                "osascript", "-e",
                f'display dialog "{escaped}" with title "{title}" buttons {{"OK"}} default button "OK" with icon stop',
            ], timeout=30)
        except Exception:
            print(f"FATAL: {title}: {msg}", file=sys.stderr)

    def _acquire_single_instance():
        os.makedirs(os.path.dirname(_LOCK_FILE), exist_ok=True)
        lock_fp = open(_LOCK_FILE, "w")
        try:
            fcntl.flock(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock_fp
        except OSError:
            lock_fp.close()
            return None
else:
    def _fatal_msgbox(msg: str, title: str = "MoSheng - Error") -> None:
        print(f"FATAL: {title}: {msg}", file=sys.stderr)

    def _acquire_single_instance():
        return True


def check_environment() -> bool:
    """Check the inference runtime. Each recording opens the selected microphone."""
    logger = logging.getLogger(__name__)

    try:
        import torch
        if sys.platform == "darwin":
            if torch.backends.mps.is_available():
                logger.info("MPS (Apple Silicon GPU) is available")
            else:
                logger.warning("MPS is not available, will use CPU")
        elif sys.platform == "win32":
            if not torch.cuda.is_available():
                logger.warning("CUDA is not available, falling back to CPU.")
            else:
                gpu_name = torch.cuda.get_device_name(0)
                vram = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                logger.info("GPU: %s (%.1f GB)", gpu_name, vram)
    except Exception as e:
        logger.error("Failed to import torch: %s", e)
        from i18n import tr
        _fatal_msgbox(tr("error.pytorch_load_failed", error=e), tr("error.title"))
        return False

    return True


def load_asr_engine(settings: SettingsManager, snapshot, standby=None):
    logger = logging.getLogger(__name__)
    model_id = settings.get("asr", "model_id", default="Qwen/Qwen3-ASR-1.7B")
    device = settings.get("asr", "device", default="auto")
    if sys.platform == "win32" and device != "cpu":
        from core.windows_model_host import WindowsModelHost as Engine
    else:
        if standby is not None:
            standby.close()
        from core.asr_qwen import QwenASREngine as Engine
        device = settings.asr_device()
    dtype = settings.get("asr", "dtype", default="bfloat16")
    max_tokens = settings.get("asr", "max_new_tokens", default=256)

    engine = Engine(
        model_id=str(snapshot), device=device,
        dtype=dtype, max_new_tokens=max_tokens,
    )

    logger.info("Loading ASR model: %s (device=%s) ...", model_id, device)
    if standby is not None and sys.platform == "win32" and device != "cpu":
        engine.load_model(standby=standby)
    else:
        engine.load_model()
    logger.info("ASR model loaded.")
    return engine


def main():
    background = sys.platform == "win32" and AUTOSTART_ARG in sys.argv[1:]
    lock = _acquire_single_instance()
    if lock is None:
        if not background:
            _fatal_msgbox("MoSheng is already running.\n\nMoSheng 已在运行中。")
        return

    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("%s v%s starting", APP_NAME, APP_VERSION)

    from PySide6.QtCore import QThread, Signal
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from ui.styles import FLUENT_DARK_STYLESHEET
    from config import ASSETS_DIR

    if sys.platform == "win32":
        from utils.windows_taskbar import set_process_identity
        refresh_autostart_command()
        set_process_identity()
    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)
    qt_app.setStyleSheet(FLUENT_DARK_STYLESHEET)

    # Icon: prefer .icns on macOS, .ico on Windows
    icon_exts = ("icns", "png") if sys.platform == "darwin" else ("ico", "png")
    for ext in icon_exts:
        icon_path = os.path.join(ASSETS_DIR, f"icon.{ext}")
        if os.path.isfile(icon_path):
            qt_app.setWindowIcon(QIcon(icon_path))
            break

    settings = SettingsManager()
    from i18n import init_language, tr
    init_language(settings)

    paused = sys.platform == "win32" and settings.get("dictation_paused", default=False)
    splash = None
    if background:
        logger.info("[startup] background_autostart")
    elif not paused:
        from ui.splash_screen import SplashScreen
        splash = SplashScreen()
        splash.show()
        qt_app.processEvents()
        logger.info("[startup] splash_visible")

    from core.model_downloader import cached_snapshot, ModelDownloadThread
    model_id = settings.get("asr", "model_id", default="Qwen/Qwen3-ASR-1.7B")

    # ---- Bring up tray + hotkey IMMEDIATELY (no engine yet) ----
    from ui.app import MoShengApp
    standby = None
    if sys.platform == "win32":
        from core.windows_model_host import WindowsModelStandby
        standby = WindowsModelStandby()

    def prepare_resume():
        if standby is not None and settings.get("asr", "device", default="auto") != "cpu":
            standby.prepare()

    def resolve_snapshot(stage=None):
        selected = settings.get("asr", "model_id", default=model_id)
        local = cached_snapshot(selected)
        if local is not None:
            return local
        downloader = ModelDownloadThread(selected)
        if stage is not None:
            name = settings.get("asr", "model_name", default=selected)
            stage(tr("splash.downloading_model", name=name))
            downloader.progress.connect(lambda pct: stage(tr("splash.download_progress", percent=pct)))
        downloader.run()
        if downloader.snapshot is None:
            raise RuntimeError(tr("error.model_download_failed", error=downloader.failure))
        return downloader.snapshot

    def resume_engine():
        engine = load_asr_engine(settings, resolve_snapshot(), standby)
        try:
            engine.warmup()
        except Exception:
            engine.unload_model()
            raise
        return engine

    app = MoShengApp(asr_engine=None, settings=settings,
                    resume_engine=resume_engine if sys.platform == "win32" else None,
                    prepare_resume=prepare_resume)
    app.start()
    if standby is not None:
        qt_app.aboutToQuit.connect(standby.close)
    logger.info("[startup] tray_active")
    if paused:
        return qt_app.exec()

    if splash is not None:
        splash.set_status(tr("tray.loading"))
        splash.set_hint(tr("splash.loading_asr_hint"))
        qt_app.processEvents()

    # ---- Background worker: runtime check, ASR load and warmup ----

    class StartupWorker(QThread):
        stage = Signal(str)
        asr_ready = Signal(object)
        failed = Signal()

        def __init__(self, settings_):
            super().__init__()
            self._settings = settings_

        def run(self):
            try:
                self.stage.emit(tr("splash.checking"))
                # GPU discovery for the Windows host belongs in the child process.
                if sys.platform != "win32" and not check_environment():
                    self.failed.emit()
                    return

                snapshot = resolve_snapshot(self.stage.emit)
                self.stage.emit(tr("tray.loading"))
                engine = load_asr_engine(self._settings, snapshot)
                self.stage.emit(tr("splash.warming"))
                try:
                    engine.warmup()
                except Exception:
                    engine.unload_model()
                    raise
                self.asr_ready.emit(engine)
            except Exception as e:
                logging.getLogger(__name__).exception("Background startup failed")
                _fatal_msgbox(f"Background startup failed: {e}")
                self.failed.emit()

    def _on_asr_ready(engine):
        app.attach_asr(engine)
        atexit.register(engine.unload_model)
        if splash is not None:
            splash.finish()

    worker = StartupWorker(settings)
    if splash is not None:
        worker.stage.connect(splash.set_status)
    worker.asr_ready.connect(_on_asr_ready)
    worker.failed.connect(app._quit)
    qt_app.aboutToQuit.connect(worker.wait)
    worker.start()
    qt_app._startup_worker = worker  # keep ref

    logger.info("MoSheng tray+hotkey ready; model loading in background.")

    try:
        sys.exit(qt_app.exec())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception:
        logger.exception("Unhandled exception")
        _fatal_msgbox(tr("error.unhandled_exception"), tr("error.title"))
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _fatal_msgbox(f"Startup failed / 启动失败: {e}")
        sys.exit(1)
