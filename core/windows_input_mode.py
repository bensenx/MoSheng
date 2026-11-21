"""Read the focused Windows control's keyboard mode without changing its IME."""

import ctypes
from ctypes import wintypes as w
from dataclasses import dataclass

import win32api
import win32con
import win32gui
import win32process
import pywintypes


class GUIThreadInfo(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("flags", w.DWORD),
                ("hwndActive", w.HWND), ("hwndFocus", w.HWND), ("hwndCapture", w.HWND),
                ("hwndMenuOwner", w.HWND), ("hwndMoveSize", w.HWND), ("hwndCaret", w.HWND),
                ("rcCaret", w.RECT)]


user32 = ctypes.WinDLL("user32")
imm32 = ctypes.WinDLL("imm32")
user32.GetCaretBlinkTime.argtypes = []
user32.GetCaretBlinkTime.restype = w.UINT
user32.GetGUIThreadInfo.argtypes = [w.DWORD, ctypes.POINTER(GUIThreadInfo)]
user32.GetGUIThreadInfo.restype = w.BOOL
imm32.ImmGetDefaultIMEWnd.argtypes = [w.HWND]
imm32.ImmGetDefaultIMEWnd.restype = w.HWND
user32.SendMessageTimeoutW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM,
                                       w.UINT, w.UINT, ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
user32.GetWindowDpiAwarenessContext.argtypes = [w.HWND]
user32.GetWindowDpiAwarenessContext.restype = w.HANDLE
user32.SetThreadDpiAwarenessContext.argtypes = [w.HANDLE]
user32.SetThreadDpiAwarenessContext.restype = w.HANDLE
user32.LogicalToPhysicalPointForPerMonitorDPI.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
user32.LogicalToPhysicalPointForPerMonitorDPI.restype = w.BOOL

WM_IME_CONTROL = 0x0283
IMC_GETOPENSTATUS = 0x0005
IMC_GETCONVERSIONMODE = 0x0001
IME_CMODE_NATIVE = 0x0001
SMTO_ERRORONEXIT = 0x0020


def _ime_value(hwnd: int, command: int) -> int | None:
    value = ctypes.c_size_t()
    # A timeout/access denial and a successful zero (English mode) are different.
    ok = user32.SendMessageTimeoutW(hwnd, WM_IME_CONTROL, command, 0,
                                    win32con.SMTO_ABORTIFHUNG | SMTO_ERRORONEXIT, 25, ctypes.byref(value))
    if ok and value.value != ctypes.c_size_t(-1).value:
        return value.value
    return None


def window_mode(focus: int) -> str | None:
    thread, _ = win32process.GetWindowThreadProcessId(focus)
    if not thread:
        return None
    language = win32api.GetKeyboardLayout(thread) & 0x3ff
    if language == 0x09:  # LANG_ENGLISH, including non-US English layouts.
        return "EN"
    if language != 0x04:  # LANG_CHINESE
        return None
    ime = imm32.ImmGetDefaultIMEWnd(focus)
    if not ime:
        return None
    opened = _ime_value(ime, IMC_GETOPENSTATUS)
    if opened is None:
        return None
    if not opened:
        return "EN"
    conversion = _ime_value(ime, IMC_GETCONVERSIONMODE)
    if conversion is None:
        return None
    return "中" if conversion & IME_CMODE_NATIVE else "EN"


@dataclass(frozen=True)
class BadgeAnchor:
    monitor_origin: tuple[int, int]
    # Physical pixels from this monitor's origin, at the foot of the caret.
    caret: tuple[int, int]
    height: int


def _caret_point(info: GUIThreadInfo) -> tuple[int, int, int] | None:
    if not info.hwndCaret or info.rcCaret.bottom <= info.rcCaret.top:
        return None
    # rcCaret is expressed in the target window's own DPI context.
    context = user32.GetWindowDpiAwarenessContext(info.hwndCaret)
    previous = user32.SetThreadDpiAwarenessContext(context) if context else None
    if not previous:
        return None
    try:
        points = []
        for y in (info.rcCaret.top, info.rcCaret.bottom):
            point = w.POINT(*win32gui.ClientToScreen(info.hwndCaret, (info.rcCaret.left, y)))
            if not user32.LogicalToPhysicalPointForPerMonitorDPI(info.hwndCaret, ctypes.byref(point)):
                return None
            points.append(point)
        top, bottom = points
        return bottom.x, bottom.y, max(1, bottom.y - top.y)
    finally:
        user32.SetThreadDpiAwarenessContext(previous)
    return None


def focused_mode() -> tuple[int, str | None, GUIThreadInfo]:
    info = GUIThreadInfo()
    info.cbSize = ctypes.sizeof(info)
    if user32.GetGUIThreadInfo(0, ctypes.byref(info)) and info.hwndFocus:
        try:
            return info.hwndFocus, window_mode(info.hwndFocus), info
        except pywintypes.error:
            pass  # The window can close between queries.
    return 0, None, info


def badge_anchor(info: GUIThreadInfo, automation) -> BadgeAnchor | None:
    try:
        if not info.hwndFocus or info.flags & 0x1e:  # Moving a window or navigating menus.
            return None
        # Reject stale, offscreen and placeholder coordinates from providers.
        left, top, right, bottom = win32gui.GetWindowRect(info.hwndActive)

        def inside(point):
            return point is not None and left <= point[0] < right and top < point[1] <= bottom

        point = _caret_point(info)
        if not inside(point):
            point = automation.point()
        if not inside(point) or win32gui.GetForegroundWindow() != info.hwndActive:
            return None
        monitor = win32api.MonitorFromPoint((point[0], point[1] - 1), win32con.MONITOR_DEFAULTTONULL)
        if not monitor:
            return None
        display = win32api.GetMonitorInfo(monitor)
        left, top, _, _ = display["Monitor"]
        return BadgeAnchor((left, top), (point[0] - left, point[1] - top), point[2])
    except pywintypes.error:
        return None
