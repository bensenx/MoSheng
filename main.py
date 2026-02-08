"""MoSheng (墨声) - Local voice input tool powered by Qwen3-ASR."""

import atexit
import ctypes
import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import setup_logging
from config import APP_NAME, APP_VERSION
from settings_manager import SettingsManager

# Windows API constants
_ERROR_ALREADY_EXISTS = 183


def _fatal_msgbox(msg: str, title: str = "MoSheng - Error") -> None:
    """Show a native Windows error dialog (works without console or Qt)."""
    ctypes.windll.user32.MessageBoxW(0, msg, title, 0x10)


def _acquire_single_instance() -> int:
    """Try to acquire a named mutex. Returns handle if acquired, 0 if already running."""
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "MoSheng_SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        ctypes.windll.kernel32.CloseHandle(mutex)
        return 0
    return mutex


def check_environment() -> bool:
    """Check GPU and audio device availability."""
    logger = logging.getLogger(__name__)

    # Check CUDA
    try:
        import torch
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

    # Check audio device
    try:
        import sounddevice as sd
        default_in = sd.query_devices(kind="input")
        logger.info("Audio input: %s", default_in["name"])
    except Exception as e:
        logger.error("No audio input device: %s", e)
        from i18n import tr
        _fatal_msgbox(tr("error.no_microphone", error=e), tr("error.title"))
        return False

    return True


def load_asr_engine(settings: SettingsManager):
    """Load ASR model."""
    logger = logging.getLogger(__name__)
    from core.asr_qwen import QwenASREngine

    model_id = settings.get("asr", "model_id", default="Qwen/Qwen3-ASR-1.7B")
    device = settings.get("asr", "device", default="cuda:0")
    dtype = settings.get("asr", "dtype", default="bfloat16")
    max_tokens = settings.get("asr", "max_new_tokens", default=256)

    engine = QwenASREngine(
        model_id=model_id, device=device,
        dtype=dtype, max_new_tokens=max_tokens,
    )

    logger.info("Loading ASR model: %s ...", model_id)
    engine.load_model()
    logger.info("ASR model loaded.")
    return engine


def load_speaker_verifier(settings: SettingsManager):
    """Load speaker verification model if enabled."""
    logger = logging.getLogger(__name__)
    from config import SPEAKER_DIR

    enabled = settings.get("speaker_verification", "enabled", default=False)
    if not enabled:
        logger.info("Speaker verification not enabled, skipping.")
        return None

    from core.speaker_verifier import SpeakerVerifier

    device = settings.get("asr", "device", default="cuda:0")
    verifier = SpeakerVerifier(device=device)

    threshold = settings.get("speaker_verification", "threshold", default=0.25)
    high = settings.get("speaker_verification", "high_threshold", default=0.40)
    low = settings.get("speaker_verification", "low_threshold", default=0.10)
    verifier.update_thresholds(threshold, high, low)

    verifier.load_model()
    verifier.load_enrollment(SPEAKER_DIR)
    logger.info("Speaker verification model loaded.")
    return verifier


def main():
    # Single instance check (before anything else)
    mutex = _acquire_single_instance()
    if not mutex:
        _fatal_msgbox("MoSheng is already running.\n\nMoSheng 已在运行中。")
        return

    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("%s v%s starting", APP_NAME, APP_VERSION)

    # Create QApplication early so we can show splash during model loading
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from ui.styles import FLUENT_DARK_STYLESHEET
    from config import ASSETS_DIR

    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)
    qt_app.setStyleSheet(FLUENT_DARK_STYLESHEET)

    for ext in ("ico", "png"):
        icon_path = os.path.join(ASSETS_DIR, f"icon.{ext}")
        if os.path.isfile(icon_path):
            qt_app.setWindowIcon(QIcon(icon_path))
            break

    # Initialize i18n before any UI text
    settings = SettingsManager()
    from i18n import init_language, tr
    init_language(settings)

    # Show splash screen
    from ui.splash_screen import SplashScreen
    splash = SplashScreen()
    splash.show()
    qt_app.processEvents()

    # Environment check
    splash.set_status("Checking environment...")
    qt_app.processEvents()
    if not check_environment():
        sys.exit(1)

    # Download ASR model if not cached
    from core.model_downloader import is_model_cached, ModelDownloadThread

    model_id = settings.get("asr", "model_id", default="Qwen/Qwen3-ASR-1.7B")
    if not is_model_cached(model_id):
        model_name = settings.get("asr", "model_name", default="Qwen3-ASR-1.7B")
        splash.set_status(tr("splash.downloading_model", name=model_name))
        qt_app.processEvents()

        download_thread = ModelDownloadThread(model_id)
        download_error = []

        def _on_download_progress(pct):
            splash.set_status(tr("splash.download_progress", percent=pct))

        def _on_download_error(msg):
            download_error.append(msg)

        download_thread.progress.connect(_on_download_progress)
        download_thread.error.connect(_on_download_error)
        download_thread.start()

        while download_thread.isRunning():
            qt_app.processEvents()
            download_thread.wait(100)

        if download_error:
            _fatal_msgbox(
                tr("error.model_download_failed", error=download_error[0]),
                tr("error.title"),
            )
            sys.exit(1)

    # Load ASR model (main thread blocks, but splash is visible)
    splash.set_status("Loading ASR model...")
    qt_app.processEvents()
    asr_engine = load_asr_engine(settings)
    atexit.register(asr_engine.unload_model)

    # Load speaker verification model (if enabled)
    splash.set_status("Loading speaker verification...")
    qt_app.processEvents()
    speaker_verifier = load_speaker_verifier(settings)
    if speaker_verifier:
        atexit.register(speaker_verifier.unload_model)

    # Start the app, close splash
    from ui.app import MoShengApp
    app = MoShengApp(asr_engine=asr_engine, settings=settings,
                     speaker_verifier=speaker_verifier)
    app.start()
    splash.finish()

    logger.info("MoSheng ready. Hotkey: %s",
                settings.get("hotkey", "display", default="Ctrl + Win"))

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
