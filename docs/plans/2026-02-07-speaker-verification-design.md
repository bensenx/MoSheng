# Speaker Verification (声纹识别) Design

Date: 2026-02-07

## Goal

Let MoSheng silently filter out non-user speech. When other people's voices are captured by the microphone, the system discards their audio and only sends the user's speech to ASR. No intrusive alerts — overlay briefly shows "已过滤" when audio is discarded.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Mode | Silent filter | Non-intrusive; suits noisy environments |
| Enrollment | Guided recording (3 samples) | Reliable; user controls quality |
| Model | SpeechBrain ECAPA-TDNN | Mature, PyTorch ecosystem, GPU support, ~30MB VRAM |
| Diarization | SpeechBrain diarization pipeline | Same ecosystem, reuses ECAPA embeddings |
| Strategy | Two-tier (fast path + slow path) | Common case ~50-100ms; diarization only when needed |
| Storage | `~/.mosheng/speaker/` | Consistent with existing `~/.mosheng/` layout |
| Failure behavior | Fail-open (proceed to ASR) | Never block user due to verifier error |

## Architecture

### Verification Flow (Two-Tier Strategy)

```
Audio recorded (np.ndarray, 16kHz, float32)
  │
  ├─ Speaker verification disabled OR not enrolled → Direct to ASR
  │
  └─ Enabled + enrolled →
      │
      ① Fast path: whole-audio embedding extraction + comparison (~50-100ms)
      │   cosine_similarity(audio_emb, centroid)
      │   → ≥ high_threshold (0.40) → Direct to ASR ✓
      │   → ≤ low_threshold  (0.10) → Silent filter, overlay "已过滤" ✗
      │   → In between → Enter slow path ↓
      │
      ② Slow path: Diarization + per-segment verification (~500ms-2s)
          → Segment audio: [(start, end, speaker_id), ...]
          → Extract embedding per segment, compare to centroid
          → Concatenate segments with similarity ≥ threshold
          → Has user segments → Concatenated audio to ASR ✓
          → No user segments → Overlay "已过滤" ✗
```

### Enrollment Flow

```
EnrollmentDialog opens
  │
  ① Show instructions: "请在安静环境下录制 3 段语音样本"
  │
  ② Loop 3 times:
  │   → Display prompt text (e.g. "请朗读：今天天气真不错")
  │   → User clicks "开始录制", records 3-8 seconds
  │   → Show real-time volume meter
  │   → Extract embedding, show ✓
  │
  ③ All 3 done → compute mean embedding
  │   → Cross-validate: pairwise similarity ≥ threshold
  │   → Pass → Save to ~/.mosheng/speaker/
  │   → Fail → "录音质量不一致，请重新录制"
  │
  ④ Show "声纹注册成功"
```

### Data Storage

```
~/.mosheng/speaker/
  embeddings.npy    # shape: (N, 192), individual sample embeddings
  centroid.npy      # shape: (192,), mean embedding for fast comparison
  metadata.json     # {"created": "...", "sample_count": 3, "threshold": 0.25}
```

## New Files

| File | Responsibility |
|------|----------------|
| `core/speaker_verifier.py` | Load ECAPA-TDNN, extract embeddings, two-tier verify flow (fast path + diarization), concatenate user segments |
| `ui/enrollment_dialog.py` | Guided enrollment dialog, reuse AudioRecorder, call speaker_verifier for embedding extraction |

## Modified Files

| File | Changes |
|------|---------|
| `main.py` | Load speaker verifier model at startup (alongside ASR) |
| `config.py` | Add `speaker_verification` default settings |
| `ui/app.py` | Insert verification step in `WorkerThread._handle_stop()` before ASR; `MoShengApp` holds verifier reference |
| `ui/settings_window.py` | Add "声纹识别" settings section (toggle, threshold slider, record/re-record button, status display) |
| `ui/overlay_window.py` | Add `STATE_FILTERED` state style |
| `pyproject.toml` | Add `speechbrain` dependency |

## Settings

```python
"speaker_verification": {
    "enabled": False,           # Toggle on/off
    "threshold": 0.25,          # Per-segment verification threshold
    "high_threshold": 0.40,     # Fast path: direct pass
    "low_threshold": 0.10,      # Fast path: direct reject
}
```

- `enabled`, `threshold`, `high_threshold`, `low_threshold` → hot-reloadable
- Model loading → requires restart

## SpeechBrain Models

- **Embedding**: `speechbrain/spkrec-ecapa-voxceleb` (ECAPA-TDNN, VoxCeleb pretrained)
- **Diarization**: `speechbrain/diarization-ecapa-tdnn` (same architecture, reuses embeddings)
- **VRAM**: ~30MB (negligible vs Qwen3-ASR-1.7B ~3.5GB)

## Performance

| Scenario | Added latency | Path |
|----------|---------------|------|
| Only user speaking (common) | ~50-100ms | Fast path |
| Mixed voices (uncommon) | ~500ms-2s | Slow path (diarization) |
| Feature disabled | 0ms | Bypass |

## Error Handling

- Verifier model fails to load → log warning, feature disabled, ASR works normally
- Verification throws exception → log error, fail-open (proceed to ASR)
- No enrolled voiceprint → skip verification, proceed to ASR
