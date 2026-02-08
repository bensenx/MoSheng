"""Dual hotkey manager with hook-level key suppression.

Supports two independent hotkey bindings running simultaneously:
- push_to_talk: long-press to record, short-press replays original key
- toggle: press once to start, press again to stop

Both share a single WH_KEYBOARD_LL hook (via KeySuppressionHook) and a
mutual exclusion lock so only one can be active at a time.
"""

import ctypes
import ctypes.wintypes
import logging
import threading
import time
from collections.abc import Callable

from core.key_suppression_hook import KeySuppressionHook

logger = logging.getLogger(__name__)

# Build a name -> VK code mapping from the keyboard library's table.
_NAME_TO_VKS: dict[str, set[int]] = {}

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002


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
    """Convert a key name (e.g. 'ctrl', 'caps lock') to VK codes."""
    _build_name_to_vks()
    result = _NAME_TO_VKS.get(name.lower(), set())
    if not result:
        logger.warning("Unknown key name: %r", name)
    return set(result)


def _keys_to_vk_groups(keys: list[str]) -> tuple[list[frozenset[int]], set[int]]:
    """Convert key name list to VK groups + flat VK set."""
    groups: list[frozenset[int]] = []
    all_vks: set[int] = set()
    for name in keys:
        vks = _key_name_to_vks(name)
        if vks:
            groups.append(frozenset(vks))
            all_vks |= vks
    return groups, all_vks


# ---- SendInput helpers for key replay ----

class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long), ("dy", ctypes.c_long),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD), ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD), ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.wintypes.DWORD),
        ("wParamL", ctypes.wintypes.WORD), ("wParamH", ctypes.wintypes.WORD),
    ]

class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]
    _fields_ = [("type", ctypes.wintypes.DWORD), ("_input", _U)]


def _replay_key(vk: int) -> None:
    """Send a key down+up via SendInput (will have INJECTED flag)."""
    down = _INPUT()
    down.type = INPUT_KEYBOARD
    down._input.ki.wVk = vk

    up = _INPUT()
    up.type = INPUT_KEYBOARD
    up._input.ki.wVk = vk
    up._input.ki.dwFlags = KEYEVENTF_KEYUP

    arr = (_INPUT * 2)(down, up)
    ctypes.windll.user32.SendInput(2, ctypes.byref(arr), ctypes.sizeof(_INPUT))


# ---- Binding configuration ----

class _BindingConfig:
    """Runtime state for one hotkey binding."""

    def __init__(self, enabled: bool, keys: list[str]):
        self.enabled = enabled
        self.vk_groups, self.all_vks = _keys_to_vk_groups(keys) if enabled else ([], set())

    def all_groups_pressed(self, vks_pressed: set[int]) -> bool:
        return bool(self.vk_groups) and all(
            group & vks_pressed for group in self.vk_groups
        )


