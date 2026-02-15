"""Settings window with glassmorphism dark theme and DWM Mica backdrop."""

import logging
from typing import Callable

import os

from PySide6.QtCore import QMetaObject, Qt, Slot, Q_ARG
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox, QDialog, QMessageBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QDoubleSpinBox, QSpinBox, QVBoxLayout, QWidget,
)

from config import ASSETS_DIR, ASR_MODELS, VOCABULARY_FILE
from utils.autostart import is_autostart_enabled, set_autostart
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
        self._input_devices: list[tuple[int | None, str]] = []

        # Hotkey capture state
        self._capturing_hotkey = False
        self._captured_keys: set[str] = set()
        self._hotkey_hook = None
        self._capture_target: str | None = None  # "ptt" or "toggle"

        # Current binding keys (loaded from settings)
        ptt = settings.get("hotkey", "push_to_talk", default={})
        toggle = settings.get("hotkey", "toggle", default={})
        self._ptt_keys: list[str] = list(ptt.get("keys", ["caps lock"]))
        self._toggle_keys: list[str] = list(toggle.get("keys", ["right ctrl"]))

        self.setWindowTitle(tr("settings.title"))
        self.setMinimumWidth(560)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        import sys
        if sys.platform != "darwin":
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("settingsRoot")

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
        import sys
        if sys.platform == "darwin":
            # No DWM acrylic on macOS — use solid fallback
            self.setObjectName("settingsFallback")
            self.style().unpolish(self)
            self.style().polish(self)
        else:
            hwnd = int(self.winId())
            if not apply_acrylic_effect(hwnd):
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

        # --- Language & Autostart (merged row) ---
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
        self._autostart_toggle = ToggleSwitch(
            tr("settings.autostart"),
            checked=is_autostart_enabled(),
        )
        lang_row.addWidget(self._autostart_toggle)
        main_layout.addLayout(lang_row)
        main_layout.addSpacing(4)

        # --- Hotkey Section (two-column PTT / Toggle) ---
        hk_group = IconGroupBox(tr("settings.hotkey_section"), "keyboard")
        hk_layout = QVBoxLayout(hk_group)
        hk_layout.setSpacing(8)

        ptt = s.get("hotkey", "push_to_talk", default={})
        toggle = s.get("hotkey", "toggle", default={})

        # Two-column layout
        columns = QHBoxLayout()
        columns.setSpacing(16)

        # -- Left column: Push-to-talk --
        ptt_col = QVBoxLayout()
        ptt_col.setSpacing(6)

        self._ptt_toggle = ToggleSwitch(
            tr("settings.push_to_talk"),
            checked=ptt.get("enabled", True),
        )
        ptt_col.addWidget(self._ptt_toggle)

        ptt_key_row = QHBoxLayout()
        ptt_key_row.addWidget(QLabel(tr("settings.hotkey_label")))
        self._ptt_edit = QLineEdit(ptt.get("display", "Caps Lock"))
        self._ptt_edit.setReadOnly(True)
        self._ptt_edit.setFixedWidth(120)
        ptt_key_row.addWidget(self._ptt_edit)
        self._ptt_bind_btn = QPushButton(tr("settings.change_binding"))
        self._ptt_bind_btn.clicked.connect(lambda: self._start_hotkey_capture("ptt"))
        ptt_key_row.addWidget(self._ptt_bind_btn)
        ptt_col.addLayout(ptt_key_row)

        lp_row = QHBoxLayout()
        lp_row.addWidget(QLabel(tr("settings.long_press_threshold")))
        self._long_press_spin = QSpinBox()
        self._long_press_spin.setRange(100, 1000)
        self._long_press_spin.setSingleStep(50)
        self._long_press_spin.setSuffix(" ms")
        self._long_press_spin.setValue(ptt.get("long_press_ms", 300))
        lp_row.addWidget(self._long_press_spin)
        lp_row.addStretch()
        ptt_col.addLayout(lp_row)

        columns.addLayout(ptt_col)

        # -- Right column: Toggle --
        toggle_col = QVBoxLayout()
        toggle_col.setSpacing(6)

        self._toggle_toggle = ToggleSwitch(
            tr("settings.toggle_mode"),
            checked=toggle.get("enabled", True),
        )
        toggle_col.addWidget(self._toggle_toggle)

        toggle_key_row = QHBoxLayout()
        toggle_key_row.addWidget(QLabel(tr("settings.hotkey_label")))
        self._toggle_edit = QLineEdit(toggle.get("display", "Right Ctrl"))
        self._toggle_edit.setReadOnly(True)
        self._toggle_edit.setFixedWidth(120)
        toggle_key_row.addWidget(self._toggle_edit)
        self._toggle_bind_btn = QPushButton(tr("settings.change_binding"))
        self._toggle_bind_btn.clicked.connect(lambda: self._start_hotkey_capture("toggle"))
        toggle_key_row.addWidget(self._toggle_bind_btn)
        toggle_col.addLayout(toggle_key_row)

        toggle_col.addStretch()
        columns.addLayout(toggle_col)

        hk_layout.addLayout(columns)

        # -- Progressive input (full width, below columns) --
        self._progressive_toggle = ToggleSwitch(
            tr("settings.progressive_input"),
            checked=s.get("hotkey", "progressive", default=False),
        )
        self._progressive_toggle.toggled.connect(self._on_progressive_toggled)
        hk_layout.addWidget(self._progressive_toggle)

        # Progressive sub-settings
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
        self._model_combo = QComboBox()
        current_model_id = s.get("asr", "model_id", default="Qwen/Qwen3-ASR-1.7B")
        for m in ASR_MODELS:
            self._model_combo.addItem(m["model_name"], m["model_id"])
        idx = self._model_combo.findData(current_model_id)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        row3.addWidget(self._model_combo)
        restart_hint_model = QLabel(tr("settings.restart_hint"))
        restart_hint_model.setObjectName("secondaryLabel")
        row3.addWidget(restart_hint_model)
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

        # --- Output Section (horizontal toggles) ---
        out_group = IconGroupBox(tr("settings.output_section"), "gear")
        out_layout = QHBoxLayout(out_group)
        out_layout.setSpacing(16)

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
        out_layout.addStretch()

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

    def _start_hotkey_capture(self, target: str) -> None:
        """Start capturing hotkey for 'ptt' or 'toggle' binding."""
        self._capturing_hotkey = True
        self._captured_keys.clear()
        self._capture_target = target

        if target == "ptt":
            btn = self._ptt_bind_btn
            edit = self._ptt_edit
        else:
            btn = self._toggle_bind_btn
            edit = self._toggle_edit

        btn.setText(tr("settings.press_hotkey"))
        btn.setObjectName("dangerButton")
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        edit.setText(tr("settings.waiting_input"))
        # On macOS we use Qt key events (grabKeyboard) instead of the keyboard library
        edit.setFocus()
        edit.grabKeyboard()
        self._hotkey_hook = True  # flag that we're capturing

    def keyPressEvent(self, event) -> None:
        """Capture hotkey via Qt key events (macOS compatible)."""
        if not self._capturing_hotkey:
            super().keyPressEvent(event)
            return

        from PySide6.QtCore import Qt as QtKey
        # Map Qt key to name
        key = event.key()
        modifiers = event.modifiers()

        # Ignore pure modifier press, just track them
        _MOD_NAMES = {
            QtKey.Key.Key_Shift: "shift", QtKey.Key.Key_Control: "control",
            QtKey.Key.Key_Alt: "alt", QtKey.Key.Key_Meta: "command",
        }
        if key in _MOD_NAMES:
            self._captured_keys.add(_MOD_NAMES[key])
        else:
            # Add modifiers
            if modifiers & QtKey.KeyboardModifier.ShiftModifier:
                self._captured_keys.add("shift")
            if modifiers & QtKey.KeyboardModifier.ControlModifier:
                self._captured_keys.add("control")
            if modifiers & QtKey.KeyboardModifier.AltModifier:
                self._captured_keys.add("alt")
            if modifiers & QtKey.KeyboardModifier.MetaModifier:
                self._captured_keys.add("command")
            # Add the actual key
            key_name = QtKey.Key(key).name.decode() if isinstance(QtKey.Key(key).name, bytes) else QtKey.Key(key).name
            key_name = key_name.replace("Key_", "").lower()
            self._captured_keys.add(key_name)

        edit = self._ptt_edit if self._capture_target == "ptt" else self._toggle_edit
        display = " + ".join(
            k.capitalize() for k in sorted(self._captured_keys)
        )
        edit.setText(display)

    def keyReleaseEvent(self, event) -> None:
        """Finalize hotkey capture on key release."""
        if not self._capturing_hotkey or not self._captured_keys:
            super().keyReleaseEvent(event)
            return

        self._capturing_hotkey = False
        self._hotkey_hook = None
        self.releaseKeyboard()

        target = self._capture_target
        keys = sorted(self._captured_keys)
        display = " + ".join(k.capitalize() for k in keys)

        if target == "ptt":
            self._ptt_keys = keys
        else:
            self._toggle_keys = keys

                QMetaObject.invokeMethod(
                    self, "_finish_capture",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, target), Q_ARG(str, display),
                )

    @Slot(str, str)
    def _finish_capture(self, target: str, display: str) -> None:
        if target == "ptt":
            self._ptt_edit.setText(display)
            btn = self._ptt_bind_btn
        else:
            self._toggle_edit.setText(display)
            btn = self._toggle_bind_btn

        btn.setText(tr("settings.change_binding"))
        btn.setObjectName("")
        btn.style().unpolish(btn)
        btn.style().polish(btn)

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
        import subprocess
        subprocess.Popen(["explorer", "/select,", VOCABULARY_FILE])

    # --- Save / Cancel ---

    def _on_save_click(self) -> None:
        lang_changed = False
        model_changed = False
        try:
            # Push-to-talk binding
            self._settings.set("hotkey", "push_to_talk", {
                "enabled": self._ptt_toggle.isChecked(),
                "keys": self._ptt_keys,
                "display": self._ptt_edit.text(),
                "long_press_ms": self._long_press_spin.value(),
            })

            # Toggle binding
            self._settings.set("hotkey", "toggle", {
                "enabled": self._toggle_toggle.isChecked(),
                "keys": self._toggle_keys,
                "display": self._toggle_edit.text(),
            })

            self._settings.set("hotkey", "progressive", self._progressive_toggle.isChecked())
            self._settings.set("hotkey", "silence_threshold", self._threshold_spin.value())
            self._settings.set("hotkey", "silence_duration", self._duration_spin.value())

            # ASR model
            old_model_id = self._settings.get("asr", "model_id", default="Qwen/Qwen3-ASR-1.7B")
            new_model_id = self._model_combo.currentData()
            self._settings.set("asr", "model_id", new_model_id)
            self._settings.set("asr", "model_name", self._model_combo.currentText())
            model_changed = new_model_id != old_model_id

            self._settings.set("asr", "device", self._device_combo.currentText())

            mic_idx = self._mic_combo.currentIndex()
            input_dev_id = self._input_devices[mic_idx][0] if mic_idx < len(self._input_devices) else None
            self._settings.set("audio", "input_device", input_dev_id)

            self._settings.set("output", "sound_enabled", self._sound_toggle.isChecked())
            self._settings.set("output", "overlay_enabled", self._overlay_toggle.isChecked())
            self._settings.set("output", "restore_clipboard", self._restore_toggle.isChecked())

            self._settings.set("vocabulary", "enabled", self._vocab_toggle.isChecked())

            self._settings.set("speaker_verification", "enabled", self._sv_toggle.isChecked())

            # Autostart (writes registry directly)
            set_autostart(self._autostart_toggle.isChecked())

            new_lang = self._lang_combo.currentData()
            lang_changed = new_lang != get_language()
            self._settings.set("language", new_lang)

            self._settings.save()
            logger.info("Settings saved: ptt=%s, toggle=%s",
                         self._ptt_keys, self._toggle_keys)

            if self._on_save:
                self._on_save()
        except Exception:
            logger.exception("Failed to save settings")

        self.close()

        if lang_changed or model_changed:
            msg = tr("settings.restart_required") if lang_changed else tr("settings.restart_required_model")
            QMessageBox.information(
                None, tr("settings.title"), msg,
            )

    def closeEvent(self, event) -> None:
        if self._hotkey_hook is not None:
            self.releaseKeyboard()
            self._hotkey_hook = None
        super().closeEvent(event)
