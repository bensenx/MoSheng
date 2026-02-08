"""Settings window with glassmorphism dark theme and DWM Mica backdrop."""

import logging
from typing import Callable

import os

import keyboard
from PySide6.QtCore import QMetaObject, Qt, Slot, Q_ARG
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QDoubleSpinBox, QRadioButton, QVBoxLayout, QWidget,
)

from config import ASSETS_DIR, VOCABULARY_FILE
from i18n import tr, get_language, SUPPORTED_LANGUAGES
from settings_manager import SettingsManager
from ui.styles import (
    COLOR_ACCENT, COLOR_TEXT_SECONDARY, IconGroupBox, ToggleSwitch,
    apply_acrylic_effect, load_icon_pixmap,
)

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

        self.setWindowTitle(tr("settings.title"))
        self.setMinimumWidth(460)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("settingsRoot")

        # Set window title bar icon
        for ext in ("ico", "png"):
            icon_path = os.path.join(ASSETS_DIR, f"icon.{ext}")
            if os.path.isfile(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                break

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

        # --- Logo + Title Header ---
        header = QHBoxLayout()
        header.setSpacing(12)

        icon_label = QLabel()
        logo_size = 44
        pm = load_icon_pixmap(logo_size)
        if pm:
            icon_label.setPixmap(pm)
        icon_label.setFixedSize(logo_size, logo_size)
        header.addWidget(icon_label)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title_label = QLabel(tr("settings.app_name"))
        title_label.setStyleSheet(
            f"font-size: 20px; font-weight: 700; color: {COLOR_ACCENT};"
            " background: transparent;"
        )
        title_col.addWidget(title_label)
        subtitle_label = QLabel(tr("settings.subtitle"))
        subtitle_label.setStyleSheet(
            f"font-size: 11px; color: {COLOR_TEXT_SECONDARY};"
            " background: transparent;"
        )
        title_col.addWidget(subtitle_label)
        header.addLayout(title_col)
        header.addStretch()

        main_layout.addLayout(header)
        main_layout.addSpacing(8)

        # --- Language Selector ---
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel(tr("settings.language_label")))
        self._lang_combo = QComboBox()
        for code, name in SUPPORTED_LANGUAGES.items():
            self._lang_combo.addItem(name, code)
        current_lang = s.get("language", default=get_language())
        for i in range(self._lang_combo.count()):
            if self._lang_combo.itemData(i) == current_lang:
                self._lang_combo.setCurrentIndex(i)
                break
        lang_row.addWidget(self._lang_combo)
        restart_hint = QLabel(tr("settings.restart_hint"))
        restart_hint.setObjectName("secondaryLabel")
        lang_row.addWidget(restart_hint)
        lang_row.addStretch()
        main_layout.addLayout(lang_row)
        main_layout.addSpacing(4)

        # --- Hotkey Section ---
        hk_group = IconGroupBox(tr("settings.hotkey_section"), "keyboard")
        hk_layout = QVBoxLayout(hk_group)
        hk_layout.setSpacing(12)

        # Row 1: hotkey display + bind button
        row1 = QHBoxLayout()
        row1.addWidget(QLabel(tr("settings.hotkey_label")))

        self._hotkey_keys = list(s.get("hotkey", "keys", default=["ctrl", "left windows"]))
        self._hotkey_edit = QLineEdit(
            s.get("hotkey", "display", default="Ctrl + Win")
        )
        self._hotkey_edit.setReadOnly(True)
        self._hotkey_edit.setFixedWidth(160)
        row1.addWidget(self._hotkey_edit)

        self._bind_btn = QPushButton(tr("settings.change_binding"))
        self._bind_btn.clicked.connect(self._start_hotkey_capture)
        row1.addWidget(self._bind_btn)
        row1.addStretch()
        hk_layout.addLayout(row1)

        # Row 2: recording mode
        row2 = QHBoxLayout()
        row2.addWidget(QLabel(tr("settings.mode_label")))

        self._mode_group = QButtonGroup(self)
        self._push_radio = QRadioButton(tr("settings.push_to_talk"))
        self._toggle_radio = QRadioButton(tr("settings.toggle_mode"))
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

        # Row 3: progressive input toggle
        self._progressive_toggle = ToggleSwitch(
            tr("settings.progressive_input"),
            checked=s.get("hotkey", "progressive", default=False),
        )
        self._progressive_toggle.toggled.connect(self._on_progressive_toggled)
        hk_layout.addWidget(self._progressive_toggle)

        # Row 4-5: silence threshold + duration (progressive sub-settings)
        self._progressive_opts = QWidget()
        prog_layout = QHBoxLayout(self._progressive_opts)
        prog_layout.setContentsMargins(24, 0, 0, 0)
        prog_layout.setSpacing(16)

        prog_layout.addWidget(QLabel(tr("settings.silence_threshold")))
        self._threshold_spin = QDoubleSpinBox()
        self._threshold_spin.setRange(0.005, 0.200)
        self._threshold_spin.setSingleStep(0.005)
        self._threshold_spin.setDecimals(3)
        self._threshold_spin.setValue(
            s.get("hotkey", "silence_threshold", default=0.01)
        )
        prog_layout.addWidget(self._threshold_spin)

        prog_layout.addWidget(QLabel(tr("settings.silence_duration")))
        self._duration_spin = QDoubleSpinBox()
        self._duration_spin.setRange(0.3, 3.0)
        self._duration_spin.setSingleStep(0.1)
        self._duration_spin.setDecimals(1)
        self._duration_spin.setValue(
            s.get("hotkey", "silence_duration", default=0.8)
        )
        prog_layout.addWidget(self._duration_spin)
        prog_layout.addStretch()

        self._progressive_opts.setVisible(self._progressive_toggle.isChecked())
        hk_layout.addWidget(self._progressive_opts)

        main_layout.addWidget(hk_group)

        # --- ASR Section ---
        asr_group = IconGroupBox(tr("settings.asr_section"), "waveform")
        asr_layout = QVBoxLayout(asr_group)
        asr_layout.setSpacing(12)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel(tr("settings.asr_model")))
        model_combo = QComboBox()
        model_combo.addItem("Qwen3-ASR-1.7B")
        model_combo.setEnabled(False)
        row3.addWidget(model_combo)
        row3.addStretch()
        asr_layout.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addWidget(QLabel(tr("settings.device_label")))
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
        mic_group = IconGroupBox(tr("settings.audio_section"), "microphone")
        mic_layout = QVBoxLayout(mic_group)

        row_mic = QHBoxLayout()
        row_mic.addWidget(QLabel(tr("settings.microphone")))
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

        # --- Speaker Verification Section ---
        sv_group = IconGroupBox(tr("settings.speaker_section"), "shield")
        sv_layout = QVBoxLayout(sv_group)
        sv_layout.setSpacing(10)

        self._sv_toggle = ToggleSwitch(
            tr("settings.enable_speaker"),
            checked=s.get("speaker_verification", "enabled", default=False),
        )
        sv_layout.addWidget(self._sv_toggle)

        sv_hint = QLabel(tr("settings.speaker_hint"))
        sv_hint.setObjectName("secondaryLabel")
        sv_hint.setWordWrap(True)
        sv_layout.addWidget(sv_hint)

        sv_btn_row = QHBoxLayout()
        self._sv_status_label = QLabel(self._get_enrollment_status())
        self._sv_status_label.setObjectName("secondaryLabel")
        sv_btn_row.addWidget(self._sv_status_label)
        sv_btn_row.addStretch()
        self._enroll_btn = QPushButton(tr("settings.enroll_voice"))
        self._enroll_btn.clicked.connect(self._open_enrollment)
        sv_btn_row.addWidget(self._enroll_btn)
        sv_layout.addLayout(sv_btn_row)

        main_layout.addWidget(sv_group)

        # --- Output Section ---
        out_group = IconGroupBox(tr("settings.output_section"), "gear")
        out_layout = QVBoxLayout(out_group)
        out_layout.setSpacing(10)

        self._sound_toggle = ToggleSwitch(
            tr("settings.sound_toggle"),
            checked=s.get("output", "sound_enabled", default=True),
        )
        out_layout.addWidget(self._sound_toggle)

        self._overlay_toggle = ToggleSwitch(
            tr("settings.overlay_toggle"),
            checked=s.get("output", "overlay_enabled", default=True),
        )
        out_layout.addWidget(self._overlay_toggle)

        self._restore_toggle = ToggleSwitch(
            tr("settings.restore_clipboard"),
            checked=s.get("output", "restore_clipboard", default=True),
        )
        out_layout.addWidget(self._restore_toggle)

        main_layout.addWidget(out_group)

        # --- Vocabulary Section ---
        vocab_group = IconGroupBox(tr("settings.vocab_section"), "book")
        vocab_layout = QVBoxLayout(vocab_group)
        vocab_layout.setSpacing(8)

        self._vocab_toggle = ToggleSwitch(
            tr("settings.vocab_toggle"),
            checked=s.get("vocabulary", "enabled", default=True),
        )
        vocab_layout.addWidget(self._vocab_toggle)

        hint = QLabel(tr("settings.vocab_hint"))
        hint.setObjectName("secondaryLabel")
        hint.setWordWrap(True)
        vocab_layout.addWidget(hint)

        vocab_row = QHBoxLayout()
        word_count = self._count_vocab_words()
        self._vocab_count_label = QLabel(tr("settings.vocab_count", count=word_count))
        self._vocab_count_label.setObjectName("secondaryLabel")
        vocab_row.addWidget(self._vocab_count_label)
        vocab_row.addStretch()
        open_btn = QPushButton(tr("settings.open_vocab"))
        open_btn.clicked.connect(self._open_vocab_file)
        vocab_row.addWidget(open_btn)
        vocab_layout.addLayout(vocab_row)

        main_layout.addWidget(vocab_group)

        # --- Buttons ---
        main_layout.addSpacing(8)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton(tr("settings.save"))
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._on_save_click)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton(tr("settings.cancel"))
        cancel_btn.clicked.connect(self.close)
        btn_layout.addWidget(cancel_btn)

        main_layout.addLayout(btn_layout)

    # --- Progressive toggle ---

    def _on_progressive_toggled(self, checked: bool) -> None:
        self._progressive_opts.setVisible(checked)

    # --- Speaker verification ---

    def _get_enrollment_status(self) -> str:
        from config import SPEAKER_DIR
        centroid_path = os.path.join(SPEAKER_DIR, "centroid.npy")
        if os.path.isfile(centroid_path):
            meta_path = os.path.join(SPEAKER_DIR, "metadata.json")
            if os.path.isfile(meta_path):
                try:
                    import json
                    with open(meta_path, encoding="utf-8") as f:
                        meta = json.load(f)
                    return tr("settings.enrolled_samples", count=meta.get('sample_count', '?'))
                except Exception:
                    pass
            return tr("settings.enrolled")
        return tr("settings.not_enrolled")

    def _open_enrollment(self) -> None:
        from ui.enrollment_dialog import EnrollmentDialog
        dialog = EnrollmentDialog(self._settings, parent=self)
        if dialog.exec():
            self._sv_status_label.setText(self._get_enrollment_status())
            # Auto-enable and save so verifier loads immediately
            self._sv_toggle.setChecked(True)
            self._on_save_click()

    # --- Device discovery ---

    def _get_input_devices(self) -> list[tuple[int | None, str]]:
        result: list[tuple[int | None, str]] = [(None, tr("settings.system_default"))]
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
        self._bind_btn.setText(tr("settings.press_hotkey"))
        self._bind_btn.setObjectName("dangerButton")
        self._bind_btn.style().unpolish(self._bind_btn)
        self._bind_btn.style().polish(self._bind_btn)
        self._hotkey_edit.setText(tr("settings.waiting_input"))
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
        self._bind_btn.setText(tr("settings.change_binding"))
        self._bind_btn.setObjectName("")
        self._bind_btn.style().unpolish(self._bind_btn)
        self._bind_btn.style().polish(self._bind_btn)

    # --- Vocabulary ---

    @staticmethod
    def _count_vocab_words() -> int:
        try:
            with open(VOCABULARY_FILE, encoding="utf-8-sig") as f:
                return sum(1 for line in f
                           if line.strip() and not line.startswith("#"))
        except FileNotFoundError:
            return 0

    def _open_vocab_file(self) -> None:
        if not os.path.isfile(VOCABULARY_FILE):
            os.makedirs(os.path.dirname(VOCABULARY_FILE), exist_ok=True)
            with open(VOCABULARY_FILE, "w", encoding="utf-8") as f:
                f.write(tr("settings.vocab_file_header"))
        # Open the folder and select the file in Explorer
        import subprocess
        subprocess.Popen(["explorer", "/select,", VOCABULARY_FILE])

    # --- Save / Cancel ---

    def _on_save_click(self) -> None:
        try:
            display = self._hotkey_edit.text()
            self._settings.set("hotkey", "keys", self._hotkey_keys)
            self._settings.set("hotkey", "display", display)

            mode = "toggle" if self._toggle_radio.isChecked() else "push_to_talk"
            self._settings.set("mode", mode)

            self._settings.set("hotkey", "progressive", self._progressive_toggle.isChecked())
            self._settings.set("hotkey", "silence_threshold", self._threshold_spin.value())
            self._settings.set("hotkey", "silence_duration", self._duration_spin.value())

            self._settings.set("asr", "device", self._device_combo.currentText())

            mic_idx = self._mic_combo.currentIndex()
            input_dev_id = self._input_devices[mic_idx][0] if mic_idx < len(self._input_devices) else None
            self._settings.set("audio", "input_device", input_dev_id)

            self._settings.set("output", "sound_enabled", self._sound_toggle.isChecked())
            self._settings.set("output", "overlay_enabled", self._overlay_toggle.isChecked())
            self._settings.set("output", "restore_clipboard", self._restore_toggle.isChecked())

            self._settings.set("vocabulary", "enabled", self._vocab_toggle.isChecked())

            self._settings.set("speaker_verification", "enabled", self._sv_toggle.isChecked())

            new_lang = self._lang_combo.currentData()
            lang_changed = new_lang != get_language()
            self._settings.set("language", new_lang)

            self._settings.save()
            logger.info("Settings saved: mode=%s, hotkey=%s", mode, self._hotkey_keys)

            if self._on_save:
                self._on_save()
        except Exception:
            logger.exception("Failed to save settings")

        self.close()

        if lang_changed:
            QMessageBox.information(
                None, tr("settings.title"),
                tr("settings.restart_required"),
            )

    def closeEvent(self, event) -> None:
        if self._hotkey_hook is not None:
            keyboard.unhook(self._hotkey_hook)
            self._hotkey_hook = None
        super().closeEvent(event)
