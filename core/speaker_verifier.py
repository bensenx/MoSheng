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
        # Compatibility: speechbrain calls torchaudio.list_audio_backends()
        # which was removed in torchaudio 2.10+
        import torchaudio
        if not hasattr(torchaudio, "list_audio_backends"):
            torchaudio.list_audio_backends = lambda: ["soundfile"]

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
            from i18n import tr
            return False, tr("verifier.model_not_loaded")

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
                    from i18n import tr
                    return False, tr("verifier.samples_too_different", i=i+1, j=j+1, score=f"{cos_sim:.2f}")

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
        from i18n import tr
        return True, tr("verifier.enrollment_success")

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
