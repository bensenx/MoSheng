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

# All modifier VK codes (generic + sided variants).
_ALL_MODIFIER_VKS = (
    0x10, 0xA0, 0xA1,  # Shift, Left Shift, Right Shift
    0x11, 0xA2, 0xA3,  # Ctrl, Left Ctrl, Right Ctrl
    0x12, 0xA4, 0xA5,  # Alt, Left Alt, Right Alt
    0x5B, 0x5C,         # Left Win, Right Win
)


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


def _send_ctrl_v(hotkey_vks: frozenset[int] = frozenset()):
    """Send Ctrl+V paste with clean modifier state.

    Hotkey keys are suppressed at the hook level, so the OS doesn't think
    they're pressed.  We only need to release non-hotkey modifiers that
    the user might be holding (e.g. Shift while using a Ctrl-only hotkey).
    """
    inputs: list[INPUT] = []

    # Release any non-hotkey modifiers that might be held
    for vk in _ALL_MODIFIER_VKS:
        if vk in hotkey_vks:
            continue  # Suppressed at hook level; OS doesn't see it
        if vk == VK_CONTROL:
            continue  # We press Ctrl ourselves for the paste
        if ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000:
            inputs.append(_make_key_input(vk, KEYEVENTF_KEYUP))

    # Clean Ctrl+V
    inputs.extend([
        _make_key_input(VK_CONTROL),
        _make_key_input(VK_V),
        _make_key_input(VK_V, KEYEVENTF_KEYUP),
        _make_key_input(VK_CONTROL, KEYEVENTF_KEYUP),
    ])
    _send_inputs(*inputs)


# ---- TextInjector ----

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
        """Save current clipboard content for later restoration."""
        self._saved_clipboard = self._get_clipboard()

    def restore_saved_clipboard(self) -> None:
        """Restore previously saved clipboard content."""
        if self._saved_clipboard is not None:
            threading.Timer(0.3, self._set_clipboard, args=(self._saved_clipboard,)).start()
            self._saved_clipboard = None

    def inject_text_no_restore(self, text: str) -> None:
        """Inject text via clipboard+paste without saving/restoring clipboard."""
        if not text.strip():
            logger.info("Empty text, skipping injection")
            return
        self._set_clipboard(text)
        time.sleep(0.05)
        _send_ctrl_v(self._hotkey_vks)
        logger.info("Injected text (no restore): %s", text[:80])

    def inject_text(self, text: str) -> None:
        if not text.strip():
            logger.info("Empty text, skipping injection")
            return

        old_clipboard = self._get_clipboard() if self._restore_clipboard else None

        self._set_clipboard(text)
        time.sleep(0.05)
        _send_ctrl_v(self._hotkey_vks)

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
