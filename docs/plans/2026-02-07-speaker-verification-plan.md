# Speaker Verification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add silent speaker verification so MoSheng filters out non-user speech before ASR, using SpeechBrain ECAPA-TDNN embeddings with a two-tier fast/slow verification strategy.

**Architecture:** Audio goes through a `SpeakerVerifier` after recording stops. Fast path extracts a single embedding and compares to the enrolled centroid (~50-100ms). If ambiguous, slow path runs windowed segmentation + per-segment verification, concatenating only user segments before ASR. Enrollment is a guided 3-sample recording dialog.

**Tech Stack:** SpeechBrain (`speechbrain.inference.speaker.EncoderClassifier`), PyTorch, NumPy, PySide6

---

### Task 1: Add SpeechBrain dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add speechbrain to dependencies**

In `pyproject.toml`, add `"speechbrain>=1.0"` to the `dependencies` list:

```toml
dependencies = [
    "torch>=2.0",
    "qwen-asr>=0.0.6",
    "sounddevice>=0.4.6",
    "numpy>=1.24",
    "keyboard>=0.13.5",
    "pywin32>=306",
    "PySide6>=6.7",
    "speechbrain>=1.0",
]
```

**Step 2: Sync dependencies**

Run: `uv sync --project E:\VoiceInput\.worktrees\speaker-verification`

Expected: SpeechBrain and its dependencies install successfully.

**Step 3: Verify import**

Run: `uv run --project E:\VoiceInput\.worktrees\speaker-verification python -c "from speechbrain.inference.speaker import EncoderClassifier; print('OK')"`

Expected: `OK`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add speechbrain dependency for speaker verification"
```

---

### Task 2: Add default settings for speaker verification

**Files:**
- Modify: `config.py:38-65` (add to `DEFAULT_SETTINGS`)

**Step 1: Add speaker_verification settings block**

Add a new `"speaker_verification"` key to `DEFAULT_SETTINGS` dict in `config.py`, after the `"vocabulary"` block, and add a `SPEAKER_DIR` path constant:

```python
SPEAKER_DIR = os.path.join(SETTINGS_DIR, "speaker")
```

Add to `DEFAULT_SETTINGS`:

```python
    "speaker_verification": {
        "enabled": False,
        "threshold": 0.25,
        "high_threshold": 0.40,
        "low_threshold": 0.10,
    },
```

**Step 2: Verify config loads**

Run: `uv run --project E:\VoiceInput\.worktrees\speaker-verification python -c "from config import DEFAULT_SETTINGS, SPEAKER_DIR; print(DEFAULT_SETTINGS['speaker_verification']); print(SPEAKER_DIR)"`

Expected: Prints the dict and path without errors.

**Step 3: Commit**

```bash
git add config.py
git commit -m "feat: add speaker verification default settings and SPEAKER_DIR"
```

---

### Task 3: Create SpeakerVerifier core module

**Files:**
- Create: `core/speaker_verifier.py`

**Step 1: Write the SpeakerVerifier class**

Create `core/speaker_verifier.py` with the full implementation:

```python
"""Speaker verification using SpeechBrain ECAPA-TDNN embeddings."""

import json
import logging
import os
import time
from dataclasses import dataclass

import numpy as np
import torch

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 192


@dataclass
class VerifyResult:
    """Result of speaker verification."""
    audio: np.ndarray | None  # Filtered audio (user segments only), or None if rejected
    is_user: bool             # Whether user speech was detected
    score: float              # Similarity score (fast path) or max segment score
    path: str                 # "bypass" | "fast_accept" | "fast_reject" | "slow_accept" | "slow_reject"


