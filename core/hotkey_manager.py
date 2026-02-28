"""Dual hotkey manager (cross-platform).

Supports two independent hotkey bindings:
- push_to_talk: long-press to record, short-press passes through
- toggle: press once to start, press again to stop

macOS: CGEventTap (requires Accessibility permission)
Windows: WH_KEYBOARD_LL via KeySuppressionHook
"""

import logging
import sys
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

# ---- Platform-specific key name → code mapping ----

if sys.platform == "darwin":
    _KEY_NAMES_TO_CODES: dict[str, set[int]] = {
        "right command": {54}, "left command": {55}, "command": {54, 55},
        "right shift": {60}, "left shift": {56}, "shift": {56, 60},
        "right option": {61}, "left option": {58}, "option": {58, 61},
        "alt": {58, 61},
        "right control": {62}, "left control": {59}, "control": {59, 62},
        "right ctrl": {62}, "left ctrl": {59}, "ctrl": {59, 62},
        "caps lock": {57}, "fn": {63},
        "f1": {122}, "f2": {120}, "f3": {99}, "f4": {118},
        "f5": {96}, "f6": {97}, "f7": {98}, "f8": {100},
        "f9": {101}, "f10": {109}, "f11": {103}, "f12": {111},
        "space": {49}, "return": {36}, "enter": {76},
        "tab": {48}, "escape": {53},
    }

    def _key_name_to_codes(name: str) -> set[int]:
        result = _KEY_NAMES_TO_CODES.get(name.lower(), set())
        if not result:
            logger.warning("Unknown key name: %r", name)
        return set(result)

elif sys.platform == "win32":
    _NAME_TO_VKS: dict[str, set[int]] = {}

    def _build_name_to_vks() -> None:
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

    def _key_name_to_codes(name: str) -> set[int]:
        _build_name_to_vks()
        result = _NAME_TO_VKS.get(name.lower(), set())
        if not result:
            logger.warning("Unknown key name: %r", name)
        return set(result)
else:
    def _key_name_to_codes(name: str) -> set[int]:
        logger.warning("Hotkeys not supported on %s", sys.platform)
        return set()


def _keys_to_code_groups(keys: list[str]) -> tuple[list[frozenset[int]], set[int]]:
    groups: list[frozenset[int]] = []
    all_codes: set[int] = set()
    for name in keys:
        codes = _key_name_to_codes(name)
        if codes:
            groups.append(frozenset(codes))
            all_codes |= codes
    return groups, all_codes


# ---- Windows: SendInput for key replay ----

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002

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
        down = _INPUT(); down.type = INPUT_KEYBOARD; down._input.ki.wVk = vk
        up = _INPUT(); up.type = INPUT_KEYBOARD; up._input.ki.wVk = vk
        up._input.ki.dwFlags = KEYEVENTF_KEYUP
        arr = (_INPUT * 2)(down, up)
        ctypes.windll.user32.SendInput(2, ctypes.byref(arr), ctypes.sizeof(_INPUT))


# ---- Binding configuration ----

class _BindingConfig:
    def __init__(self, enabled: bool, keys: list[str]):
        self.enabled = enabled
        self.code_groups, self.all_codes = _keys_to_code_groups(keys) if enabled else ([], set())

    def all_groups_pressed(self, codes_pressed: set[int]) -> bool:
        return bool(self.code_groups) and all(
            group & codes_pressed for group in self.code_groups
        )


