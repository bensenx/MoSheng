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
    screen: str
    # Physical-pixel offsets from this monitor's origin. None means no native caret.
    caret: tuple[int, int] | None


def _caret_point(info: GUIThreadInfo) -> tuple[int, int] | None:
    if not info.hwndCaret or info.rcCaret.bottom <= info.rcCaret.top:
        return None
    # rcCaret is expressed in the target window's own DPI context.
    context = user32.GetWindowDpiAwarenessContext(info.hwndCaret)
    previous = user32.SetThreadDpiAwarenessContext(context) if context else None
    if not previous:
        return None
    try:
        xy = win32gui.ClientToScreen(info.hwndCaret, (info.rcCaret.right, info.rcCaret.bottom))
        point = w.POINT(*xy)
        if user32.LogicalToPhysicalPointForPerMonitorDPI(info.hwndCaret, ctypes.byref(point)):
            return point.x, point.y
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


def badge_anchor(info: GUIThreadInfo) -> BadgeAnchor | None:
    try:
        point = _caret_point(info)
        if point is None:
            monitor = win32api.MonitorFromWindow(info.hwndFocus, win32con.MONITOR_DEFAULTTONEAREST)
        else:
            monitor = win32api.MonitorFromPoint(point, win32con.MONITOR_DEFAULTTONEAREST)
        display = win32api.GetMonitorInfo(monitor)
        left, top, right, bottom = display["Monitor"]
        offset = None
        if point and left <= point[0] < right and top <= point[1] < bottom:
            offset = point[0] - left, point[1] - top
        return BadgeAnchor(display["Device"], offset)
    except pywintypes.error:
        return None
