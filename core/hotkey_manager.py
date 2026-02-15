"""Dual hotkey manager using macOS CGEventTap.

Supports two independent hotkey bindings:
- push_to_talk: long-press to record, short-press passes through
- toggle: press once to start, press again to stop

Uses Quartz CGEventTap for global keyboard monitoring (requires Accessibility permission).
"""

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

# macOS key codes for common keys
_KEY_NAMES_TO_CODES: dict[str, set[int]] = {
    "right command": {54},
    "left command": {55},
    "command": {54, 55},
    "right shift": {60},
    "left shift": {56},
    "shift": {56, 60},
    "right option": {61},
    "left option": {58},
    "option": {58, 61},
    "alt": {58, 61},
    "right control": {62},
    "left control": {59},
    "control": {59, 62},
    "right ctrl": {62},
    "left ctrl": {59},
    "ctrl": {59, 62},
    "caps lock": {57},
    "fn": {63},
    "f1": {122}, "f2": {120}, "f3": {99}, "f4": {118},
    "f5": {96}, "f6": {97}, "f7": {98}, "f8": {100},
    "f9": {101}, "f10": {109}, "f11": {103}, "f12": {111},
    "space": {49},
    "return": {36}, "enter": {76},
    "tab": {48},
    "escape": {53},
}


def _key_name_to_codes(name: str) -> set[int]:
    result = _KEY_NAMES_TO_CODES.get(name.lower(), set())
    if not result:
        logger.warning("Unknown key name: %r", name)
    return set(result)


def _keys_to_code_groups(keys: list[str]) -> tuple[list[frozenset[int]], set[int]]:
    groups: list[frozenset[int]] = []
    all_codes: set[int] = set()
    for name in keys:
        codes = _key_name_to_codes(name)
        if codes:
            groups.append(frozenset(codes))
            all_codes |= codes
    return groups, all_codes


class _BindingConfig:
    def __init__(self, enabled: bool, keys: list[str]):
        self.enabled = enabled
        self.code_groups, self.all_codes = _keys_to_code_groups(keys) if enabled else ([], set())

    def all_groups_pressed(self, codes_pressed: set[int]) -> bool:
        return bool(self.code_groups) and all(
            group & codes_pressed for group in self.code_groups
        )


class DualHotkeyManager:
    """Manages two hotkey bindings using a single CGEventTap."""

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

        self._tap = None
        self._thread: threading.Thread | None = None
        self._run_loop = None

        logger.info(
            "DualHotkeyManager: ptt=%s (enabled=%s, long_press=%dms), toggle=%s (enabled=%s)",
            ptt_keys, ptt_enabled, ptt_long_press_ms, toggle_keys, toggle_enabled,
        )

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_tap, daemon=True, name="HotkeyTap")
        self._thread.start()
        logger.info("DualHotkeyManager started")

    def stop(self) -> None:
        if self._run_loop is not None:
            from Quartz import CFRunLoopStop
            CFRunLoopStop(self._run_loop)
        if self._tap is not None:
            from Quartz import CGEventTapEnable
            CGEventTapEnable(self._tap, False)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        with self._lock:
            self._cancel_ptt_timer()
            self._codes_pressed.clear()
            self._is_active = False
            self._active_mode = None
        self._tap = None
        self._run_loop = None
        logger.info("DualHotkeyManager stopped")

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def hotkey_vks(self) -> frozenset[int]:
        """Union of all key codes from both bindings (kept for API compat)."""
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

    def _run_tap(self) -> None:
        """Install CGEventTap and run the CFRunLoop."""
        from Quartz import (
            CGEventTapCreate, CGEventTapEnable,
            CFMachPortCreateRunLoopSource,
            CFRunLoopAddSource, CFRunLoopGetCurrent, CFRunLoopRun,
            kCGSessionEventTap, kCGHeadInsertEventTap,
            kCGEventKeyDown, kCGEventKeyUp, kCGEventFlagsChanged,
            CGEventGetIntegerValueField, kCGKeyboardEventKeycode,
            kCFRunLoopCommonModes,
        )

        # Track modifier state for flagsChanged events
        self._modifier_keys = {54, 55, 56, 57, 58, 59, 60, 61, 62, 63}

        def callback(proxy, event_type, event, refcon):
            try:
                keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)

                if event_type == kCGEventFlagsChanged:
                    # For modifier keys, determine press/release from flags
                    is_down = self._is_modifier_down(event, keycode)
                elif event_type == kCGEventKeyDown:
                    is_down = True
                elif event_type == kCGEventKeyUp:
                    is_down = False
                else:
                    return event

                suppress = self._on_key_event(keycode, is_down)
                if suppress:
                    return None  # Suppress the event
            except Exception:
                logger.exception("Error in hotkey callback")
            return event

        mask = (1 << kCGEventKeyDown) | (1 << kCGEventKeyUp) | (1 << kCGEventFlagsChanged)
        self._tap = CGEventTapCreate(
            kCGSessionEventTap, kCGHeadInsertEventTap, 0,
            mask, callback, None,
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

    def _is_modifier_down(self, event, keycode: int) -> bool:
        """Determine if a modifier key is pressed or released from flags."""
        from Quartz import CGEventGetFlags, kCGEventFlagMaskCommand, kCGEventFlagMaskShift, \
            kCGEventFlagMaskAlternate, kCGEventFlagMaskControl, kCGEventFlagMaskAlphaShift
        flags = CGEventGetFlags(event)

        # Map keycode to its flag mask
        flag_map = {
            54: kCGEventFlagMaskCommand,   # Right Cmd
            55: kCGEventFlagMaskCommand,   # Left Cmd
            56: kCGEventFlagMaskShift,     # Left Shift
            60: kCGEventFlagMaskShift,     # Right Shift
            58: kCGEventFlagMaskAlternate, # Left Option
            61: kCGEventFlagMaskAlternate, # Right Option
            59: kCGEventFlagMaskControl,   # Left Control
            62: kCGEventFlagMaskControl,   # Right Control
            57: kCGEventFlagMaskAlphaShift,# Caps Lock
            63: 0x800000,                  # Fn key (NSEventModifierFlagFunction)
        }
        mask = flag_map.get(keycode, 0)
        if mask == 0:
            return False
        return bool(flags & mask)

    def _on_key_event(self, keycode: int, is_down: bool) -> bool:
        """Returns True to suppress the event."""
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