class SpeakerVerifier:
    """Two-tier speaker verification: fast embedding check, slow windowed segmentation."""

    def __init__(self, device: str = "cuda:0"):
        self._device = device
        self._model = None
        self._centroid: np.ndarray | None = None  # shape: (EMBEDDING_DIM,)
        self._threshold = 0.25
        self._high_threshold = 0.40
        self._low_threshold = 0.10

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    @property
    def is_enrolled(self) -> bool:
        return self._centroid is not None

    def load_model(self, save_dir: str = "") -> None:
        """Load ECAPA-TDNN encoder model."""
        from speechbrain.inference.speaker import EncoderClassifier

        logger.info("Loading speaker verification model on %s", self._device)
        t0 = time.time()
        self._model = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=save_dir or None,
            run_opts={"device": self._device},
        )
        elapsed = time.time() - t0
        logger.info("Speaker verification model loaded in %.1fs", elapsed)

    def unload_model(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
            torch.cuda.empty_cache()
            logger.info("Speaker verification model unloaded")

    def load_enrollment(self, speaker_dir: str) -> bool:
        """Load enrolled centroid embedding from disk. Returns True if found."""
        centroid_path = os.path.join(speaker_dir, "centroid.npy")
        if os.path.isfile(centroid_path):
            self._centroid = np.load(centroid_path)
            logger.info("Loaded enrolled speaker centroid from %s", centroid_path)
            return True
        self._centroid = None
        return False

    def update_thresholds(self, threshold: float, high: float, low: float) -> None:
        self._threshold = threshold
        self._high_threshold = high
        self._low_threshold = low

    # --- Embedding extraction ---

    def extract_embedding(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        """Extract a 192-dim speaker embedding from audio.

        Args:
            audio: 1-D float32 array (mono, 16kHz expected)
            sample_rate: Sample rate of the audio

        Returns:
            np.ndarray of shape (192,)
        """
        if not self.is_ready:
            raise RuntimeError("Model not loaded. Call load_model() first.")
        waveform = torch.tensor(audio, dtype=torch.float32).unsqueeze(0)  # (1, T)
        with torch.no_grad():
            embedding = self._model.encode_batch(waveform)  # (1, 1, 192)
        return embedding.squeeze().cpu().numpy()  # (192,)

    # --- Enrollment ---

    def enroll(self, audio_samples: list[np.ndarray], speaker_dir: str,
               sample_rate: int = 16000) -> tuple[bool, str]:
        """Enroll a speaker from multiple audio samples.

        Returns:
            (success, message) tuple
        """
        if not self.is_ready:
            return False, "模型未加载"

        embeddings = []
        for i, audio in enumerate(audio_samples):
            emb = self.extract_embedding(audio, sample_rate)
            embeddings.append(emb)
            logger.info("Enrollment sample %d: embedding extracted", i + 1)

        emb_array = np.stack(embeddings)  # (N, 192)

        # Cross-validate: pairwise cosine similarity
        from numpy.linalg import norm
        for i in range(len(embeddings)):
            for j in range(i + 1, len(embeddings)):
                cos_sim = float(np.dot(emb_array[i], emb_array[j]) /
                                (norm(emb_array[i]) * norm(emb_array[j])))
                logger.info("Enrollment pairwise similarity [%d,%d]: %.4f", i, j, cos_sim)
                if cos_sim < self._threshold:
                    return False, f"样本 {i+1} 和 {j+1} 的声纹差异过大 (相似度: {cos_sim:.2f})，请在安静环境下重新录制"

        centroid = emb_array.mean(axis=0)  # (192,)

        # Save to disk
        os.makedirs(speaker_dir, exist_ok=True)
        np.save(os.path.join(speaker_dir, "embeddings.npy"), emb_array)
        np.save(os.path.join(speaker_dir, "centroid.npy"), centroid)

        metadata = {
            "sample_count": len(audio_samples),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "threshold": self._threshold,
        }
        with open(os.path.join(speaker_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        self._centroid = centroid
        logger.info("Speaker enrolled with %d samples", len(audio_samples))
        return True, "声纹注册成功"

    # --- Verification (two-tier) ---

    def verify(self, audio: np.ndarray, sample_rate: int = 16000) -> VerifyResult:
        """Two-tier speaker verification.

        Fast path: compare whole-audio embedding to centroid.
        Slow path: window-based segmentation + per-segment verification.
        """
        if not self.is_ready or not self.is_enrolled:
            return VerifyResult(audio=audio, is_user=True, score=1.0, path="bypass")

        # Fast path: whole-audio embedding
        emb = self.extract_embedding(audio, sample_rate)
        score = self._cosine_similarity(emb, self._centroid)
        logger.info("Speaker verify fast path: score=%.4f (high=%.2f, low=%.2f)",
                     score, self._high_threshold, self._low_threshold)

        if score >= self._high_threshold:
            return VerifyResult(audio=audio, is_user=True, score=score, path="fast_accept")

        if score <= self._low_threshold:
            return VerifyResult(audio=None, is_user=False, score=score, path="fast_reject")

        # Slow path: windowed segmentation
        logger.info("Speaker verify entering slow path (score=%.4f in ambiguous zone)", score)
        return self._slow_path(audio, sample_rate)

    def _slow_path(self, audio: np.ndarray, sample_rate: int) -> VerifyResult:
        """Windowed segmentation: split audio into overlapping windows,
        verify each, concatenate user segments."""
        window_sec = 2.0
        hop_sec = 1.0
        window_samples = int(window_sec * sample_rate)
        hop_samples = int(hop_sec * sample_rate)
        total_samples = len(audio)

        if total_samples < window_samples:
            # Audio too short for windowed analysis, use whole-audio score
            emb = self.extract_embedding(audio, sample_rate)
            score = self._cosine_similarity(emb, self._centroid)
            is_user = score >= self._threshold
            path = "slow_accept" if is_user else "slow_reject"
            return VerifyResult(
                audio=audio if is_user else None,
                is_user=is_user, score=score, path=path,
            )

        user_mask = np.zeros(total_samples, dtype=bool)
        max_score = -1.0

        pos = 0
        while pos + window_samples <= total_samples:
            segment = audio[pos:pos + window_samples]

            # Skip near-silent segments
            rms = float(np.sqrt(np.mean(segment ** 2)))
            if rms < 0.005:
                pos += hop_samples
                continue

            emb = self.extract_embedding(segment, sample_rate)
            score = self._cosine_similarity(emb, self._centroid)
            logger.debug("Slow path segment [%d:%d] score=%.4f rms=%.6f",
                         pos, pos + window_samples, score, rms)

            if score >= self._threshold:
                user_mask[pos:pos + window_samples] = True

            max_score = max(max_score, score)
            pos += hop_samples

        # Handle remaining tail segment
        if pos < total_samples and total_samples - pos >= int(0.5 * sample_rate):
            tail = audio[pos:]
            rms = float(np.sqrt(np.mean(tail ** 2)))
            if rms >= 0.005:
                emb = self.extract_embedding(tail, sample_rate)
                score = self._cosine_similarity(emb, self._centroid)
                if score >= self._threshold:
                    user_mask[pos:] = True
                max_score = max(max_score, score)

        if user_mask.any():
            filtered = audio[user_mask]
            logger.info("Slow path: kept %d/%d samples (%.1f%%)",
                        len(filtered), total_samples,
                        100.0 * len(filtered) / total_samples)
            return VerifyResult(audio=filtered, is_user=True, score=max_score, path="slow_accept")
        else:
            logger.info("Slow path: no user segments found (max_score=%.4f)", max_score)
            return VerifyResult(audio=None, is_user=False, score=max_score, path="slow_reject")

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a < 1e-9 or norm_b < 1e-9:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
```

**Step 2: Verify the module imports cleanly**

Run: `uv run --project E:\VoiceInput\.worktrees\speaker-verification python -c "from core.speaker_verifier import SpeakerVerifier, VerifyResult; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
git add core/speaker_verifier.py
git commit -m "feat: add SpeakerVerifier with two-tier verification (fast/slow path)"
```

---

### Task 4: Add STATE_FILTERED to overlay

**Files:**
- Modify: `ui/overlay_window.py:19-24` (add state constant)
- Modify: `ui/overlay_window.py:177-211` (add state handling in `set_state`)
- Modify: `ui/styles.py:33-38` (add color constant)

**Step 1: Add COLOR_FILTERED to styles.py**

In `ui/styles.py`, add after the line `COLOR_ERROR = "#f38ba8"` (line 37):

```python
COLOR_FILTERED = "#6c7086"     # Muted grey for silent filter
```

**Step 2: Add STATE_FILTERED constant to overlay_window.py**

In `ui/overlay_window.py`, add after `STATE_ERROR = "error"` (line 24):

```python
STATE_FILTERED = "filtered"
```

**Step 3: Import COLOR_FILTERED in overlay_window.py**

Update the import from `ui.styles` to include `COLOR_FILTERED`:

```python
from ui.styles import (
    COLOR_BORDER, COLOR_ERROR, COLOR_FILTERED, COLOR_OVERLAY_BG, COLOR_OVERLAY_TEXT,
    COLOR_RECORDING, COLOR_RECOGNIZING, COLOR_RESULT, FONT_FAMILY,
)
```

**Step 4: Handle STATE_FILTERED in set_state()**

In `ui/overlay_window.py`, inside `set_state()`, add a new `elif` block after the `STATE_ERROR` block (after line 211):

```python
        elif state == STATE_FILTERED:
            self._label.setStyleSheet(f"color: {COLOR_FILTERED}; background: transparent;")
            self._label.setText("已过滤")
            QTimer.singleShot(1000, self.hide)  # Shorter display for filtered
```

**Step 5: Update the import in ui/app.py**

In `ui/app.py`, update the overlay import (line 20-23) to include `STATE_FILTERED`:

```python
from ui.overlay_window import (
    OverlayWindow, STATE_RECORDING, STATE_RECOGNIZING,
    STATE_RESULT, STATE_ERROR, STATE_FILTERED, STATE_IDLE,
)
```

**Step 6: Verify import**

Run: `uv run --project E:\VoiceInput\.worktrees\speaker-verification python -c "from ui.overlay_window import STATE_FILTERED; print(STATE_FILTERED)"`

Expected: `filtered`

**Step 7: Commit**

```bash
git add ui/styles.py ui/overlay_window.py ui/app.py
git commit -m "feat: add STATE_FILTERED overlay state for speaker verification"
```

---

### Task 5: Integrate SpeakerVerifier into main.py and app.py

**Files:**
- Modify: `main.py:49-66` (add speaker verifier loading)
- Modify: `main.py:69-104` (pass verifier to MoShengApp)
- Modify: `ui/app.py:37-44` (WorkerThread accepts verifier)
- Modify: `ui/app.py:77-102` (add verification in _handle_stop)
- Modify: `ui/app.py:105-142` (MoShengApp accepts and wires verifier)
- Modify: `ui/app.py:220-237` (_apply_settings updates verifier thresholds)

**Step 1: Add load_speaker_verifier function in main.py**

Add after the `load_asr_engine` function (after line 66):

```python
def load_speaker_verifier(settings: SettingsManager):
    """Load speaker verification model if enabled."""
    from config import SPEAKER_DIR

    enabled = settings.get("speaker_verification", "enabled", default=False)
    if not enabled:
        print("声纹识别未启用，跳过模型加载。")
        return None

    from core.speaker_verifier import SpeakerVerifier

    device = settings.get("asr", "device", default="cuda:0")
    verifier = SpeakerVerifier(device=device)

    threshold = settings.get("speaker_verification", "threshold", default=0.25)
    high = settings.get("speaker_verification", "high_threshold", default=0.40)
    low = settings.get("speaker_verification", "low_threshold", default=0.10)
    verifier.update_thresholds(threshold, high, low)

    print("正在加载声纹识别模型...")
    verifier.load_model()
    verifier.load_enrollment(SPEAKER_DIR)
    print("声纹识别模型加载完成！")
    return verifier
```

**Step 2: Call load_speaker_verifier in main()**

In `main()`, after `asr_engine = load_asr_engine(settings)` (line 78), add:

```python
    speaker_verifier = load_speaker_verifier(settings)
    if speaker_verifier:
        atexit.register(speaker_verifier.unload_model)
```

And update the MoShengApp construction (line 99) to pass the verifier:

```python
    app = MoShengApp(asr_engine=asr_engine, settings=settings,
                     speaker_verifier=speaker_verifier)
```

**Step 3: Update WorkerThread to accept verifier**

In `ui/app.py`, update `WorkerThread.__init__` to accept an optional verifier:

```python
    def __init__(self, recorder: AudioRecorder, asr: ASRBase,
                 injector: TextInjector, settings: SettingsManager,
                 speaker_verifier=None):
        super().__init__()
        self._recorder = recorder
        self._asr = asr
        self._injector = injector
        self._settings = settings
        self._speaker_verifier = speaker_verifier
        self._cmd_queue: queue.Queue[str] = queue.Queue()
        self._hotword_context: str = ""
```

**Step 4: Add verification step in _handle_stop**

In `ui/app.py`, in `_handle_stop()`, insert the verification step after the min_duration check (after line 88) and before the `STATE_RECOGNIZING` emit (line 90):

```python
        # Speaker verification (if enabled and enrolled)
        if (self._speaker_verifier is not None
                and self._settings.get("speaker_verification", "enabled", default=False)):
            try:
                result = self._speaker_verifier.verify(audio, self._recorder.sample_rate)
                if not result.is_user:
                    logger.info("Speaker filtered: path=%s, score=%.4f", result.path, result.score)
                    self.state_changed.emit(STATE_FILTERED, "")
                    return
                if result.audio is not None:
                    audio = result.audio
            except Exception:
                logger.exception("Speaker verification failed, proceeding with ASR")
```

**Step 5: Update MoShengApp to accept and wire verifier**

In `ui/app.py`, update `MoShengApp.__init__` signature:

```python
    def __init__(self, asr_engine: ASRBase, settings: SettingsManager,
                 speaker_verifier=None):
```

Store the verifier reference (after `self._injector` initialization):

```python
        self._speaker_verifier = speaker_verifier
```

Pass verifier to WorkerThread:

```python
        self._worker = WorkerThread(
            self._recorder, asr_engine, self._injector, settings,
            speaker_verifier=speaker_verifier,
        )
```

**Step 6: Update _apply_settings for verifier thresholds**

In `ui/app.py`, in `_apply_settings()`, add at the end (before the logger.info line):

```python
        if self._speaker_verifier is not None:
            self._speaker_verifier.update_thresholds(
                self._settings.get("speaker_verification", "threshold", default=0.25),
                self._settings.get("speaker_verification", "high_threshold", default=0.40),
                self._settings.get("speaker_verification", "low_threshold", default=0.10),
            )
```

**Step 7: Commit**

```bash
git add main.py ui/app.py
git commit -m "feat: integrate speaker verification into recording pipeline"
```

---

### Task 6: Add speaker verification section to settings UI

**Files:**
- Modify: `ui/settings_window.py:79-294` (_build_ui — add speaker verification section)
- Modify: `ui/settings_window.py:400-429` (_on_save_click — save speaker verification settings)
- Modify: `ui/styles.py:462-529` (draw_section_icon — add "shield" icon)

**Step 1: Add "shield" icon to draw_section_icon in styles.py**

In `ui/styles.py`, inside `draw_section_icon()`, add a new `elif` before the final `p.end()`:

```python
    elif name == "shield":
        cx = s / 2
        path = QPainterPath()
        path.moveTo(cx, s * 0.08)
        path.lineTo(s * 0.88, s * 0.28)
        path.quadTo(s * 0.88, s * 0.62, cx, s * 0.92)
        path.quadTo(s * 0.12, s * 0.62, s * 0.12, s * 0.28)
        path.closeSubpath()
        p.drawPath(path)
        # Checkmark inside shield
        p.drawLine(QPointF(cx - s * 0.15, s * 0.50), QPointF(cx - s * 0.02, s * 0.63))
        p.drawLine(QPointF(cx - s * 0.02, s * 0.63), QPointF(cx + s * 0.18, s * 0.38))
```

**Step 2: Add speaker verification section in _build_ui**

In `ui/settings_window.py`, in `_build_ui()`, add a new section after the "音频输入" section (after `main_layout.addWidget(mic_group)`, line 224) and before the "输出设置" section:

```python
        # --- Speaker Verification Section ---
        sv_group = IconGroupBox("声纹识别", "shield")
        sv_layout = QVBoxLayout(sv_group)
        sv_layout.setSpacing(10)

        self._sv_toggle = ToggleSwitch(
            "启用声纹验证",
            checked=s.get("speaker_verification", "enabled", default=False),
        )
        sv_layout.addWidget(self._sv_toggle)

        sv_hint = QLabel("注册声纹后，将自动过滤其他人的语音输入")
        sv_hint.setObjectName("secondaryLabel")
        sv_hint.setWordWrap(True)
        sv_layout.addWidget(sv_hint)

        sv_btn_row = QHBoxLayout()
        self._sv_status_label = QLabel(self._get_enrollment_status())
        self._sv_status_label.setObjectName("secondaryLabel")
        sv_btn_row.addWidget(self._sv_status_label)
        sv_btn_row.addStretch()
        self._enroll_btn = QPushButton("录制声纹")
        self._enroll_btn.clicked.connect(self._open_enrollment)
        sv_btn_row.addWidget(self._enroll_btn)
        sv_layout.addLayout(sv_btn_row)

        main_layout.addWidget(sv_group)
```

**Step 3: Add enrollment status helper**

Add a method to `SettingsWindow`:

```python
    def _get_enrollment_status(self) -> str:
        from config import SPEAKER_DIR
        import os
        centroid_path = os.path.join(SPEAKER_DIR, "centroid.npy")
        if os.path.isfile(centroid_path):
            meta_path = os.path.join(SPEAKER_DIR, "metadata.json")
            if os.path.isfile(meta_path):
                try:
                    import json
                    with open(meta_path, encoding="utf-8") as f:
                        meta = json.load(f)
                    return f"已注册 ({meta.get('sample_count', '?')} 个样本)"
                except Exception:
                    pass
            return "已注册"
        return "未注册声纹"
```

**Step 4: Add _open_enrollment stub**

Add a method stub (will be implemented in Task 7):

```python
    def _open_enrollment(self) -> None:
        from ui.enrollment_dialog import EnrollmentDialog
        dialog = EnrollmentDialog(self._settings, parent=self)
        if dialog.exec():
            self._sv_status_label.setText(self._get_enrollment_status())
```

**Step 5: Save speaker verification settings in _on_save_click**

In `_on_save_click()`, add before `self._settings.save()`:

```python
            self._settings.set("speaker_verification", "enabled", self._sv_toggle.isChecked())
```

**Step 6: Commit**

```bash
git add ui/styles.py ui/settings_window.py
git commit -m "feat: add speaker verification section to settings UI"
```

---

### Task 7: Create EnrollmentDialog

**Files:**
- Create: `ui/enrollment_dialog.py`

**Step 1: Write the EnrollmentDialog**

Create `ui/enrollment_dialog.py`:

```python
"""Guided speaker enrollment dialog for recording voice samples."""

import logging
import os
import threading

import numpy as np
from PySide6.QtCore import QTimer, Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox,
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

        # Auto-stop after MAX_DURATION_SEC
        QTimer.singleShot(int(MAX_DURATION_SEC * 1000), self._auto_stop)

    def _auto_stop(self) -> None:
        if self._is_recording:
            self._stop_recording()

    def _stop_recording(self) -> None:
        if not self._is_recording:
            return
        self._is_recording = False
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
            # Read recent buffer for RMS level
            import threading
            with self._recorder._lock:
                if self._recorder._buffer:
                    recent = self._recorder._buffer[-1]
                    rms = float(np.sqrt(np.mean(recent ** 2)))
                    level = min(100, int(rms * 500))
                    self._level_bar.setValue(level)

    def closeEvent(self, event) -> None:
        if self._is_recording and self._recorder:
            self._recorder.stop_recording()
        super().closeEvent(event)
```

**Step 2: Verify the module imports**

Run: `uv run --project E:\VoiceInput\.worktrees\speaker-verification python -c "from ui.enrollment_dialog import EnrollmentDialog; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
git add ui/enrollment_dialog.py
git commit -m "feat: add guided speaker enrollment dialog"
```

---

### Task 8: Manual integration test

**Step 1: Run the application**

Run: `uv run --project E:\VoiceInput\.worktrees\speaker-verification python E:\VoiceInput\.worktrees\speaker-verification\main.py`

Verify:
- App starts normally (声纹识别未启用, verifier not loaded)
- Open settings → "声纹识别" section visible
- Shows "未注册声纹" status
- Toggle and "录制声纹" button present

**Step 2: Test enrollment flow**

1. Click "录制声纹" button
2. Enrollment dialog opens with glassmorphism backdrop
3. Record 3 samples following the prompts (3+ seconds each)
4. Volume bar shows real-time level
5. After 3 samples, processing runs
6. "声纹注册成功" message appears
7. Settings shows "已注册 (3 个样本)"

**Step 3: Enable verification and test**

1. Toggle "启用声纹验证" on
2. Save settings
3. Close and reopen the app (model needs to load at startup)
4. Press hotkey and speak — should recognize and paste text normally
5. Have someone else speak (or play audio from a different person) — should show "已过滤" in overlay

**Step 4: Verify fail-open behavior**

- Disable speaker verification → app works as before
- Delete `~/.mosheng/speaker/` directory → verification skipped, ASR works normally

**Step 5: Commit final state**

```bash
git add -A
git commit -m "feat: speaker verification integration complete"
```
