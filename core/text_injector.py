"""Text injection via clipboard + Cmd+V (macOS)."""

import logging
import subprocess
import threading
import time

logger = logging.getLogger(__name__)


def _send_cmd_v():
    """Simulate Cmd+V keystroke using Quartz CGEvents."""
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventPost,
        CGEventSetFlags,
        kCGHIDEventTap,
        kCGEventFlagMaskCommand,
    )
    # key code 9 = V
    event_down = CGEventCreateKeyboardEvent(None, 9, True)
    CGEventSetFlags(event_down, kCGEventFlagMaskCommand)
    event_up = CGEventCreateKeyboardEvent(None, 9, False)
    CGEventSetFlags(event_up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, event_down)
    CGEventPost(kCGHIDEventTap, event_up)


class TextInjector:
    def __init__(self, restore_clipboard: bool = True):
        self._restore_clipboard = restore_clipboard
        self._saved_clipboard: str | None = None

    @property
    def restore_clipboard(self) -> bool:
        return self._restore_clipboard

    @restore_clipboard.setter
    def restore_clipboard(self, value: bool) -> None:
        self._restore_clipboard = value

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
        _send_cmd_v()
        logger.info("Injected text (no restore): %s", text[:80])

    def inject_text(self, text: str) -> None:
        if not text.strip():
            logger.info("Empty text, skipping injection")
            return

        old_clipboard = self._get_clipboard() if self._restore_clipboard else None

        self._set_clipboard(text)
        time.sleep(0.05)
        _send_cmd_v()

        logger.info("Injected text: %s", text[:80])

        if self._restore_clipboard and old_clipboard is not None:
            threading.Timer(0.5, self._set_clipboard, args=(old_clipboard,)).start()

    def _get_clipboard(self) -> str | None:
        try:
            result = subprocess.run(
                ["pbpaste"], capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                return result.stdout
        except Exception:
            logger.debug("Could not read clipboard")
        return None

    def _set_clipboard(self, text: str) -> None:
        try:
            subprocess.run(
                ["pbcopy"], input=text, text=True, timeout=2, check=True,
            )
        except Exception:
            logger.warning("Failed to set clipboard")
