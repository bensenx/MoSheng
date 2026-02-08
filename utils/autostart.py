"""Windows autostart (registry-based) management for MoSheng."""

import logging
import os
import sys
import winreg

logger = logging.getLogger(__name__)

REGISTRY_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "MoSheng"


def _get_executable_command() -> str:
    """Detect runtime environment and return the correct startup command."""
    if getattr(sys, "frozen", False):
        # PyInstaller packaged mode → MoSheng.exe
        return f'"{sys.executable}"'
    else:
        # Dev mode → pythonw.exe main.py
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pythonw = os.path.join(sys.prefix, "Scripts", "pythonw.exe")
        main_py = os.path.join(app_dir, "main.py")
        return f'"{pythonw}" "{main_py}"'


def is_autostart_enabled() -> bool:
    """Check Windows registry for existing autostart entry."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_READ
        ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    """Write or remove the autostart registry entry. Returns True on success."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                cmd = _get_executable_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                logger.info("Autostart enabled: %s", cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    logger.info("Autostart disabled")
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        logger.exception("Failed to update autostart registry")
        return False
