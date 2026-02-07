"""Floating overlay window for recording/recognition status display."""

import ctypes
import logging
import tkinter as tk

logger = logging.getLogger(__name__)

# States
STATE_IDLE = "idle"
STATE_RECORDING = "recording"
STATE_RECOGNIZING = "recognizing"
STATE_RESULT = "result"
STATE_ERROR = "error"


class OverlayWindow:
    """Transparent, topmost, click-through status overlay at bottom-right.

    Must be created on the main tkinter thread. Call `create(root)` after
    the root window exists, then `set_state()` from any thread.
    """

    WIDTH = 280
    HEIGHT = 50
    MARGIN = 20
    RESULT_DISPLAY_MS = 2000

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._win: tk.Toplevel | None = None
        self._root: tk.Tk | None = None
        self._label: tk.Label | None = None
        self._anim_id: str | None = None
        self._anim_step = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        if not value and self._win is not None:
            try:
                self._root.after_idle(self._win.withdraw)
            except Exception:
                pass

    def create(self, root: tk.Tk) -> None:
        """Build the overlay as a Toplevel of the given root. Call on main thread."""
        if not self._enabled:
            return
        self._root = root
        self._win = tk.Toplevel(root)
        self._win.withdraw()
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", 0.85)

        screen_w = self._win.winfo_screenwidth()
        screen_h = self._win.winfo_screenheight()
        x = screen_w - self.WIDTH - self.MARGIN
        y = screen_h - self.HEIGHT - self.MARGIN - 40
        self._win.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")
        self._win.configure(bg="#1e1e2e")

        self._label = tk.Label(
            self._win,
            text="",
            font=("Segoe UI", 12),
            fg="#cdd6f4",
            bg="#1e1e2e",
            anchor="center",
        )
        self._label.pack(expand=True, fill="both", padx=10, pady=5)

        self._set_click_through()

    def _set_click_through(self) -> None:
        try:
            hwnd = ctypes.windll.user32.GetParent(self._win.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, -20, style | 0x80000 | 0x20 | 0x80
            )
        except Exception:
            logger.debug("Could not set click-through")

    def set_state(self, state: str, text: str = "") -> None:
        """Thread-safe: schedules UI update on the tkinter main thread."""
        if not self._enabled or self._root is None:
            return
        try:
            self._root.after_idle(self._update_display, state, text)
        except Exception:
            pass

    def _update_display(self, state: str, text: str) -> None:
        if self._anim_id is not None:
            self._root.after_cancel(self._anim_id)
            self._anim_id = None

        if state == STATE_IDLE:
            self._win.withdraw()
            return

        self._win.deiconify()

        if state == STATE_RECORDING:
            self._label.configure(fg="#f38ba8")
            self._anim_step = 0
            self._animate_recording()
        elif state == STATE_RECOGNIZING:
            self._label.configure(text="识别中...", fg="#f9e2af")
        elif state == STATE_RESULT:
            display = text if len(text) <= 30 else text[:28] + "..."
            self._label.configure(text=display, fg="#a6e3a1")
            self._root.after(self.RESULT_DISPLAY_MS, self._hide)
        elif state == STATE_ERROR:
            display = text if len(text) <= 30 else text[:28] + "..."
            self._label.configure(text=display, fg="#f38ba8")
            self._root.after(self.RESULT_DISPLAY_MS, self._hide)

    def _animate_recording(self) -> None:
        dots = "\u25cf" * ((self._anim_step % 3) + 1)
        self._label.configure(text=f"录音中 {dots}")
        self._anim_step += 1
        self._anim_id = self._root.after(400, self._animate_recording)

    def _hide(self) -> None:
        if self._win:
            self._win.withdraw()

    def destroy(self) -> None:
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None
        self._root = None
