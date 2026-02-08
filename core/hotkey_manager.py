"""Global hotkey manager with hook-level key suppression.

Uses a custom WH_KEYBOARD_LL hook (via ctypes) that suppresses physical
hotkey key events during recording.  Injected events (from SendInput,
e.g. our Ctrl+V paste) are always passed through thanks to the
LLKHF_INJECTED flag.
"""

import logging
import threading
from collections.abc import Callable

from core.key_suppression_hook import KeySuppressionHook

logger = logging.getLogger(__name__)

# Build a name → VK code mapping from the keyboard library's table.
# We only import the data dict, not the hook machinery.
_NAME_TO_VKS: dict[str, set[int]] = {}


def _build_name_to_vks() -> None:
    """Populate _NAME_TO_VKS from keyboard._winkeyboard.official_virtual_keys."""
    if _NAME_TO_VKS:
        return
    try:
        from keyboard._winkeyboard import official_virtual_keys
    except ImportError:
        logger.warning("keyboard library not available for VK mapping")
        return

    for vk, (name, _is_keypad) in official_virtual_keys.items():
        key = name.lower()
        _NAME_TO_VKS.setdefault(key, set()).add(vk)

    # "ctrl" should also match left ctrl (0xA2) and right ctrl (0xA3).
    # "shift" should also match left shift (0xA0) and right shift (0xA1).
    # "alt" should also match left alt (0xA4) and right alt (0xA5).
    _SIDED = {
        "ctrl": ["left ctrl", "right ctrl"],
        "shift": ["left shift", "right shift"],
        "alt": ["left alt", "right alt"],
    }
    for generic, sided_names in _SIDED.items():
        if generic in _NAME_TO_VKS:
            for sided in sided_names:
                if sided in _NAME_TO_VKS:
                    _NAME_TO_VKS[generic] |= _NAME_TO_VKS[sided]


def _key_name_to_vks(name: str) -> set[int]:
    """Convert a key name (e.g. 'ctrl', 'left windows') to VK codes."""
    _build_name_to_vks()
    result = _NAME_TO_VKS.get(name.lower(), set())
    if not result:
        logger.warning("Unknown key name: %r", name)
    return set(result)


class HotkeyManager:
    MODE_PUSH_TO_TALK = "push_to_talk"
    MODE_TOGGLE = "toggle"

    def __init__(self, hotkey_keys: list[str],
                 on_start: Callable | None = None,
                 on_stop: Callable | None = None,
                 mode: str = "push_to_talk"):
        self._on_start = on_start
        self._on_stop = on_stop
        self._mode = mode
        self._is_active = False
        self._toggle_fired = False
        self._lock = threading.Lock()
        self._hook: KeySuppressionHook | None = None

        # Per-key-name VK groups: e.g. "ctrl" → {0x11, 0xA2, 0xA3}
        # Matching requires at least one VK from EACH group to be pressed.
        self._hotkey_vk_groups: list[frozenset[int]] = []
        # Flat union of all hotkey VKs (for "is this a hotkey VK" checks)
        self._hotkey_vks: set[int] = set()
        # Currently physically pressed VK codes
        self._vks_pressed: set[int] = set()

        self._set_hotkey_keys(hotkey_keys)

    def _set_hotkey_keys(self, hotkey_keys: list[str]) -> None:
        groups: list[frozenset[int]] = []
        all_vks: set[int] = set()
        for name in hotkey_keys:
            vks = _key_name_to_vks(name)
            if vks:
                groups.append(frozenset(vks))
                all_vks |= vks
        self._hotkey_vk_groups = groups
        self._hotkey_vks = all_vks
        logger.info("Hotkey VK groups: %s (from %s)",
                     [[hex(v) for v in sorted(g)] for g in groups], hotkey_keys)

    def _all_groups_pressed(self) -> bool:
        """Check if at least one VK from each hotkey group is pressed."""
        return bool(self._hotkey_vk_groups) and all(
            group & self._vks_pressed
            for group in self._hotkey_vk_groups
        )

    def start(self) -> None:
        self._hook = KeySuppressionHook(self._on_key_event)
        self._hook.start()
        logger.info("Hotkey manager started (suppression hook)")

    def stop(self) -> None:
        if self._hook is not None:
            self._hook.stop()
            self._hook = None
        with self._lock:
            self._vks_pressed.clear()
            self._is_active = False
        logger.info("Hotkey manager stopped")

    def update_hotkey(self, hotkey_keys: list[str]) -> None:
        with self._lock:
            self._set_hotkey_keys(hotkey_keys)
            self._vks_pressed.clear()
            self._is_active = False
        logger.info("Hotkey updated")

    def update_mode(self, mode: str) -> None:
        with self._lock:
            self._mode = mode
            self._vks_pressed.clear()
            self._is_active = False
        logger.info("Hotkey mode updated to: %s", mode)

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def hotkey_vks(self) -> frozenset[int]:
        """VK codes forming the hotkey.  Used by TextInjector."""
        return frozenset(self._hotkey_vks)

    # ---- Hook callback (runs on the hook thread) ----

    def _on_key_event(self, vk: int, scan: int,
                      is_down: bool, is_injected: bool) -> bool:
        """Returns True to suppress the event, False to pass through."""
        # Never suppress our own SendInput events
        if is_injected:
            return False

        is_hotkey_vk = vk in self._hotkey_vks
        if not is_hotkey_vk:
            return False

        with self._lock:
            if self._mode == self.MODE_TOGGLE:
                return self._handle_toggle_vk(vk, is_down)
            else:
                return self._handle_push_to_talk_vk(vk, is_down)

    def _handle_push_to_talk_vk(self, vk: int, is_down: bool) -> bool:
        """Push-to-talk: hold to record, release to stop.

        Returns True to suppress the event.
        """
        if is_down:
            self._vks_pressed.add(vk)
            if not self._is_active and self._all_groups_pressed():
                self._is_active = True
                if self._on_start:
                    threading.Thread(
                        target=self._on_start, daemon=True,
                    ).start()
                # Suppress the activating key-down so OS never sees it
                return True
            # Suppress repeated key-down while active
            return self._is_active
        else:
            # KEY_UP
            if self._is_active and vk in self._hotkey_vks:
                self._is_active = False
                if self._on_stop:
                    threading.Thread(
                        target=self._on_stop, daemon=True,
                    ).start()
                self._vks_pressed.discard(vk)
                # Suppress the release so OS never sees Win UP etc.
                return True
            self._vks_pressed.discard(vk)
            return False

    def _handle_toggle_vk(self, vk: int, is_down: bool) -> bool:
        """Toggle: press once to start, press again to stop.

        Returns True to suppress the event.
        """
        if is_down:
            self._vks_pressed.add(vk)
            if not self._toggle_fired and self._all_groups_pressed():
                self._toggle_fired = True
                if not self._is_active:
                    self._is_active = True
                    if self._on_start:
                        threading.Thread(
                            target=self._on_start, daemon=True,
                        ).start()
                else:
                    self._is_active = False
                    if self._on_stop:
                        threading.Thread(
                            target=self._on_stop, daemon=True,
                        ).start()
                return True  # suppress the activating key-down
            # Suppress repeated key-down while active
            return self._is_active
        else:
            # KEY_UP
            suppress = self._is_active
            if vk in self._hotkey_vks:
                self._toggle_fired = False
            self._vks_pressed.discard(vk)
            return suppress
