"""Global hotkey manager with push-to-talk support."""

import logging
import threading
from typing import Callable

import keyboard

logger = logging.getLogger(__name__)


class HotkeyManager:
    MODE_PUSH_TO_TALK = "push_to_talk"
    MODE_TOGGLE = "toggle"

    def __init__(self, hotkey_keys: list[str],
                 on_start: Callable | None = None,
                 on_stop: Callable | None = None,
                 mode: str = "push_to_talk"):
        self._hotkey_keys = set(k.lower() for k in hotkey_keys)
        self._on_start = on_start
        self._on_stop = on_stop
        self._mode = mode
        self._keys_pressed: set[str] = set()
        self._is_active = False
        self._toggle_fired = False  # debounce for toggle mode
        self._lock = threading.Lock()
        self._hook = None

    def start(self) -> None:
        self._hook = keyboard.hook(self._on_key_event, suppress=False)
        logger.info("Hotkey manager started, keys=%s", self._hotkey_keys)

    def stop(self) -> None:
        if self._hook is not None:
            keyboard.unhook(self._hook)
            self._hook = None
        with self._lock:
            self._keys_pressed.clear()
            self._is_active = False
        logger.info("Hotkey manager stopped")

    def update_hotkey(self, hotkey_keys: list[str]) -> None:
        with self._lock:
            self._hotkey_keys = set(k.lower() for k in hotkey_keys)
            self._keys_pressed.clear()
            self._is_active = False
        logger.info("Hotkey updated to: %s", self._hotkey_keys)

    def update_mode(self, mode: str) -> None:
        with self._lock:
            self._mode = mode
            self._keys_pressed.clear()
            self._is_active = False
        logger.info("Hotkey mode updated to: %s", mode)

    def _on_key_event(self, event: keyboard.KeyboardEvent) -> None:
        name = event.name.lower() if event.name else ""
        if not name:
            return

        with self._lock:
            if self._mode == self.MODE_TOGGLE:
                self._handle_toggle(event, name)
            else:
                self._handle_push_to_talk(event, name)

    def _handle_push_to_talk(self, event: keyboard.KeyboardEvent, name: str) -> None:
        """Push-to-talk: hold to record, release to stop."""
        if event.event_type == keyboard.KEY_DOWN:
            self._keys_pressed.add(name)
            if (not self._is_active
                    and self._hotkey_keys
                    and self._hotkey_keys.issubset(self._keys_pressed)):
                self._is_active = True
                if self._on_start:
                    threading.Thread(
                        target=self._on_start, daemon=True
                    ).start()

        elif event.event_type == keyboard.KEY_UP:
            if self._is_active and name in self._hotkey_keys:
                self._is_active = False
                if self._on_stop:
                    threading.Thread(
                        target=self._on_stop, daemon=True
                    ).start()
            self._keys_pressed.discard(name)

    def _handle_toggle(self, event: keyboard.KeyboardEvent, name: str) -> None:
        """Toggle: press once to start, press again to stop.

        Uses _toggle_fired to ignore key-repeat (Windows sends repeated
        KEY_DOWN while a key is held).  The flag resets when any hotkey
        key is released.
        """
        if event.event_type == keyboard.KEY_DOWN:
            self._keys_pressed.add(name)
            if (not self._toggle_fired
                    and self._hotkey_keys
                    and self._hotkey_keys.issubset(self._keys_pressed)):
                self._toggle_fired = True
                if not self._is_active:
                    self._is_active = True
                    if self._on_start:
                        threading.Thread(
                            target=self._on_start, daemon=True
                        ).start()
                else:
                    self._is_active = False
                    if self._on_stop:
                        threading.Thread(
                            target=self._on_stop, daemon=True
                        ).start()

        elif event.event_type == keyboard.KEY_UP:
            if name in self._hotkey_keys:
                self._toggle_fired = False
            self._keys_pressed.discard(name)

    @property
    def is_active(self) -> bool:
        return self._is_active
