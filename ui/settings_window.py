"""Settings window with ttkbootstrap modern UI."""

import logging
import tkinter as tk
from typing import Callable

import keyboard
import ttkbootstrap as ttk
from ttkbootstrap.constants import *

from settings_manager import SettingsManager

logger = logging.getLogger(__name__)


class SettingsWindow:
    def __init__(self, settings: SettingsManager,
                 on_save: Callable | None = None):
        self._settings = settings
        self._on_save = on_save
        self._win: ttk.Toplevel | None = None
        self._capturing_hotkey = False
        self._captured_keys: set[str] = set()
        self._hotkey_hook = None

        # Tk variables (created when window opens)
        self._hotkey_display = None
        self._hotkey_keys: list[str] = []
        self._sound_var = None
        self._overlay_var = None
        self._restore_var = None
        self._device_var = None
        self._mode_var = None
        self._input_device_var = None
        self._input_devices: list[tuple[int | None, str]] = []  # (id, display_name)

    def show(self, parent: tk.Tk | None = None) -> None:
        if self._win is not None:
            try:
                self._win.lift()
                self._win.focus_force()
                return
            except Exception:
                self._win = None

        self._win = ttk.Toplevel(master=parent, title="VoiceInput 设置")
        self._win.resizable(False, False)
        self._win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        try:
            self._build_ui()
        except Exception:
            logger.exception("Failed to build settings UI")

        # Center on screen after content determines size
        self._win.update_idletasks()
        w = self._win.winfo_reqwidth()
        h = self._win.winfo_reqheight()
        sw = self._win.winfo_screenwidth()
        sh = self._win.winfo_screenheight()
        self._win.geometry(f"{max(w, 420)}x{h}+{(sw - max(w, 420)) // 2}+{(sh - h) // 2}")

    def _build_ui(self) -> None:
        s = self._settings
        main = ttk.Frame(self._win, padding=20)
        main.pack(fill=BOTH, expand=YES)

        # --- Hotkey Section ---
        hk_frame = ttk.LabelFrame(main, text="快捷键设置")
        hk_frame.pack(fill=X, pady=(0, 12))

        row1 = ttk.Frame(hk_frame)
        row1.pack(fill=X, padx=10, pady=(10, 5))
        ttk.Label(row1, text="录音快捷键:").pack(side=LEFT)

        self._hotkey_keys = list(s.get("hotkey", "keys", default=["ctrl", "left windows"]))
        self._hotkey_display = tk.StringVar(
            value=s.get("hotkey", "display", default="Ctrl + Win")
        )
        ttk.Entry(row1, textvariable=self._hotkey_display, state="readonly",
                  width=18).pack(side=LEFT, padx=(8, 8))

        self._bind_btn = ttk.Button(
            row1, text="修改绑定", bootstyle=OUTLINE,
            command=self._start_hotkey_capture
        )
        self._bind_btn.pack(side=LEFT)

        row2 = ttk.Frame(hk_frame)
        row2.pack(fill=X, padx=10, pady=(0, 10))
        ttk.Label(row2, text="模式:").pack(side=LEFT)
        self._mode_var = tk.StringVar(
            value=s.get("mode", default="push_to_talk")
        )
        ttk.Radiobutton(row2, text="按住录音", variable=self._mode_var,
                        value="push_to_talk", bootstyle="info"
                        ).pack(side=LEFT, padx=(8, 0))
        ttk.Radiobutton(row2, text="按键切换", variable=self._mode_var,
                        value="toggle", bootstyle="info"
                        ).pack(side=LEFT, padx=(8, 0))

        # --- ASR Section ---
        asr_frame = ttk.LabelFrame(main, text="语音识别")
        asr_frame.pack(fill=X, pady=(0, 12))

        row3 = ttk.Frame(asr_frame)
        row3.pack(fill=X, padx=10, pady=(10, 5))
        ttk.Label(row3, text="ASR 模型:").pack(side=LEFT)
        model_combo = ttk.Combobox(row3, values=["Qwen3-ASR-1.7B"],
                                   state="readonly", width=20)
        model_combo.set("Qwen3-ASR-1.7B")
        model_combo.pack(side=LEFT, padx=(8, 0))

        row4 = ttk.Frame(asr_frame)
        row4.pack(fill=X, padx=10, pady=(0, 10))
        ttk.Label(row4, text="设备:").pack(side=LEFT)
        devices = self._get_cuda_devices()
        self._device_var = tk.StringVar(
            value=s.get("asr", "device", default="cuda:0")
        )
        device_combo = ttk.Combobox(row4, textvariable=self._device_var,
                                    values=devices, state="readonly", width=20)
        device_combo.pack(side=LEFT, padx=(8, 0))

        # --- Audio Input Section ---
        mic_frame = ttk.LabelFrame(main, text="音频输入")
        mic_frame.pack(fill=X, pady=(0, 12))

        row_mic = ttk.Frame(mic_frame)
        row_mic.pack(fill=X, padx=10, pady=(10, 10))
        ttk.Label(row_mic, text="麦克风:").pack(side=LEFT)
        self._input_devices = self._get_input_devices()
        display_names = [name for _, name in self._input_devices]
        saved_dev = s.get("audio", "input_device", default=None)
        current_display = "系统默认"
        for dev_id, name in self._input_devices:
            if dev_id == saved_dev:
                current_display = name
                break
        self._input_device_var = tk.StringVar(value=current_display)
        mic_combo = ttk.Combobox(row_mic, textvariable=self._input_device_var,
                                 values=display_names, state="readonly", width=30)
        mic_combo.pack(side=LEFT, padx=(8, 0))

        # --- Output Section ---
        out_frame = ttk.LabelFrame(main, text="输出设置")
        out_frame.pack(fill=X, pady=(0, 20))

        self._sound_var = tk.BooleanVar(
            value=s.get("output", "sound_enabled", default=True)
        )
        ttk.Checkbutton(out_frame, text="录音开始/结束提示音",
                        variable=self._sound_var, bootstyle="round-toggle"
                        ).pack(anchor=W, padx=10, pady=2)

        self._overlay_var = tk.BooleanVar(
            value=s.get("output", "overlay_enabled", default=True)
        )
        ttk.Checkbutton(out_frame, text="显示悬浮状态窗口",
                        variable=self._overlay_var, bootstyle="round-toggle"
                        ).pack(anchor=W, padx=10, pady=2)

        self._restore_var = tk.BooleanVar(
            value=s.get("output", "restore_clipboard", default=True)
        )
        ttk.Checkbutton(out_frame, text="粘贴后恢复剪贴板",
                        variable=self._restore_var, bootstyle="round-toggle"
                        ).pack(anchor=W, padx=10, pady=(2, 10))

        # --- Buttons ---
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=X)

        ttk.Button(btn_frame, text="取消", bootstyle=SECONDARY,
                   command=self._on_cancel, width=10).pack(side=RIGHT, padx=(8, 0))
        ttk.Button(btn_frame, text="保存", bootstyle=SUCCESS,
                   command=self._on_save_click, width=10).pack(side=RIGHT)

    def _get_input_devices(self) -> list[tuple[int | None, str]]:
        """Return list of (device_id_or_None, display_name) for input devices."""
        result: list[tuple[int | None, str]] = [(None, "系统默认")]
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            for i, d in enumerate(devices):
                if d["max_input_channels"] > 0 and d["hostapi"] == 0:
                    name = d["name"]
                    if len(name) > 35:
                        name = name[:33] + "…"
                    result.append((i, name))
        except Exception:
            pass
        return result

    def _get_cuda_devices(self) -> list[str]:
        devices = ["cpu"]
        try:
            import torch
            for i in range(torch.cuda.device_count()):
                name = torch.cuda.get_device_name(i)
                devices.append(f"cuda:{i}")
        except Exception:
            pass
        return devices

    def _start_hotkey_capture(self) -> None:
        self._capturing_hotkey = True
        self._captured_keys.clear()
        self._bind_btn.configure(text="请按下快捷键...", bootstyle=DANGER)
        self._hotkey_display.set("等待输入...")
        self._hotkey_hook = keyboard.hook(self._on_capture_key, suppress=False)

    def _on_capture_key(self, event: keyboard.KeyboardEvent) -> None:
        if not self._capturing_hotkey:
            return

        if event.event_type == keyboard.KEY_DOWN:
            self._captured_keys.add(event.name.lower())
            display = " + ".join(
                k.capitalize() if len(k) > 1 else k.upper()
                for k in sorted(self._captured_keys)
            )
            self._win.after_idle(self._hotkey_display.set, display)

        elif event.event_type == keyboard.KEY_UP:
            if self._captured_keys:
                self._capturing_hotkey = False
                keyboard.unhook(self._hotkey_hook)
                self._hotkey_hook = None

                self._hotkey_keys = sorted(self._captured_keys)
                display = " + ".join(
                    k.capitalize() if len(k) > 1 else k.upper()
                    for k in self._hotkey_keys
                )
                self._win.after_idle(self._finish_capture, display)

    def _finish_capture(self, display: str) -> None:
        self._hotkey_display.set(display)
        self._bind_btn.configure(text="修改绑定", bootstyle=OUTLINE)

    def _on_save_click(self) -> None:
        try:
            display = self._hotkey_display.get()
            self._settings.set("hotkey", "keys", self._hotkey_keys)
            self._settings.set("hotkey", "display", display)
            self._settings.set("mode", self._mode_var.get())
            self._settings.set("asr", "device", self._device_var.get())
            # Resolve input device name to device id
            selected_name = self._input_device_var.get()
            input_dev_id = None
            for dev_id, name in self._input_devices:
                if name == selected_name:
                    input_dev_id = dev_id
                    break
            self._settings.set("audio", "input_device", input_dev_id)
            self._settings.set("output", "sound_enabled", self._sound_var.get())
            self._settings.set("output", "overlay_enabled", self._overlay_var.get())
            self._settings.set("output", "restore_clipboard", self._restore_var.get())
            self._settings.save()
            logger.info("Settings saved: mode=%s, hotkey=%s",
                        self._mode_var.get(), self._hotkey_keys)

            if self._on_save:
                self._on_save()
        except Exception:
            logger.exception("Failed to save settings")

        self._close()

    def _on_cancel(self) -> None:
        if self._hotkey_hook is not None:
            keyboard.unhook(self._hotkey_hook)
            self._hotkey_hook = None
        self._close()

    def _close(self) -> None:
        if self._win is not None:
            self._win.destroy()
            self._win = None