class DualHotkeyManager:
    """Manages two hotkey bindings (cross-platform)."""

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

        self._ptt = _BindingConfig(ptt_enabled, ptt_keys)
        self._toggle = _BindingConfig(toggle_enabled, toggle_keys)
        self._ptt_long_press_ms = ptt_long_press_ms

        self._codes_pressed: set[int] = set()
        self._is_active = False
        self._active_mode: str | None = None

        self._ptt_press_time: float | None = None
        self._ptt_long_triggered = False
        self._ptt_timer: threading.Timer | None = None
        self._toggle_fired = False

        # Platform-specific handles
        self._tap = None          # macOS CGEventTap
        self._run_loop = None     # macOS CFRunLoop
        self._hook = None         # Windows KeySuppressionHook
        self._thread: threading.Thread | None = None

        logger.info(
            "DualHotkeyManager: ptt=%s (enabled=%s, long_press=%dms), toggle=%s (enabled=%s)",
            ptt_keys, ptt_enabled, ptt_long_press_ms, toggle_keys, toggle_enabled,
        )

    def start(self) -> None:
        if sys.platform == "darwin":
            self._thread = threading.Thread(target=self._run_tap_macos, daemon=True, name="HotkeyTap")
            self._thread.start()
        elif sys.platform == "win32":
            from core.key_suppression_hook import KeySuppressionHook
            self._hook = KeySuppressionHook(self._on_key_event_win32)
            self._hook.start()
        logger.info("DualHotkeyManager started")

    def stop(self) -> None:
        if sys.platform == "darwin":
            if self._run_loop is not None:
                from Quartz import CFRunLoopStop
                CFRunLoopStop(self._run_loop)
            if self._tap is not None:
                from Quartz import CGEventTapEnable
                CGEventTapEnable(self._tap, False)
            if self._thread is not None:
                self._thread.join(timeout=5.0)
                self._thread = None
            self._tap = None
            self._run_loop = None
        elif sys.platform == "win32":
            if self._hook is not None:
                self._hook.stop()
                self._hook = None
        with self._lock:
            self._cancel_ptt_timer()
            self._codes_pressed.clear()
            self._is_active = False
            self._active_mode = None
        logger.info("DualHotkeyManager stopped")

    def reinstall_hook(self) -> None:
        """Reinstall the keyboard hook to recover from silent removal by Windows."""
        if sys.platform == "win32" and self._hook is not None:
            self._hook.reinstall()

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def hotkey_vks(self) -> frozenset[int]:
        return frozenset(self._ptt.all_codes | self._toggle.all_codes)

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
            self._codes_pressed.clear()
            self._is_active = False
            self._active_mode = None
            self._toggle_fired = False
        logger.info("Bindings updated")

    # ================================================================
    # macOS: CGEventTap
    # ================================================================

    def _run_tap_macos(self) -> None:
        from Quartz import (
            CGEventTapCreate, CGEventTapEnable,
            CFMachPortCreateRunLoopSource,
            CFRunLoopAddSource, CFRunLoopGetCurrent, CFRunLoopRun,
            kCGSessionEventTap, kCGHeadInsertEventTap,
            kCGEventKeyDown, kCGEventKeyUp, kCGEventFlagsChanged,
            CGEventGetIntegerValueField, kCGKeyboardEventKeycode,
            kCFRunLoopCommonModes,
        )

        self._modifier_keys = {54, 55, 56, 57, 58, 59, 60, 61, 62, 63}

        def callback(proxy, event_type, event, refcon):
            try:
                keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                if event_type == kCGEventFlagsChanged:
                    is_down = self._is_modifier_down_macos(event, keycode)
                elif event_type == kCGEventKeyDown:
                    is_down = True
                elif event_type == kCGEventKeyUp:
                    is_down = False
                else:
                    return event
                suppress = self._on_key_event_common(keycode, is_down)
                if suppress:
                    return None
            except Exception:
                logger.exception("Error in hotkey callback")
            return event

        mask = (1 << kCGEventKeyDown) | (1 << kCGEventKeyUp) | (1 << kCGEventFlagsChanged)
        self._tap = CGEventTapCreate(
            kCGSessionEventTap, kCGHeadInsertEventTap, 0, mask, callback, None,
        )
        if self._tap is None:
            logger.error(
                "Failed to create CGEventTap. "
                "Grant Accessibility permission in System Settings > Privacy & Security > Accessibility"
            )
            return

        source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._run_loop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(self._run_loop, source, kCFRunLoopCommonModes)
        CGEventTapEnable(self._tap, True)
        logger.info("CGEventTap installed")
        CFRunLoopRun()
        logger.info("CGEventTap run loop exited")

    def _is_modifier_down_macos(self, event, keycode: int) -> bool:
        from Quartz import (CGEventGetFlags, kCGEventFlagMaskCommand, kCGEventFlagMaskShift,
                            kCGEventFlagMaskAlternate, kCGEventFlagMaskControl, kCGEventFlagMaskAlphaShift)
        flags = CGEventGetFlags(event)
        flag_map = {
            54: kCGEventFlagMaskCommand, 55: kCGEventFlagMaskCommand,
            56: kCGEventFlagMaskShift, 60: kCGEventFlagMaskShift,
            58: kCGEventFlagMaskAlternate, 61: kCGEventFlagMaskAlternate,
            59: kCGEventFlagMaskControl, 62: kCGEventFlagMaskControl,
            57: kCGEventFlagMaskAlphaShift, 63: 0x800000,
        }
        mask = flag_map.get(keycode, 0)
        return bool(flags & mask) if mask else False

    # ================================================================
    # Windows: KeySuppressionHook callback
    # ================================================================

    def _on_key_event_win32(self, vk: int, scan: int,
                            is_down: bool, is_injected: bool) -> bool:
        if is_injected:
            return False
        return self._on_key_event_common(vk, is_down)

    # ================================================================
    # Shared logic
    # ================================================================

    def _on_key_event_common(self, keycode: int, is_down: bool) -> bool:
        is_ptt_key = self._ptt.enabled and keycode in self._ptt.all_codes
        is_toggle_key = self._toggle.enabled and keycode in self._toggle.all_codes

        if not is_ptt_key and not is_toggle_key:
            return False

        with self._lock:
            if self._is_active:
                if self._active_mode == "ptt" and is_ptt_key:
                    return self._handle_ptt(keycode, is_down)
                elif self._active_mode == "toggle" and is_toggle_key:
                    return self._handle_toggle(keycode, is_down)
                return True

            if is_ptt_key:
                return self._handle_ptt(keycode, is_down)
            if is_toggle_key:
                return self._handle_toggle(keycode, is_down)

        return False

    def _handle_ptt(self, keycode: int, is_down: bool) -> bool:
        if is_down:
            self._codes_pressed.add(keycode)
            if self._is_active:
                return True
            if self._ptt.all_groups_pressed(self._codes_pressed):
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
                return True
            return False
        else:
            was_all_pressed = self._ptt.all_groups_pressed(self._codes_pressed)
            self._codes_pressed.discard(keycode)

            if self._is_active and self._active_mode == "ptt":
                self._is_active = False
                self._active_mode = None
                self._ptt_press_time = None
                self._ptt_long_triggered = False
                if self._on_stop:
                    threading.Thread(target=self._on_stop, daemon=True).start()
                return True

            if was_all_pressed and self._ptt_press_time is not None:
                self._cancel_ptt_timer()
                self._ptt_press_time = None
                was_long = self._ptt_long_triggered
                self._ptt_long_triggered = False

                if not was_long:
                    # On Windows, replay the key; on macOS, just log
                    if sys.platform == "win32":
                        threading.Thread(
                            target=_replay_key, args=(keycode,), daemon=True,
                        ).start()
                    logger.debug("PTT short-press, passing through")
                return True
            return False

    def _ptt_long_press_fired(self) -> None:
        with self._lock:
            if self._ptt_press_time is None:
                return
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

    def _handle_toggle(self, keycode: int, is_down: bool) -> bool:
        if is_down:
            self._codes_pressed.add(keycode)
            if not self._toggle_fired and self._toggle.all_groups_pressed(self._codes_pressed):
                self._toggle_fired = True
                if not self._is_active:
                    self._is_active = True
                    self._active_mode = "toggle"
                    if self._on_start:
                        threading.Thread(target=self._on_start, daemon=True).start()
                else:
                    self._is_active = False
                    self._active_mode = None
                    if self._on_stop:
                        threading.Thread(target=self._on_stop, daemon=True).start()
                return True
            return self._is_active and self._active_mode == "toggle"
        else:
            suppress = self._is_active and self._active_mode == "toggle"
            if keycode in self._toggle.all_codes:
                self._toggle_fired = False
            self._codes_pressed.discard(keycode)
            return suppress
