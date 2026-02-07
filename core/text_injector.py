"""Text injection via clipboard + SendInput Ctrl+V."""

import ctypes
import ctypes.wintypes
import logging
import threading
import time

import win32clipboard
import win32con

logger = logging.getLogger(__name__)

# ---- SendInput structures (correct sizing for x64) ----

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_V = 0x56
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_MENU = 0x12
VK_SHIFT = 0x10

_MODIFIER_VKS = (VK_CONTROL, VK_LWIN, VK_RWIN, VK_MENU, VK_SHIFT)


class MOUSEINPUT(ctypes.Structure):
    """Needed in the union so sizeof(INPUT) == 40 on x64."""
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.wintypes.DWORD),
        ("wParamL", ctypes.wintypes.WORD),
        ("wParamH", ctypes.wintypes.WORD),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("_input", _INPUT),
    ]


def _make_key_input(vk: int, flags: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp._input.ki.wVk = vk
    inp._input.ki.dwFlags = flags
    return inp


def _send_inputs(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    ctypes.windll.user32.SendInput(len(inputs), ctypes.byref(arr), ctypes.sizeof(INPUT))


def _release_modifiers():
    """Release any modifier keys still held down by the OS."""
    for vk in _MODIFIER_VKS:
        if ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000:
            _send_inputs(_make_key_input(vk, KEYEVENTF_KEYUP))


def _send_ctrl_v():
    _release_modifiers()
    time.sleep(0.05)
    _send_inputs(
        _make_key_input(VK_CONTROL),
        _make_key_input(VK_V),
        _make_key_input(VK_V, KEYEVENTF_KEYUP),
        _make_key_input(VK_CONTROL, KEYEVENTF_KEYUP),
    )


# ---- TextInjector ----

class TextInjector:
    def __init__(self, restore_clipboard: bool = True):
        self._restore_clipboard = restore_clipboard

    @property
    def restore_clipboard(self) -> bool:
        return self._restore_clipboard

    @restore_clipboard.setter
    def restore_clipboard(self, value: bool) -> None:
        self._restore_clipboard = value

    def inject_text(self, text: str) -> None:
        if not text.strip():
            logger.info("Empty text, skipping injection")
            return

        old_clipboard = self._get_clipboard() if self._restore_clipboard else None

        self._set_clipboard(text)
        time.sleep(0.05)
        _send_ctrl_v()

        logger.info("Injected text: %s", text[:80])

        if self._restore_clipboard and old_clipboard is not None:
            threading.Timer(0.5, self._set_clipboard, args=(old_clipboard,)).start()

    def _get_clipboard(self) -> str | None:
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

    def _set_clipboard(self, text: str) -> None:
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
