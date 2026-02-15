"""macOS autostart management via launchd plist."""

import logging
import os
import plistlib
import sys

logger = logging.getLogger(__name__)

APP_NAME = "MoSheng"
PLIST_LABEL = "com.mosheng.app"
PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{PLIST_LABEL}.plist")


def _get_executable_command() -> list[str]:
    """Detect runtime environment and return the correct startup command."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    else:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        main_py = os.path.join(app_dir, "main.py")
        return [sys.executable, main_py]


def is_autostart_enabled() -> bool:
    """Check if the launchd plist exists."""
    return os.path.isfile(PLIST_PATH)


def set_autostart(enabled: bool) -> bool:
    """Create or remove the launchd plist. Returns True on success."""
    try:
        if enabled:
            cmd = _get_executable_command()
            plist = {
                "Label": PLIST_LABEL,
                "ProgramArguments": cmd,
                "RunAtLoad": True,
                "KeepAlive": False,
            }
            os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)
            with open(PLIST_PATH, "wb") as f:
                plistlib.dump(plist, f)
            logger.info("Autostart enabled: %s", PLIST_PATH)
        else:
            if os.path.isfile(PLIST_PATH):
                os.remove(PLIST_PATH)
                logger.info("Autostart disabled")
        return True
    except OSError:
        logger.exception("Failed to update autostart plist")
        return False
