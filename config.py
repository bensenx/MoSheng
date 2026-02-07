"""Default configuration constants for VoiceInput."""

import os

APP_NAME = "VoiceInput"
APP_VERSION = "1.0.0"

# Paths
SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".voiceinput")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# Default settings
DEFAULT_SETTINGS = {
    "hotkey": {
        "keys": ["ctrl", "left windows"],
        "display": "Ctrl + Win",
    },
    "mode": "push_to_talk",
    "asr": {
        "model_name": "Qwen3-ASR-1.7B",
        "model_id": "Qwen/Qwen3-ASR-1.7B",
        "device": "cuda:0",
        "dtype": "bfloat16",
        "max_new_tokens": 256,
    },
    "audio": {
        "sample_rate": 16000,
        "channels": 1,
        "min_duration": 0.3,
        "input_device": None,
    },
    "output": {
        "sound_enabled": True,
        "overlay_enabled": True,
        "restore_clipboard": True,
    },
}
