"""Low-level keyboard hook for selective key suppression.

Installs a WH_KEYBOARD_LL hook via ctypes that can suppress specific
physical key events while passing through injected (SendInput) events.
This is the same technique AutoHotkey uses to prevent Win key side effects.
"""

import ctypes
import ctypes.wintypes
import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Windows constants
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x00000010
LLKHF_LOWER_IL_INJECTED = 0x00000002
HC_ACTION = 0


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


# HOOKPROC signature: LRESULT CALLBACK (int nCode, WPARAM wParam, LPARAM lParam)
HOOKPROC = ctypes.CFUNCTYPE(
    ctypes.c_long,       # LRESULT return
    ctypes.c_int,        # nCode
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)

# Callback type for the user-facing API.
# (vk_code: int, scan_code: int, is_key_down: bool, is_injected: bool) -> bool
# Returns True to suppress the event, False to pass through.
KeyEventCallback = Callable[[int, int, bool, bool], bool]


class KeySuppressionHook:
    """Manages a WH_KEYBOARD_LL hook on a dedicated thread."""

    def __init__(self, callback: KeyEventCallback):
        self._callback = callback
        self._hook_handle = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._thread_id: int | None = None
        # prevent GC of the C callback
        self._c_callback: HOOKPROC | None = None

    def start(self) -> None:
        """Install the hook on a background thread."""
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="KeySuppressionHook",
        )
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def stop(self) -> None:
        """Remove the hook and stop the message pump."""
        if self._thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(
                self._thread_id, WM_QUIT, 0, 0,
            )
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._thread_id = None

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        # Proper type declarations for 64-bit handle safety
        kernel32.GetModuleHandleW.argtypes = [ctypes.wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = ctypes.wintypes.HMODULE

        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, HOOKPROC, ctypes.wintypes.HINSTANCE, ctypes.wintypes.DWORD,
        ]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p

        user32.CallNextHookEx.argtypes = [
            ctypes.c_void_p, ctypes.c_int,
            ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
        ]
        user32.CallNextHookEx.restype = ctypes.c_long

        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.UnhookWindowsHookEx.restype = ctypes.wintypes.BOOL

        self._thread_id = kernel32.GetCurrentThreadId()

        def hook_proc(nCode: int, wParam: int, lParam: int) -> int:
            if nCode == HC_ACTION:
                kbd = ctypes.cast(
                    lParam, ctypes.POINTER(KBDLLHOOKSTRUCT),
                ).contents
                is_injected = bool(
                    kbd.flags & (LLKHF_INJECTED | LLKHF_LOWER_IL_INJECTED)
                )
                is_key_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)

                try:
                    suppress = self._callback(
                        kbd.vkCode, kbd.scanCode, is_key_down, is_injected,
                    )
                except Exception:
                    logger.exception("Error in key suppression callback")
                    suppress = False

                if suppress:
                    return 1  # block event, do NOT call CallNextHookEx

            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        self._c_callback = HOOKPROC(hook_proc)
        h_module = kernel32.GetModuleHandleW(None)

        self._hook_handle = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._c_callback, h_module, 0,
        )
        if not self._hook_handle:
            err = ctypes.get_last_error()
            logger.error("Failed to install keyboard hook (error %d)", err)
            self._ready.set()
            return

        logger.info("Key suppression hook installed")
        self._ready.set()

        # Message pump — required for WH_KEYBOARD_LL to receive events.
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # Cleanup
        if self._hook_handle:
            user32.UnhookWindowsHookEx(self._hook_handle)
            self._hook_handle = None
        logger.info("Key suppression hook removed")
