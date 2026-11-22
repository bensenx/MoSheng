"""Cross-platform autostart management for MoSheng.

macOS: launchd plist in ~/Library/LaunchAgents/
Windows: HKCU registry Run key
"""

import logging
import os
import sys

logger = logging.getLogger(__name__)

APP_NAME = "MoSheng"
AUTOSTART_ARG = "--autostart"

if sys.platform == "darwin":
    import plistlib

    PLIST_LABEL = "com.mosheng.app"
    PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{PLIST_LABEL}.plist")

    def _get_executable_command() -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable]
        else:
            app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            main_py = os.path.join(app_dir, "main.py")
            return [sys.executable, main_py]

    def is_autostart_enabled() -> bool:
        return os.path.isfile(PLIST_PATH)

    def set_autostart(enabled: bool) -> bool:
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

elif sys.platform == "win32":
    import re
    import winreg

    REGISTRY_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"

    def _get_executable_command() -> str:
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" {AUTOSTART_ARG}'
        else:
            app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            pythonw = os.path.join(sys.prefix, "Scripts", "pythonw.exe")
            main_py = os.path.join(app_dir, "main.py")
            return f'"{pythonw}" "{main_py}" {AUTOSTART_ARG}'

    def refresh_autostart_command() -> None:
        """Upgrade an existing MoSheng Run entry, including after extracting an update."""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0,
                                winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
                value, kind = winreg.QueryValueEx(key, APP_NAME)
                command = _get_executable_command()
                if kind != winreg.REG_SZ or value == command:
                    return
                same_install = value.casefold() == command.removesuffix(" " + AUTOSTART_ARG).casefold()
                packaged = os.path.isfile(os.path.join(os.path.dirname(__file__), "..", "MoSheng.exe"))
                previous_install = re.fullmatch(
                    r'(?:"[^"]+\\pythonw\.exe" "[^"]+\\main\.py"|"[^"]+\\MoSheng\.exe")(?: --autostart)?',
                    value, re.IGNORECASE)
                if same_install or (packaged and previous_install):
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
        except FileNotFoundError:
            pass  # Disabled autostart stays disabled.
        except OSError:
            logger.warning("Could not refresh the Windows startup entry", exc_info=True)

    def is_autostart_enabled() -> bool:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_READ
            ) as key:
                winreg.QueryValueEx(key, APP_NAME)
                return True
        except (FileNotFoundError, OSError):
            return False

    def set_autostart(enabled: bool) -> bool:
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

else:
    def is_autostart_enabled() -> bool:
        return False

    def set_autostart(enabled: bool) -> bool:
        logger.warning("Autostart not supported on %s", sys.platform)
        return False
