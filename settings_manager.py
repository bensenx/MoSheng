"""User settings persistence via JSON file."""

import json
import os
import copy
import logging

from config import SETTINGS_DIR, SETTINGS_FILE, DEFAULT_SETTINGS

logger = logging.getLogger(__name__)


class SettingsManager:
    def __init__(self):
        self._settings = copy.deepcopy(DEFAULT_SETTINGS)
        self._ensure_dir()
        self.load()

    def _ensure_dir(self):
        os.makedirs(SETTINGS_DIR, exist_ok=True)

    def load(self):
        if not os.path.exists(SETTINGS_FILE):
            self.save()
            return
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self._merge(self._settings, saved)
            logger.info("Settings loaded from %s", SETTINGS_FILE)
        except Exception:
            logger.exception("Failed to load settings, using defaults")
            self._settings = copy.deepcopy(DEFAULT_SETTINGS)

    def save(self):
        self._ensure_dir()
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2, ensure_ascii=False)
            logger.info("Settings saved to %s", SETTINGS_FILE)
        except Exception:
            logger.exception("Failed to save settings")

    def _merge(self, base: dict, override: dict):
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge(base[key], value)
            else:
                base[key] = value

    def get(self, *keys, default=None):
        result = self._settings
        for key in keys:
            if isinstance(result, dict) and key in result:
                result = result[key]
            else:
                return default
        return result

    def set(self, *keys_and_value):
        if len(keys_and_value) < 2:
            raise ValueError("Need at least one key and a value")
        keys = keys_and_value[:-1]
        value = keys_and_value[-1]
        target = self._settings
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value

    @property
    def all(self) -> dict:
        return copy.deepcopy(self._settings)
