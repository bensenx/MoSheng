"""Prism settings window for input, recognition and app preferences."""

import logging
from typing import Callable

import os
import sys

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox, QDialog, QMessageBox,
    QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QScrollArea, QSpinBox, QStackedWidget, QTabBar, QVBoxLayout, QWidget,
)

from config import ASSETS_DIR, ASR_MODELS, VOCABULARY_FILE
from utils.autostart import is_autostart_enabled, set_autostart
from i18n import tr, get_language, SUPPORTED_LANGUAGES
from settings_manager import SettingsManager
from ui.styles import (
    IconGroupBox, PrismHeader, ToggleSwitch, style_title_bar,
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
        self._captured_keys: set[str] = set()
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
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("settingsRoot")

        for ext in ("ico", "png"):
            icon_path = os.path.join(ASSETS_DIR, f"icon.{ext}")
            if os.path.isfile(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                break

        self._build_ui()
        self.setMinimumHeight(400)
        self.setMaximumHeight(800)
        self.resize(self.minimumWidth(), 612)
        self._center_on_screen()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        style_title_bar(self)

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
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(PrismHeader(tr("tray.settings")))
        body = QVBoxLayout()
        body.setContentsMargins(22, 12, 22, 16)
        body.setSpacing(12)
        main_layout.addLayout(body, 1)
        self._tabs = QTabBar()
        self._tabs.setDrawBase(False)
        self._tabs.setExpanding(True)
        self._tabs.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        body.addWidget(self._tabs)
        pages = QStackedWidget()
        body.addWidget(pages, 1)

        def page(key):
            self._tabs.addTab(tr(key))
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(scroll.Shape.NoFrame)
            content = QWidget()
            content.setObjectName("settingsPage")
            layout = QVBoxLayout(content)
            layout.setSpacing(10)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            scroll.setWidget(content)
            pages.addWidget(scroll)
            return layout

        input_page = page("settings.tab_input")
        recognition_page = page("settings.tab_recognition")
        preferences_page = page("settings.tab_preferences")
        self._tabs.currentChanged.connect(self._cancel_capture)
        self._tabs.currentChanged.connect(pages.setCurrentIndex)

        # --- Hotkeys ---
        hk_group = IconGroupBox(tr("settings.hotkey_section"), "keyboard")
        hk_layout = QVBoxLayout(hk_group)
        hk_layout.setSpacing(8)

        ptt = s.get("hotkey", "push_to_talk", default={})
        toggle = s.get("hotkey", "toggle", default={})

        def shortcut_row(target, title, options, default_key):
            row = QHBoxLayout()
            label = QLabel(title)
            row.addWidget(label, 1)
            button = QPushButton(options.get("display", default_key))
            button.setAutoDefault(False)
            button.setToolTip(tr("settings.change_binding"))
            button.setAccessibleName(f"{title} · {tr('settings.change_binding')}")
            button.clicked.connect(lambda: self._start_hotkey_capture(target))
            row.addWidget(button)
            toggle_switch = ToggleSwitch(checked=options.get("enabled", True))
            toggle_switch.setFixedWidth(toggle_switch.TRACK_WIDTH)
            toggle_switch.setAccessibleName(title)
            label.setBuddy(toggle_switch)
            row.addWidget(toggle_switch)
            hk_layout.addLayout(row)
            return button, toggle_switch

        self._ptt_bind_btn, self._ptt_toggle = shortcut_row(
            "ptt", tr("settings.push_to_talk"), ptt, "Caps Lock")
        self._toggle_bind_btn, self._toggle_toggle = shortcut_row(
            "toggle", tr("settings.toggle_mode"), toggle, "Right Ctrl")

        lp_row = QHBoxLayout()
        lp_row.addWidget(QLabel(tr("settings.long_press_threshold")), 1)
        self._long_press_spin = QSpinBox()
        self._long_press_spin.setRange(100, 1000)
        self._long_press_spin.setSingleStep(50)
        self._long_press_spin.setSuffix(" ms")
        self._long_press_spin.setValue(ptt.get("long_press_ms", 300))
        lp_row.addWidget(self._long_press_spin)
        hk_layout.addLayout(lp_row)

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


        # --- Audio Input Section ---
        mic_group = IconGroupBox(tr("settings.microphone"), "microphone")
        mic_layout = QVBoxLayout(mic_group)

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
        self._mic_combo.setAccessibleName(tr("settings.microphone"))
        mic_layout.addWidget(self._mic_combo)

        input_page.addWidget(mic_group)
        input_page.addWidget(hk_group)

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
        restart_hint_model = QLabel(tr("settings.model_device_hint"))
        restart_hint_model.setObjectName("secondaryLabel")
        restart_hint_model.setWordWrap(True)
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
        asr_layout.addWidget(restart_hint_model)

        recognition_page.addWidget(asr_group)

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

        recognition_page.addWidget(sv_group)

        # --- Output Section ---
        out_group = IconGroupBox(tr("settings.output_section"), "gear")
        out_layout = QVBoxLayout(out_group)
        out_layout.setSpacing(16)

        sound_row = QHBoxLayout()
        sound_row.addWidget(QLabel(tr("settings.sound_style_label")))
        self._sound_combo = QComboBox()
        for key, i18n_key in [
            ("bell", "settings.sound_style_bell"),
            ("chime", "settings.sound_style_chime"),
            ("soft", "settings.sound_style_soft"),
            ("off", "settings.sound_style_off"),
        ]:
            self._sound_combo.addItem(tr(i18n_key), key)
        self._sound_combo.setCurrentIndex(self._sound_combo.findData(
            s.get("output", "sound_style", default="bell")))
        sound_row.addWidget(self._sound_combo)
        sound_row.addStretch()
        out_layout.addLayout(sound_row)

        self._overlay_toggle = ToggleSwitch(
            tr("settings.overlay_toggle"),
            checked=s.get("output", "overlay_enabled", default=True),
        )
        out_layout.addWidget(self._overlay_toggle)

        if sys.platform == "win32":
            self._mode_badge_toggle = ToggleSwitch(
                tr("settings.input_mode_badge"),
                checked=s.get("output", "input_mode_badge", default=True),
            )
            out_layout.addWidget(self._mode_badge_toggle)

        self._restore_toggle = ToggleSwitch(
            tr("settings.restore_clipboard"),
            checked=s.get("output", "restore_clipboard", default=True),
        )
        out_layout.addWidget(self._restore_toggle)

        preferences_page.addWidget(out_group)

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

        recognition_page.addWidget(vocab_group)

        # --- Text Processing Section ---
        tp_group = IconGroupBox(tr("settings.text_processing_section"), "gear")
        tp_layout = QVBoxLayout(tp_group)
        tp_layout.setSpacing(16)
        self._remove_fillers_toggle = ToggleSwitch(
            tr("settings.remove_fillers"),
            checked=s.get("text_processing", "remove_fillers", default=True),
        )
        tp_layout.addWidget(self._remove_fillers_toggle)
        self._smart_punct_toggle = ToggleSwitch(
            tr("settings.smart_punctuation"),
            checked=s.get("text_processing", "smart_punctuation", default=True),
        )
        tp_layout.addWidget(self._smart_punct_toggle)
        punct_hint = QLabel(tr("settings.smart_punct_hint"))
        punct_hint.setObjectName("secondaryLabel")
        punct_hint.setWordWrap(True)
        tp_layout.addWidget(punct_hint)
        recognition_page.addWidget(tp_group)

        general_group = IconGroupBox(tr("settings.general_section"), "gear")
        general_layout = QVBoxLayout(general_group)
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
        restart_hint.setWordWrap(True)
        lang_row.addStretch()
        self._autostart_toggle = ToggleSwitch(
            tr("settings.autostart"),
            checked=is_autostart_enabled(),
        )
        general_layout.addLayout(lang_row)
        general_layout.addWidget(restart_hint)
        general_layout.addWidget(self._autostart_toggle)
        preferences_page.addWidget(general_group)

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton(tr("settings.save"))
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._on_save_click)

        cancel_btn = QPushButton(tr("settings.cancel"))
        cancel_btn.clicked.connect(self.close)
        btn_layout.addWidget(cancel_btn)

        btn_layout.addWidget(save_btn)
        body.addLayout(btn_layout)

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
        import sys
        devices = ["cpu"]
        try:
            import torch
            if sys.platform == "darwin":
                if torch.backends.mps.is_available():
                    devices.append("mps")
            else:
                for i in range(torch.cuda.device_count()):
                    torch.cuda.get_device_name(i)
                    devices.append(f"cuda:{i}")
        except Exception:
            pass
        # Always offer "auto" as first option
        return ["auto"] + devices

    # --- Hotkey capture ---

    def _start_hotkey_capture(self, target: str) -> None:
        """Start capturing hotkey for 'ptt' or 'toggle' binding."""
        self._cancel_capture()
        self._captured_keys.clear()
        self._capture_target = target
        btn = self._capture_button()
        self._previous_binding = btn.text()
        btn.setText(tr("settings.press_hotkey"))
        btn.setObjectName("dangerButton")
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        self.grabKeyboard()

    def _capture_button(self):
        return self._ptt_bind_btn if self._capture_target == "ptt" else self._toggle_bind_btn

    @Slot()
    def _cancel_capture(self):
        if self._capture_target is None:
            return
        btn = self._capture_button()
        btn.setText(self._previous_binding)
        btn.setObjectName("")
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        self.releaseKeyboard()
        self._capture_target = None

    def keyPressEvent(self, event) -> None:
        """Capture hotkey via Qt key events (macOS compatible)."""
        if self._capture_target is None:
            super().keyPressEvent(event)
            return

        from PySide6.QtCore import Qt as QtKey
        # Map Qt key to name
        key = event.key()
        if key == QtKey.Key.Key_Escape:
            self._cancel_capture()
            return
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
            key_name = QtKey.Key(key).name
            key_name = key_name.replace("Key_", "").lower()
            self._captured_keys.add(key_name)

        display = " + ".join(
            k.capitalize() for k in sorted(self._captured_keys)
        )
        self._capture_button().setText(display)

    def keyReleaseEvent(self, event) -> None:
        """Finalize hotkey capture on key release."""
        if self._capture_target is None or not self._captured_keys:
            super().keyReleaseEvent(event)
            return

        keys = sorted(self._captured_keys)
        btn = self._capture_button()
        if self._capture_target == "ptt":
            self._ptt_keys = keys
        else:
            self._toggle_keys = keys
        self._cancel_capture()
        btn.setText(" + ".join(k.capitalize() for k in keys))

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
        import sys
        if sys.platform == "darwin":
            subprocess.Popen(["open", VOCABULARY_FILE])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", VOCABULARY_FILE])
        else:
            subprocess.Popen(["xdg-open", VOCABULARY_FILE])

    # --- Save / Cancel ---

    def _on_save_click(self) -> None:
        self._cancel_capture()
        lang_changed = False
        model_changed = False
        try:
            # Push-to-talk binding
            self._settings.set("hotkey", "push_to_talk", {
                "enabled": self._ptt_toggle.isChecked(),
                "keys": self._ptt_keys,
                "display": self._ptt_bind_btn.text(),
                "long_press_ms": self._long_press_spin.value(),
            })

            # Toggle binding
            self._settings.set("hotkey", "toggle", {
                "enabled": self._toggle_toggle.isChecked(),
                "keys": self._toggle_keys,
                "display": self._toggle_bind_btn.text(),
            })

            self._settings.set("hotkey", "progressive", self._progressive_toggle.isChecked())
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

            self._settings.set("output", "sound_style", self._sound_combo.currentData())
            self._settings.set("output", "overlay_enabled", self._overlay_toggle.isChecked())
            if sys.platform == "win32":
                self._settings.set("output", "input_mode_badge", self._mode_badge_toggle.isChecked())
            self._settings.set("output", "restore_clipboard", self._restore_toggle.isChecked())

            self._settings.set("vocabulary", "enabled", self._vocab_toggle.isChecked())

            self._settings.set("speaker_verification", "enabled", self._sv_toggle.isChecked())

            self._settings.set("text_processing", "remove_fillers", self._remove_fillers_toggle.isChecked())
            self._settings.set("text_processing", "smart_punctuation", self._smart_punct_toggle.isChecked())

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
        self._cancel_capture()
        super().closeEvent(event)
