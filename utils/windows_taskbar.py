"""Shell identity for MoSheng windows hosted by pythonw.exe."""

import logging
from pathlib import Path
import subprocess
import sys

import pythoncom
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QPlatformSurfaceEvent
from win32com.propsys import propsys, pscon
from win32com.shell import shell

APP_ID = "MoSheng.VoiceInput"
logger = logging.getLogger(__name__)


def set_process_identity() -> None:
    try:
        shell.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except pythoncom.com_error:
        logger.exception("Could not set the MoSheng taskbar identity")


class TaskbarWindow(QObject):
    """Publish pin metadata before showing the HWND and release it before destruction."""

    def __init__(self, window, app_dir: Path):
        super().__init__(window)
        launcher = app_dir / "MoSheng.exe"
        if launcher.is_file():
            command = [launcher]
            icon = f"{launcher},0"  # First icon group embedded by PyInstaller.
        else:
            command = [Path(sys.executable).with_name("pythonw.exe"), app_dir / "main.py"]
            icon = str(app_dir / "assets" / "icon.ico") + ",0"
        # Windows reads the relaunch properties when the AppUserModelID is assigned.
        self.properties = (
            (pscon.PKEY_AppUserModel_RelaunchCommand, subprocess.list2cmdline(command)),
            (pscon.PKEY_AppUserModel_RelaunchDisplayNameResource, "MoSheng"),
            (pscon.PKEY_AppUserModel_RelaunchIconResource, icon),
            (pscon.PKEY_AppUserModel_ID, APP_ID),
        )
        self._write(window, clear=False)
        window.installEventFilter(self)

    def _write(self, window, *, clear: bool) -> None:
        try:
            store = propsys.SHGetPropertyStoreForWindow(int(window.winId()), propsys.IID_IPropertyStore)
            for key, value in self.properties:
                prop = (propsys.PROPVARIANTType(None, pythoncom.VT_EMPTY) if clear else
                        propsys.PROPVARIANTType(value, pythoncom.VT_LPWSTR))
                store.SetValue(key, prop)
        except pythoncom.com_error:
            logger.exception("Could not update MoSheng taskbar properties")

    def eventFilter(self, window, event):
        if event.type() == QEvent.Type.PlatformSurface:
            closing = event.surfaceEventType() == QPlatformSurfaceEvent.SurfaceEventType.SurfaceAboutToBeDestroyed
            self._write(window, clear=closing)
        return False
