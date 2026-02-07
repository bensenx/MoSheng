"""MoSheng (墨声) - Local voice input tool powered by Qwen3-ASR."""

import atexit
import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import setup_logging
from config import APP_NAME, APP_VERSION
from settings_manager import SettingsManager


def check_environment() -> bool:
    """Check GPU and audio device availability."""
    logger = logging.getLogger(__name__)

    # Check CUDA
    try:
        import torch
        if not torch.cuda.is_available():
            logger.error("CUDA is not available. GPU required for ASR inference.")
            print("错误: 未检测到 CUDA，请确保已安装 NVIDIA GPU 驱动和 CUDA。")
            return False
        gpu_name = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        logger.info("GPU: %s (%.1f GB)", gpu_name, vram)
    except Exception as e:
        logger.error("Failed to check CUDA: %s", e)
        print(f"错误: CUDA 检测失败 - {e}")
        return False

    # Check audio device
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        default_in = sd.query_devices(kind="input")
        logger.info("Audio input: %s", default_in["name"])
    except Exception as e:
        logger.error("No audio input device: %s", e)
        print(f"错误: 未检测到麦克风 - {e}")
        return False

    return True


def load_asr_engine(settings: SettingsManager):
    """Load ASR model with progress display."""
    from core.asr_qwen import QwenASREngine

    model_id = settings.get("asr", "model_id", default="Qwen/Qwen3-ASR-1.7B")
    device = settings.get("asr", "device", default="cuda:0")
    dtype = settings.get("asr", "dtype", default="bfloat16")
    max_tokens = settings.get("asr", "max_new_tokens", default=256)

    engine = QwenASREngine(
        model_id=model_id, device=device,
        dtype=dtype, max_new_tokens=max_tokens,
    )

    print(f"正在加载 ASR 模型 ({model_id})，首次运行需下载模型权重...")
    engine.load_model()
    print("模型加载完成！")
    return engine


def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("%s v%s starting", APP_NAME, APP_VERSION)

    if not check_environment():
        sys.exit(1)

    settings = SettingsManager()
    asr_engine = load_asr_engine(settings)
    atexit.register(asr_engine.unload_model)

    import os
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from ui.styles import FLUENT_DARK_STYLESHEET
    from ui.app import MoShengApp
    from config import ASSETS_DIR

    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)
    qt_app.setStyleSheet(FLUENT_DARK_STYLESHEET)

    # Set application icon (window title bars, taskbar)
    for ext in ("ico", "png"):
        icon_path = os.path.join(ASSETS_DIR, f"icon.{ext}")
        if os.path.isfile(icon_path):
            qt_app.setWindowIcon(QIcon(icon_path))
            break

    app = MoShengApp(asr_engine=asr_engine, settings=settings)
    app.start()

    hotkey_display = settings.get("hotkey", "display", default="Ctrl + Win")
    print(f"\nMoSheng 已启动！按住 [{hotkey_display}] 开始录音，松开自动识别。")
    print("右键系统托盘图标可打开设置或退出。\n")

    try:
        sys.exit(qt_app.exec())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception:
        logger.exception("Unhandled exception")
        sys.exit(1)


if __name__ == "__main__":
    main()
