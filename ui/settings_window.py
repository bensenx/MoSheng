"""Settings window with glassmorphism dark theme and DWM Mica backdrop."""

import logging
from typing import Callable

import keyboard
from PySide6.QtCore import QMetaObject, Qt, Slot, Q_ARG
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from settings_manager import SettingsManager
from ui.styles import ToggleSwitch, apply_acrylic_effect

logger = logging.getLogger(__name__)


class SettingsWindow(QDialog):
    def __init__(self, settings: SettingsManager,
                 on_save: Callable | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._settings = settings
        self._on_save = on_save
        self._capturing_hotkey = False
        self._captured_keys: set[str] = set()
        self._hotkey_hook = None
        self._hotkey_keys: list[str] = []
        self._input_devices: list[tuple[int | None, str]] = []

        self.setWindowTitle("VoiceInput 设置")
        self.setMinimumWidth(460)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setObjectName("settingsRoot")

        self._build_ui()
        self.adjustSize()
        self._center_on_screen()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Apply DWM Mica backdrop after window has a valid HWND
        hwnd = int(self.winId())
        if not apply_acrylic_effect(hwnd):
            # Fallback: solid dark background
            self.setObjectName("settingsFallback")
            self.style().unpolish(self)
            self.style().polish(self)

    def _center_on_screen(self) -> None:
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(x, y)

    def _build_ui(self) -> None:
        s = self._settings
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # --- Hotkey Section ---
        hk_group = QGroupBox("  \u2328  快捷键设置")
        hk_layout = QVBoxLayout(hk_group)
        hk_layout.setSpacing(12)

        # Row 1: hotkey display + bind button
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("录音快捷键"))

        self._hotkey_keys = list(s.get("hotkey", "keys", default=["ctrl", "left windows"]))
        self._hotkey_edit = QLineEdit(
            s.get("hotkey", "display", default="Ctrl + Win")
        )
        self._hotkey_edit.setReadOnly(True)
        self._hotkey_edit.setFixedWidth(160)
        row1.addWidget(self._hotkey_edit)

        self._bind_btn = QPushButton("修改绑定")
        self._bind_btn.clicked.connect(self._start_hotkey_capture)
        row1.addWidget(self._bind_btn)
        row1.addStretch()
        hk_layout.addLayout(row1)

        # Row 2: recording mode
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("录音模式"))

        self._mode_group = QButtonGroup(self)
        self._push_radio = QRadioButton("按住录音")
        self._toggle_radio = QRadioButton("按键切换")
        self._mode_group.addButton(self._push_radio)
        self._mode_group.addButton(self._toggle_radio)

        current_mode = s.get("mode", default="push_to_talk")
        if current_mode == "toggle":
            self._toggle_radio.setChecked(True)
        else:
            self._push_radio.setChecked(True)

        row2.addWidget(self._push_radio)
        row2.addWidget(self._toggle_radio)
        row2.addStretch()
        hk_layout.addLayout(row2)

        main_layout.addWidget(hk_group)

        # --- ASR Section ---
        asr_group = QGroupBox("  \U0001f9e0  语音识别")
        asr_layout = QVBoxLayout(asr_group)
        asr_layout.setSpacing(12)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("ASR 模型"))
        model_combo = QComboBox()
        model_combo.addItem("Qwen3-ASR-1.7B")
        model_combo.setEnabled(False)
        row3.addWidget(model_combo)
        row3.addStretch()
        asr_layout.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addWidget(QLabel("推理设备"))
        self._device_combo = QComboBox()
        devices = self._get_cuda_devices()
        self._device_combo.addItems(devices)
        current_device = s.get("asr", "device", default="cuda:0")
        idx = self._device_combo.findText(current_device)
        if idx >= 0:
            self._device_combo.setCurrentIndex(idx)
        row4.addWidget(self._device_combo)
        row4.addStretch()
        asr_layout.addLayout(row4)

        main_layout.addWidget(asr_group)

        # --- Audio Input Section ---
        mic_group = QGroupBox("  \U0001f3a4  音频输入")
        mic_layout = QVBoxLayout(mic_group)

        row_mic = QHBoxLayout()
        row_mic.addWidget(QLabel("麦克风"))
        self._mic_combo = QComboBox()
        self._input_devices = self._get_input_devices()
        for _, name in self._input_devices:
            self._mic_combo.addItem(name)
        saved_dev = s.get("audio", "input_device", default=None)
        for i, (dev_id, _) in enumerate(self._input_devices):
            if dev_id == saved_dev:
                self._mic_combo.setCurrentIndex(i)
                break
        self._mic_combo.setMinimumWidth(240)
        row_mic.addWidget(self._mic_combo)
        row_mic.addStretch()
        mic_layout.addLayout(row_mic)

        main_layout.addWidget(mic_group)

        # --- Output Section ---
        out_group = QGroupBox("  \u2699  输出设置")
        out_layout = QVBoxLayout(out_group)
        out_layout.setSpacing(10)

        self._sound_toggle = ToggleSwitch(
            "录音开始/结束提示音",
            checked=s.get("output", "sound_enabled", default=True),
        )
        out_layout.addWidget(self._sound_toggle)

        self._overlay_toggle = ToggleSwitch(
            "显示悬浮状态窗口",
            checked=s.get("output", "overlay_enabled", default=True),
        )
        out_layout.addWidget(self._overlay_toggle)

        self._restore_toggle = ToggleSwitch(
            "粘贴后恢复剪贴板",
            checked=s.get("output", "restore_clipboard", default=True),
        )
        out_layout.addWidget(self._restore_toggle)

        main_layout.addWidget(out_group)

        # --- Buttons ---
        main_layout.addSpacing(8)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("保存")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._on_save_click)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.close)
        btn_layout.addWidget(cancel_btn)

        main_layout.addLayout(btn_layout)

    # --- Device discovery ---

    def _get_input_devices(self) -> list[tuple[int | None, str]]:
        result: list[tuple[int | None, str]] = [(None, "系统默认")]
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            for i, d in enumerate(devices):
                if d["max_input_channels"] > 0 and d["hostapi"] == 0:
                    name = d["name"]
                    if len(name) > 35:
                        name = name[:33] + "\u2026"
                    result.append((i, name))
        except Exception:
            pass
        return result

    def _get_cuda_devices(self) -> list[str]:
        devices = ["cpu"]
        try:
            import torch
            for i in range(torch.cuda.device_count()):
                torch.cuda.get_device_name(i)
                devices.append(f"cuda:{i}")
        except Exception:
            pass
        return devices

    # --- Hotkey capture ---

    def _start_hotkey_capture(self) -> None:
        self._capturing_hotkey = True
        self._captured_keys.clear()
        self._bind_btn.setText("请按下快捷键...")
        self._bind_btn.setObjectName("dangerButton")
        self._bind_btn.style().unpolish(self._bind_btn)
        self._bind_btn.style().polish(self._bind_btn)
        self._hotkey_edit.setText("等待输入...")
        self._hotkey_hook = keyboard.hook(self._on_capture_key, suppress=False)

    def _on_capture_key(self, event: keyboard.KeyboardEvent) -> None:
        """Called from the keyboard library's thread."""
        if not self._capturing_hotkey:
            return

        if event.event_type == keyboard.KEY_DOWN:
            self._captured_keys.add(event.name.lower())
            display = " + ".join(
                k.capitalize() if len(k) > 1 else k.upper()
                for k in sorted(self._captured_keys)
            )
            QMetaObject.invokeMethod(
                self._hotkey_edit, "setText",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, display),
            )

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
                QMetaObject.invokeMethod(
                    self, "_finish_capture",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, display),
                )

    @Slot(str)
    def _finish_capture(self, display: str) -> None:
        self._hotkey_edit.setText(display)
        self._bind_btn.setText("修改绑定")
        self._bind_btn.setObjectName("")
        self._bind_btn.style().unpolish(self._bind_btn)
        self._bind_btn.style().polish(self._bind_btn)

    # --- Save / Cancel ---

    def _on_save_click(self) -> None:
        try:
            display = self._hotkey_edit.text()
            self._settings.set("hotkey", "keys", self._hotkey_keys)
            self._settings.set("hotkey", "display", display)

            mode = "toggle" if self._toggle_radio.isChecked() else "push_to_talk"
            self._settings.set("mode", mode)

            self._settings.set("asr", "device", self._device_combo.currentText())

            mic_idx = self._mic_combo.currentIndex()
            input_dev_id = self._input_devices[mic_idx][0] if mic_idx < len(self._input_devices) else None
            self._settings.set("audio", "input_device", input_dev_id)

            self._settings.set("output", "sound_enabled", self._sound_toggle.isChecked())
            self._settings.set("output", "overlay_enabled", self._overlay_toggle.isChecked())
            self._settings.set("output", "restore_clipboard", self._restore_toggle.isChecked())

            self._settings.save()
            logger.info("Settings saved: mode=%s, hotkey=%s", mode, self._hotkey_keys)

            if self._on_save:
                self._on_save()
        except Exception:
            logger.exception("Failed to save settings")

        self.close()

    def closeEvent(self, event) -> None:
        if self._hotkey_hook is not None:
            keyboard.unhook(self._hotkey_hook)
            self._hotkey_hook = None
        super().closeEvent(event)
