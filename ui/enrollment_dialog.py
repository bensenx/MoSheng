"""Guided speaker enrollment dialog for recording voice samples."""

import logging
import threading

import numpy as np
from PySide6.QtCore import QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QVBoxLayout, QWidget,
)

from config import SPEAKER_DIR
from settings_manager import SettingsManager
from ui.styles import COLOR_ACCENT, COLOR_RESULT, COLOR_TEXT_SECONDARY, apply_acrylic_effect

logger = logging.getLogger(__name__)

SAMPLE_COUNT = 3
MIN_DURATION_SEC = 3.0
MAX_DURATION_SEC = 8.0
PROMPTS = [
    "请自然地说一段话，例如：今天天气真不错，适合出去散步。",
    "请继续说一段话，例如：我正在使用墨声语音输入工具。",
    "最后一段，例如：声音化为笔墨，记录每一个想法。",
]


class EnrollmentDialog(QDialog):
    """Guided 3-sample speaker enrollment."""

    _recording_done = Signal(np.ndarray)  # emitted from recorder thread

    def __init__(self, settings: SettingsManager, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings = settings
        self._samples: list[np.ndarray] = []
        self._current_sample = 0
        self._recorder = None
        self._is_recording = False
        self._level_timer = QTimer(self)
        self._level_timer.timeout.connect(self._update_level)
        self._auto_stop_timer = QTimer(self)
        self._auto_stop_timer.setSingleShot(True)
        self._auto_stop_timer.timeout.connect(self._auto_stop)

        self._recording_done.connect(self._on_recording_done, Qt.ConnectionType.QueuedConnection)

        self.setWindowTitle("声纹注册")
        self.setMinimumWidth(420)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self._build_ui()
        self.adjustSize()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        hwnd = int(self.winId())
        if not apply_acrylic_effect(hwnd):
            self.setStyleSheet("background-color: #141418;")

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("声纹注册")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {COLOR_ACCENT}; background: transparent;")
        layout.addWidget(title)

        self._instruction = QLabel("请在安静环境下录制 3 段语音样本")
        self._instruction.setObjectName("secondaryLabel")
        self._instruction.setWordWrap(True)
        layout.addWidget(self._instruction)

        layout.addSpacing(8)

        # Progress indicators
        self._progress_row = QHBoxLayout()
        self._step_labels: list[QLabel] = []
        for i in range(SAMPLE_COUNT):
            lbl = QLabel(f"样本 {i + 1}")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; background: transparent; font-size: 12px;")
            lbl.setFixedWidth(80)
            self._step_labels.append(lbl)
            self._progress_row.addWidget(lbl)
        layout.addLayout(self._progress_row)

        # Prompt text
        self._prompt_label = QLabel(PROMPTS[0])
        self._prompt_label.setWordWrap(True)
        self._prompt_label.setStyleSheet("background: transparent; font-size: 13px; padding: 8px;")
        layout.addWidget(self._prompt_label)

        # Volume level bar
        self._level_bar = QProgressBar()
        self._level_bar.setRange(0, 100)
        self._level_bar.setValue(0)
        self._level_bar.setTextVisible(False)
        self._level_bar.setFixedHeight(8)
        layout.addWidget(self._level_bar)

        # Record button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._record_btn = QPushButton("开始录制")
        self._record_btn.setObjectName("primaryButton")
        self._record_btn.clicked.connect(self._toggle_recording)
        btn_row.addWidget(self._record_btn)

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Status label
        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; background: transparent;")
        layout.addWidget(self._status_label)

    def _toggle_recording(self) -> None:
        if self._is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        from core.audio_recorder import AudioRecorder

        input_dev = self._settings.get("audio", "input_device", default=None)
        self._recorder = AudioRecorder(sample_rate=16000, device=input_dev)
        self._recorder.start_recording()
        self._is_recording = True

        self._record_btn.setText("停止录制")
        self._record_btn.setObjectName("dangerButton")
        self._record_btn.style().unpolish(self._record_btn)
        self._record_btn.style().polish(self._record_btn)
        self._status_label.setText("正在录制...")
        self._level_timer.start(50)

        # Auto-stop after MAX_DURATION_SEC (cancellable on manual stop)
        self._auto_stop_timer.start(int(MAX_DURATION_SEC * 1000))

    def _auto_stop(self) -> None:
        if self._is_recording:
            self._stop_recording()

    def _stop_recording(self) -> None:
        if not self._is_recording:
            return
        self._is_recording = False
        self._auto_stop_timer.stop()
        self._level_timer.stop()
        self._level_bar.setValue(0)

        audio = self._recorder.stop_recording()
        self._recorder = None

        self._record_btn.setText("开始录制")
        self._record_btn.setObjectName("primaryButton")
        self._record_btn.style().unpolish(self._record_btn)
        self._record_btn.style().polish(self._record_btn)

        if audio is None or len(audio) / 16000 < MIN_DURATION_SEC:
            self._status_label.setText(f"录音太短（至少 {MIN_DURATION_SEC:.0f} 秒），请重试")
            return

        self._recording_done.emit(audio)

    @Slot(np.ndarray)
    def _on_recording_done(self, audio: np.ndarray) -> None:
        self._samples.append(audio)
        self._step_labels[self._current_sample].setStyleSheet(
            f"color: {COLOR_RESULT}; background: transparent; font-size: 12px; font-weight: 700;"
        )
        self._current_sample += 1

        if self._current_sample < SAMPLE_COUNT:
            self._prompt_label.setText(PROMPTS[self._current_sample])
            self._status_label.setText(f"样本 {self._current_sample} 录制完成")
        else:
            self._record_btn.setEnabled(False)
            self._status_label.setText("正在处理声纹...")
            QTimer.singleShot(100, self._process_enrollment)

    def _process_enrollment(self) -> None:
        """Run enrollment in a background thread to avoid blocking UI."""
        def _do_enroll():
            try:
                from core.speaker_verifier import SpeakerVerifier

                device = self._settings.get("asr", "device", default="cuda:0")
                verifier = SpeakerVerifier(device=device)
                verifier.load_model()

                threshold = self._settings.get("speaker_verification", "threshold", default=0.25)
                high = self._settings.get("speaker_verification", "high_threshold", default=0.40)
                low = self._settings.get("speaker_verification", "low_threshold", default=0.10)
                verifier.update_thresholds(threshold, high, low)

                success, message = verifier.enroll(self._samples, SPEAKER_DIR)
                verifier.unload_model()

                from PySide6.QtCore import QMetaObject, Q_ARG
                QMetaObject.invokeMethod(
                    self, "_on_enrollment_result",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(bool, success),
                    Q_ARG(str, message),
                )
            except Exception as e:
                logger.exception("Enrollment failed")
                from PySide6.QtCore import QMetaObject, Q_ARG
                QMetaObject.invokeMethod(
                    self, "_on_enrollment_result",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(bool, False),
                    Q_ARG(str, f"注册失败: {e}"),
                )

        threading.Thread(target=_do_enroll, daemon=True).start()

    @Slot(bool, str)
    def _on_enrollment_result(self, success: bool, message: str) -> None:
        if success:
            self._status_label.setText(message)
            self._status_label.setStyleSheet(f"color: {COLOR_RESULT}; background: transparent;")
            QTimer.singleShot(1500, self.accept)
        else:
            self._status_label.setText(message)
            # Reset for retry
            self._samples.clear()
            self._current_sample = 0
            self._record_btn.setEnabled(True)
            self._prompt_label.setText(PROMPTS[0])
            for lbl in self._step_labels:
                lbl.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; background: transparent; font-size: 12px;")

    def _update_level(self) -> None:
        if self._recorder and self._recorder.is_recording:
            rms = self._recorder.recent_rms()
            level = min(100, int(rms * 500))
            self._level_bar.setValue(level)

    def closeEvent(self, event) -> None:
        if self._is_recording and self._recorder:
            self._recorder.stop_recording()
        super().closeEvent(event)
