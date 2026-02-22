"""Text injection via clipboard + paste keystroke (cross-platform)."""

import logging
import sys
import threading
import time

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes
    import win32clipboard
    import win32con

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    VK_CONTROL = 0x11
    VK_V = 0x56

    _ALL_MODIFIER_VKS = (
        0x10, 0xA0, 0xA1,
        0x11, 0xA2, 0xA3,
        0x12, 0xA4, 0xA5,
        0x5B, 0x5C,
    )

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long), ("dy", ctypes.c_long),
            ("mouseData", ctypes.wintypes.DWORD),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.wintypes.WORD), ("wScan", ctypes.wintypes.WORD),
            ("dwFlags", ctypes.wintypes.DWORD), ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.wintypes.DWORD),
            ("wParamL", ctypes.wintypes.WORD), ("wParamH", ctypes.wintypes.WORD),
        ]

    class INPUT(ctypes.Structure):
        class _INPUT(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]
        _fields_ = [("type", ctypes.wintypes.DWORD), ("_input", _INPUT)]

    def _make_key_input(vk: int, flags: int = 0) -> INPUT:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp._input.ki.wVk = vk
        inp._input.ki.dwFlags = flags
        return inp

    def _make_unicode_input(char: str, flags: int = KEYEVENTF_UNICODE) -> INPUT:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp._input.ki.wVk = 0
        inp._input.ki.wScan = ord(char)
        inp._input.ki.dwFlags = flags
        return inp

    def _send_inputs(*inputs):
        arr = (INPUT * len(inputs))(*inputs)
        ctypes.windll.user32.SendInput(len(inputs), ctypes.byref(arr), ctypes.sizeof(INPUT))

    def _send_paste(hotkey_vks: frozenset[int] = frozenset()):
        inputs: list[INPUT] = []
        for vk in _ALL_MODIFIER_VKS:
            if vk in hotkey_vks:
                continue
            if vk == VK_CONTROL:
                continue
            if ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000:
                inputs.append(_make_key_input(vk, KEYEVENTF_KEYUP))
        inputs.extend([
            _make_key_input(VK_CONTROL),
            _make_key_input(VK_V),
            _make_key_input(VK_V, KEYEVENTF_KEYUP),
            _make_key_input(VK_CONTROL, KEYEVENTF_KEYUP),
        ])
        _send_inputs(*inputs)

elif sys.platform == "darwin":
    import subprocess

    def _send_paste(**_kwargs):
        from Quartz import (
            CGEventCreateKeyboardEvent, CGEventPost, CGEventSetFlags,
            kCGHIDEventTap, kCGEventFlagMaskCommand,
        )
        event_down = CGEventCreateKeyboardEvent(None, 9, True)
        CGEventSetFlags(event_down, kCGEventFlagMaskCommand)
        event_up = CGEventCreateKeyboardEvent(None, 9, False)
        CGEventSetFlags(event_up, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, event_down)
        CGEventPost(kCGHIDEventTap, event_up)
else:
    def _send_paste(**_kwargs):
        logger.warning("Paste keystroke not implemented for %s", sys.platform)


class TextInjector:
    def __init__(self, restore_clipboard: bool = True):
        self._restore_clipboard = restore_clipboard
        self._saved_clipboard: str | None = None
        self._hotkey_vks: frozenset[int] = frozenset()

    @property
    def restore_clipboard(self) -> bool:
        return self._restore_clipboard

    @restore_clipboard.setter
    def restore_clipboard(self, value: bool) -> None:
        self._restore_clipboard = value

    @property
    def hotkey_vks(self) -> frozenset[int]:
        return self._hotkey_vks

    @hotkey_vks.setter
    def hotkey_vks(self, value: frozenset[int]) -> None:
        self._hotkey_vks = value

    def save_clipboard(self) -> None:
        self._saved_clipboard = self._get_clipboard()

    def restore_saved_clipboard(self) -> None:
        if self._saved_clipboard is not None:
            threading.Timer(0.3, self._set_clipboard, args=(self._saved_clipboard,)).start()
            self._saved_clipboard = None

    def inject_char_unicode(self, char: str) -> None:
        """Type a single Unicode character via SendInput (no clipboard, zero latency)."""
        try:
            _send_inputs(
                _make_unicode_input(char),
                _make_unicode_input(char, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
            )
            time.sleep(0.02)
            logger.info("inject_char_unicode: %r", char)
        except Exception:
            logger.warning("inject_char_unicode failed for char %r", char)

    def inject_text_no_restore(self, text: str) -> None:
        if not text.strip():
            logger.info("Empty text, skipping injection")
            return
        self._set_clipboard(text)
        time.sleep(0.05)
        _send_paste(hotkey_vks=self._hotkey_vks)
        logger.info("Injected text (no restore): %s", text[:80])

    def inject_text(self, text: str) -> None:
        if not text.strip():
            logger.info("Empty text, skipping injection")
            return
        old_clipboard = self._get_clipboard() if self._restore_clipboard else None
        self._set_clipboard(text)
        time.sleep(0.05)
        _send_paste(hotkey_vks=self._hotkey_vks)
        logger.info("Injected text: %s", text[:80])
        if self._restore_clipboard and old_clipboard is not None:
            threading.Timer(0.5, self._set_clipboard, args=(old_clipboard,)).start()

    def _get_clipboard(self) -> str | None:
        if sys.platform == "win32":
            try:
                win32clipboard.OpenClipboard()
                try:
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                        return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                finally:
                    win32clipboard.CloseClipboard()
            except Exception:
                logger.debug("Could not read clipboard")
            return None
        elif sys.platform == "darwin":
            try:
                result = subprocess.run(
                    ["pbpaste"], capture_output=True, text=True, timeout=2,
                )
                if result.returncode == 0:
                    return result.stdout
            except Exception:
                logger.debug("Could not read clipboard")
            return None
        return None

    def _set_clipboard(self, text: str) -> None:
        if sys.platform == "win32":
            for _ in range(3):
                try:
                    win32clipboard.OpenClipboard()
                    try:
                        win32clipboard.EmptyClipboard()
                        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                    finally:
                        win32clipboard.CloseClipboard()
                    return
                except Exception:
                    time.sleep(0.05)
            logger.warning("Failed to set clipboard after retries")
        elif sys.platform == "darwin":
            try:
                subprocess.run(
                    ["pbcopy"], input=text, text=True, timeout=2, check=True,
                )
            except Exception:
                logger.warning("Failed to set clipboard")
