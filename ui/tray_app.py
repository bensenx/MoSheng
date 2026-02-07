"""System tray application - coordinates all components."""

import logging
import queue
import threading
import winsound

import ttkbootstrap as ttk
from PIL import Image, ImageDraw
import pystray

from settings_manager import SettingsManager
from core.asr_base import ASRBase
from core.audio_recorder import AudioRecorder
from core.text_injector import TextInjector
from core.hotkey_manager import HotkeyManager
from ui.overlay_window import (
    OverlayWindow, STATE_RECORDING, STATE_RECOGNIZING,
    STATE_RESULT, STATE_ERROR,
)

logger = logging.getLogger(__name__)

CMD_START = "start"
CMD_STOP = "stop"
CMD_QUIT = "quit"


class TrayApp:
    def __init__(self, asr_engine: ASRBase, settings: SettingsManager):
        self._asr = asr_engine
        self._settings = settings
        self._cmd_queue: queue.Queue[str] = queue.Queue()

        # Components
        sr = settings.get("audio", "sample_rate", default=16000)
        input_dev = settings.get("audio", "input_device", default=None)
        self._recorder = AudioRecorder(sample_rate=sr, device=input_dev)
        self._injector = TextInjector(
            restore_clipboard=settings.get("output", "restore_clipboard", default=True)
        )
        self._overlay = OverlayWindow(
            enabled=settings.get("output", "overlay_enabled", default=True)
        )

        hotkey_keys = settings.get("hotkey", "keys", default=["ctrl", "left windows"])
        hotkey_mode = settings.get("mode", default="push_to_talk")
        self._hotkey = HotkeyManager(
            hotkey_keys=hotkey_keys,
            on_start=self._on_hotkey_start,
            on_stop=self._on_hotkey_stop,
            mode=hotkey_mode,
        )

        self._sound_enabled = settings.get("output", "sound_enabled", default=True)
        self._min_duration = settings.get("audio", "min_duration", default=0.3)

        self._icon: pystray.Icon | None = None
        self._tk_root: ttk.Window | None = None

    def run(self) -> None:
        """Start the application. Blocks in tk mainloop on the main thread."""
        # --- tkinter on main thread ---
        self._tk_root = ttk.Window(themename="darkly")
        self._tk_root.title("VoiceInput")
        self._tk_root.withdraw()

        # Overlay is a Toplevel child of the main window
        self._overlay.create(self._tk_root)

        # --- background threads ---
        self._hotkey.start()

        worker = threading.Thread(target=self._worker_loop, daemon=True)
        worker.start()

        tray_thread = threading.Thread(target=self._run_tray, daemon=True)
        tray_thread.start()

        logger.info("VoiceInput ready. Hotkey: %s",
                     self._settings.get("hotkey", "display"))

        # Block in tk mainloop (main thread)
        self._tk_root.mainloop()

    # ---- tray (background thread) ----

    def _run_tray(self) -> None:
        icon_image = self._create_icon_image("#6c7086")
        self._icon = pystray.Icon(
            "VoiceInput",
            icon=icon_image,
            title="VoiceInput - 就绪",
            menu=pystray.Menu(
                pystray.MenuItem("设置", self._open_settings),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._quit),
            ),
        )
        self._icon.run()

    def _create_icon_image(self, color: str) -> Image.Image:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 56, 56], fill=color)
        draw.rounded_rectangle([24, 16, 40, 38], radius=6, fill="white")
        draw.arc([20, 28, 44, 48], start=0, end=180, fill="white", width=2)
        draw.line([32, 48, 32, 54], fill="white", width=2)
        draw.line([26, 54, 38, 54], fill="white", width=2)
        return img

    # ---- hotkey callbacks (keyboard thread) ----

    def _on_hotkey_start(self) -> None:
        self._cmd_queue.put(CMD_START)

    def _on_hotkey_stop(self) -> None:
        self._cmd_queue.put(CMD_STOP)

    # ---- worker thread ----

    def _worker_loop(self) -> None:
        while True:
            cmd = self._cmd_queue.get()
            if cmd == CMD_QUIT:
                break
            elif cmd == CMD_START:
                self._handle_start()
            elif cmd == CMD_STOP:
                self._handle_stop()

    def _handle_start(self) -> None:
        self._recorder.start_recording()
        self._overlay.set_state(STATE_RECORDING)
        self._set_tray_icon("#f38ba8", "VoiceInput - 录音中")
        if self._sound_enabled:
            threading.Thread(
                target=lambda: winsound.Beep(800, 100), daemon=True
            ).start()

    def _handle_stop(self) -> None:
        audio = self._recorder.stop_recording()
        if self._sound_enabled:
            threading.Thread(
                target=lambda: winsound.Beep(600, 100), daemon=True
            ).start()

        if audio is None or len(audio) / self._recorder.sample_rate < self._min_duration:
            self._overlay.set_state(STATE_ERROR, "录音太短")
            self._set_tray_icon("#6c7086", "VoiceInput - 就绪")
            return

        self._overlay.set_state(STATE_RECOGNIZING)
        self._set_tray_icon("#f9e2af", "VoiceInput - 识别中")

        try:
            text = self._asr.transcribe(audio, self._recorder.sample_rate)
            if text.strip():
                self._injector.inject_text(text)
                self._overlay.set_state(STATE_RESULT, text)
            else:
                self._overlay.set_state(STATE_ERROR, "未识别到内容")
        except Exception:
            logger.exception("Transcription failed")
            self._overlay.set_state(STATE_ERROR, "识别失败")

        self._set_tray_icon("#6c7086", "VoiceInput - 就绪")

    def _set_tray_icon(self, color: str, title: str) -> None:
        if self._icon is not None:
            self._icon.icon = self._create_icon_image(color)
            self._icon.title = title

    # ---- settings (scheduled on main tk thread) ----

    def _open_settings(self, icon=None, item=None) -> None:
        if self._tk_root is None:
            return
        from ui.settings_window import SettingsWindow

        def show():
            win = SettingsWindow(self._settings, on_save=self._apply_settings)
            win.show(self._tk_root)

        self._tk_root.after_idle(show)

    def _apply_settings(self) -> None:
        new_keys = self._settings.get("hotkey", "keys", default=["ctrl", "left windows"])
        self._hotkey.update_hotkey(new_keys)

        new_mode = self._settings.get("mode", default="push_to_talk")
        self._hotkey.update_mode(new_mode)

        self._injector.restore_clipboard = self._settings.get(
            "output", "restore_clipboard", default=True
        )
        self._sound_enabled = self._settings.get("output", "sound_enabled", default=True)
        self._overlay.enabled = self._settings.get(
            "output", "overlay_enabled", default=True
        )
        self._recorder.device = self._settings.get(
            "audio", "input_device", default=None
        )
        logger.info("Settings applied")

    # ---- shutdown ----

    def _quit(self, icon=None, item=None) -> None:
        logger.info("Shutting down...")
        self._cmd_queue.put(CMD_QUIT)
        self._hotkey.stop()
        self._overlay.destroy()
        if self._icon:
            self._icon.stop()
        if self._tk_root:
            self._tk_root.after_idle(self._tk_root.destroy)
