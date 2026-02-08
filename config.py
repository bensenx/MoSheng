"""Default configuration constants for MoSheng (墨声)."""

import os
import shutil

APP_NAME = "MoSheng"
APP_VERSION = "1.0.0"

# Paths
SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".mosheng")
_OLD_SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".voiceinput")

# One-time migration from old settings directory
if os.path.isdir(_OLD_SETTINGS_DIR) and not os.path.isdir(SETTINGS_DIR):
    shutil.copytree(_OLD_SETTINGS_DIR, SETTINGS_DIR)

SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
SPEAKER_DIR = os.path.join(SETTINGS_DIR, "speaker")
VOCABULARY_FILE = os.path.join(SETTINGS_DIR, "vocabulary.csv")
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# One-time migration: move word_list from settings.json to vocabulary.csv
if os.path.isfile(SETTINGS_FILE) and not os.path.isfile(VOCABULARY_FILE):
    try:
        import json
        with open(SETTINGS_FILE, encoding="utf-8") as _f:
            _data = json.load(_f)
        _words = _data.get("vocabulary", {}).get("word_list", [])
        if _words:
            os.makedirs(SETTINGS_DIR, exist_ok=True)
            with open(VOCABULARY_FILE, "w", encoding="utf-8") as _f:
                _f.write("# 每行一个词汇（专业术语、人名等），帮助语音识别更准确\n")
                for _w in _words:
                    _f.write(_w + "\n")
    except Exception:
        pass

# Default settings
DEFAULT_SETTINGS = {
    "language": None,
    "hotkey": {
        "keys": ["ctrl", "left windows"],
        "display": "Ctrl + Win",
        "progressive": False,
        "silence_threshold": 0.01,
        "silence_duration": 0.8,
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
    "vocabulary": {
        "enabled": True,
    },
    "speaker_verification": {
        "enabled": False,
        "threshold": 0.25,
        "high_threshold": 0.40,
        "low_threshold": 0.10,
    },
}
