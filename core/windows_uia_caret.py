"""Read only the active text insertion point via Windows UI Automation."""

import ctypes as c
from _ctypes import COMError
import math
from contextlib import contextmanager
from uuid import UUID

import pythoncom


def _guid(value):
    return (c.c_byte * 16).from_buffer_copy(UUID(value).bytes_le)


_automation8 = _guid("e22ad333-b25f-460c-83d0-0581107395c9")
_automation2 = _guid("34723aff-0c9d-49d0-9896-7ab52df8cd8a")
_text_pattern2 = _guid("506a921a-fcc9-409f-b23b-37eb74106872")
_text_pattern = _guid("32eba289-3583-42c9-9c59-3b6d9a1e9b6a")
_ptr = c.c_void_p
_out = c.POINTER(_ptr)
_ole = c.OleDLL("ole32")
_ole.CoCreateInstance.argtypes = [_ptr, _ptr, c.c_ulong, _ptr, _out]
_arrays = c.OleDLL("oleaut32")
_arrays.SafeArrayGetLBound.argtypes = [_ptr, c.c_uint, c.POINTER(c.c_long)]
_arrays.SafeArrayGetUBound.argtypes = _arrays.SafeArrayGetLBound.argtypes
_arrays.SafeArrayAccessData.argtypes = [_ptr, _out]
_arrays.SafeArrayUnaccessData.argtypes = [_ptr]
_arrays.SafeArrayDestroy.argtypes = [_ptr]


def _method(slot, name, *arguments):
    # Slots are from the public UIAutomationClient.h interfaces (IUnknown at 0..2).
    return c.WINFUNCTYPE(c.HRESULT, *arguments)(slot, name)


_release = c.WINFUNCTYPE(c.c_ulong)(2, "Release")
_focus = _method(8, "GetFocusedElement", _out)
_pattern = _method(14, "GetCurrentPatternAs", c.c_int, _ptr, _out)
_caret = _method(10, "GetCaretRange", c.POINTER(c.c_int), _out)
_selection = _method(5, "GetSelection", _out)
_length = _method(3, "get_Length", c.POINTER(c.c_int))
_element_at = _method(4, "GetElement", c.c_int, _out)
_compare_ends = _method(5, "CompareEndpoints", c.c_int, _ptr, c.c_int, c.POINTER(c.c_int))
_bounds = _method(10, "GetBoundingRectangles", _out)
_move_end = _method(14, "MoveEndpointByUnit", c.c_int, c.c_int, c.c_int, c.POINTER(c.c_int))
_connection_timeout = _method(61, "put_ConnectionTimeout", c.c_uint)
_transaction_timeout = _method(63, "put_TransactionTimeout", c.c_uint)


@contextmanager
def _interface():
    pointer = _ptr()
    try:
        yield pointer
    finally:
        if pointer:
            _release(pointer)


def _rectangle(text_range):
    array = _ptr()
    try:
        _bounds(text_range, c.byref(array))
        if not array:
            return None
        first, last = c.c_long(), c.c_long()
        _arrays.SafeArrayGetLBound(array, 1, c.byref(first))
        _arrays.SafeArrayGetUBound(array, 1, c.byref(last))
        if last.value - first.value != 3:
            return None
        data = _ptr()
        _arrays.SafeArrayAccessData(array, c.byref(data))
        try:
            rect = tuple((c.c_double * 4).from_address(data.value))
            if all(map(math.isfinite, rect)) and rect[2] >= 0 and rect[3] > 0:
                return rect
        finally:
            _arrays.SafeArrayUnaccessData(array)
    finally:
        if array:
            _arrays.SafeArrayDestroy(array)


class AutomationCaret:
    """One lazy COM client per watcher thread, with bounded provider timeouts."""

    def __init__(self):
        self._client = _ptr()
        self._attempted = False

    def __enter__(self):
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        return self

    def __exit__(self, *exc):
        if self._client:
            _release(self._client)
        pythoncom.CoUninitialize()

    @staticmethod
    def _active_range(element, text_range):
        with _interface() as pattern:
            try:
                _pattern(element, 10024, _text_pattern2, c.byref(pattern))  # UIA_TextPattern2Id
            except (OSError, COMError):
                pass
            if pattern:
                active = c.c_int()
                _caret(pattern, c.byref(active), c.byref(text_range))
                return active.value and text_range
        # Older providers expose only TextPattern. Use a single collapsed
        # selection, never a selected passage as an inferred insertion point.
        with _interface() as pattern, _interface() as ranges:
            _pattern(element, 10014, _text_pattern, c.byref(pattern))  # UIA_TextPatternId
            if not pattern:
                return False
            _selection(pattern, c.byref(ranges))
            count = c.c_int()
            if not ranges:
                return False
            _length(ranges, c.byref(count))
            if count.value != 1:
                return False
            _element_at(ranges, 0, c.byref(text_range))
            if not text_range:
                return False
            distance = c.c_int()
            _compare_ends(text_range, 0, text_range, 1, c.byref(distance))
            return distance.value == 0

    def point(self):
        try:
            if not self._attempted:
                self._attempted = True
                _ole.CoCreateInstance(_automation8, None, 1, _automation2, c.byref(self._client))
                _connection_timeout(self._client, 200)
                _transaction_timeout(self._client, 200)
            if not self._client:
                return None
            with _interface() as element, _interface() as text_range:
                _focus(self._client, c.byref(element))
                if not element or not self._active_range(element, text_range):
                    return None
                rect = _rectangle(text_range)
                if rect:
                    return round(rect[0]), round(rect[1] + rect[3]), max(1, round(rect[3]))
                # Some providers only return bounds for a nonempty range. Extend
                # the private range one character without changing the selection.
                moved = c.c_int()
                for endpoint, direction in ((1, 1), (0, -1)):
                    _move_end(text_range, endpoint, 0, direction, c.byref(moved))
                    if moved.value:
                        rect = _rectangle(text_range)
                        if rect:
                            x, y, width, height = rect
                            return round(x if direction > 0 else x + width), round(y + height), max(1, round(height))
                        break
        except (OSError, COMError):
            pass  # Unsupported, stale, or unresponsive provider.
        return None