class DualHotkeyManager:
    """Manages two hotkey bindings sharing one keyboard hook."""

    def __init__(
        self,
        ptt_keys: list[str],
        ptt_enabled: bool,
        ptt_long_press_ms: int,
        toggle_keys: list[str],
        toggle_enabled: bool,
        on_start: Callable | None = None,
        on_stop: Callable | None = None,
    ):
        self._on_start = on_start
        self._on_stop = on_stop
        self._lock = threading.Lock()
        self._hook: KeySuppressionHook | None = None

        # Binding configs
        self._ptt = _BindingConfig(ptt_enabled, ptt_keys)
        self._toggle = _BindingConfig(toggle_enabled, toggle_keys)
        self._ptt_long_press_ms = ptt_long_press_ms

        # State
        self._vks_pressed: set[int] = set()
        self._is_active = False           # Recording in progress (either mode)
        self._active_mode: str | None = None  # "ptt" or "toggle"

        # Push-to-talk long-press state
        self._ptt_press_time: float | None = None
        self._ptt_long_triggered = False
        self._ptt_timer: threading.Timer | None = None

        # Toggle anti-repeat
        self._toggle_fired = False

        logger.info(
            "DualHotkeyManager: ptt=%s (enabled=%s, long_press=%dms), "
            "toggle=%s (enabled=%s)",
            [hex(v) for g in self._ptt.vk_groups for v in g], ptt_enabled,
            ptt_long_press_ms,
            [hex(v) for g in self._toggle.vk_groups for v in g], toggle_enabled,
        )

    def start(self) -> None:
        self._hook = KeySuppressionHook(self._on_key_event)
        self._hook.start()
        logger.info("DualHotkeyManager started")

    def stop(self) -> None:
        if self._hook is not None:
            self._hook.stop()
            self._hook = None
        with self._lock:
            self._cancel_ptt_timer()
            self._vks_pressed.clear()
            self._is_active = False
            self._active_mode = None
        logger.info("DualHotkeyManager stopped")

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def hotkey_vks(self) -> frozenset[int]:
        """Union of all VKs from both bindings. Used by TextInjector."""
        return frozenset(self._ptt.all_vks | self._toggle.all_vks)

    def update_bindings(
        self,
        ptt_keys: list[str],
        ptt_enabled: bool,
        ptt_long_press_ms: int,
        toggle_keys: list[str],
        toggle_enabled: bool,
    ) -> None:
        with self._lock:
            self._ptt = _BindingConfig(ptt_enabled, ptt_keys)
            self._toggle = _BindingConfig(toggle_enabled, toggle_keys)
            self._ptt_long_press_ms = ptt_long_press_ms
            self._cancel_ptt_timer()
            self._vks_pressed.clear()
            self._is_active = False
            self._active_mode = None
            self._toggle_fired = False
        logger.info("Bindings updated: ptt_enabled=%s, toggle_enabled=%s",
                     ptt_enabled, toggle_enabled)

    # ---- Hook callback (runs on the hook thread) ----

    def _on_key_event(self, vk: int, scan: int,
                      is_down: bool, is_injected: bool) -> bool:
        """Returns True to suppress the event, False to pass through."""
        if is_injected:
            return False

        is_ptt_vk = self._ptt.enabled and vk in self._ptt.all_vks
        is_toggle_vk = self._toggle.enabled and vk in self._toggle.all_vks

        if not is_ptt_vk and not is_toggle_vk:
            return False

        with self._lock:
            # If active, only the active mode's handler processes events
            if self._is_active:
                if self._active_mode == "ptt" and is_ptt_vk:
                    return self._handle_ptt_vk(vk, is_down)
                elif self._active_mode == "toggle" and is_toggle_vk:
                    return self._handle_toggle_vk(vk, is_down)
                # Suppress hotkey VKs of the *other* mode while recording
                return True

            # Not active: either mode can trigger
            if is_ptt_vk:
                return self._handle_ptt_vk(vk, is_down)
            if is_toggle_vk:
                return self._handle_toggle_vk(vk, is_down)

        return False

    # ---- Push-to-talk with long-press detection ----

    def _handle_ptt_vk(self, vk: int, is_down: bool) -> bool:
        if is_down:
            self._vks_pressed.add(vk)

            if self._is_active:
                return True  # Suppress repeat key-down while recording

            if self._ptt.all_groups_pressed(self._vks_pressed):
                if self._ptt_press_time is None:
                    self._ptt_press_time = time.perf_counter()
                    self._ptt_long_triggered = False
                    self._cancel_ptt_timer()
                    self._ptt_timer = threading.Timer(
                        self._ptt_long_press_ms / 1000.0,
                        self._ptt_long_press_fired,
                    )
                    self._ptt_timer.daemon = True
                    self._ptt_timer.start()
                return True  # Suppress while deciding short/long

            return False
        else:
            # KEY_UP
            was_all_pressed = self._ptt.all_groups_pressed(self._vks_pressed)
            self._vks_pressed.discard(vk)

            if self._is_active and self._active_mode == "ptt":
                # Long press was active, stop recording
                self._is_active = False
                self._active_mode = None
                self._ptt_press_time = None
                self._ptt_long_triggered = False
                if self._on_stop:
                    threading.Thread(target=self._on_stop, daemon=True).start()
                return True

            if was_all_pressed and self._ptt_press_time is not None:
                # Short press: cancel timer and replay original key
                self._cancel_ptt_timer()
                self._ptt_press_time = None
                was_long = self._ptt_long_triggered
                self._ptt_long_triggered = False

                if not was_long:
                    replay_vk = vk
                    threading.Thread(
                        target=_replay_key, args=(replay_vk,), daemon=True,
                    ).start()
                    logger.debug("PTT short-press: replaying VK 0x%X", replay_vk)

                return True  # Suppress original release

            return False

    def _ptt_long_press_fired(self) -> None:
        """Called from timer thread when long-press threshold is exceeded."""
        with self._lock:
            if self._ptt_press_time is None:
                return  # Already cancelled
            self._ptt_long_triggered = True
            self._is_active = True
            self._active_mode = "ptt"
            logger.info("PTT long-press triggered")
        if self._on_start:
            self._on_start()

    def _cancel_ptt_timer(self) -> None:
        if self._ptt_timer is not None:
            self._ptt_timer.cancel()
            self._ptt_timer = None

    # ---- Toggle mode ----

    def _handle_toggle_vk(self, vk: int, is_down: bool) -> bool:
        if is_down:
            self._vks_pressed.add(vk)
            if not self._toggle_fired and self._toggle.all_groups_pressed(self._vks_pressed):
                self._toggle_fired = True
                if not self._is_active:
                    self._is_active = True
                    self._active_mode = "toggle"
                    if self._on_start:
                        threading.Thread(
                            target=self._on_start, daemon=True,
                        ).start()
                else:
                    self._is_active = False
                    self._active_mode = None
                    if self._on_stop:
                        threading.Thread(
                            target=self._on_stop, daemon=True,
                        ).start()
                return True
            return self._is_active and self._active_mode == "toggle"
        else:
            # KEY_UP
            suppress = self._is_active and self._active_mode == "toggle"
            if vk in self._toggle.all_vks:
                self._toggle_fired = False
            self._vks_pressed.discard(vk)
            return suppress
