"""Qwen3-ASR engine implementation."""

import logging
import time

import numpy as np
import torch

from core.asr_base import ASRBase

logger = logging.getLogger(__name__)


class QwenASREngine(ASRBase):
    def __init__(self, model_id: str = "Qwen/Qwen3-ASR-1.7B",
                 device: str = "cuda:0", dtype: str = "bfloat16",
                 max_new_tokens: int = 256):
        self._model_id = model_id
        self._device = device
        self._dtype = getattr(torch, dtype, torch.bfloat16)
        self._max_new_tokens = max_new_tokens
        self._model = None

    @staticmethod
    def get_name() -> str:
        return "Qwen3-ASR-1.7B"

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    def load_model(self) -> None:
        logger.info("Loading Qwen3-ASR model: %s on %s", self._model_id, self._device)
        t0 = time.time()

        from qwen_asr import Qwen3ASRModel
        self._model = Qwen3ASRModel.from_pretrained(
            self._model_id,
            dtype=self._dtype,
            device_map=self._device,
            max_new_tokens=self._max_new_tokens,
        )

        elapsed = time.time() - t0
        logger.info("Model loaded in %.1fs", elapsed)

        # Warmup with a short silent audio to ensure first real inference is fast
        logger.info("Warming up model...")
        dummy = np.zeros(16000, dtype=np.float32)  # 1 second of silence
        self._model.transcribe(audio=(dummy, 16000), language=None)
        logger.info("Warmup complete")

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000,
                   context: str = "") -> str:
        if not self.is_ready:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        rms = float(np.sqrt(np.mean(audio ** 2)))
        peak = float(np.max(np.abs(audio)))
        logger.info("Audio stats: samples=%d, rms=%.6f, peak=%.6f", len(audio), rms, peak)
        if context:
            logger.info("Using hotword context: %s", context[:80])

        t0 = time.time()
        results = self._model.transcribe(
            audio=(audio, sample_rate),
            language=None,
            context=context,
        )
        elapsed = time.time() - t0

        text = results[0].text if results else ""
        lang = results[0].language if results else ""
        logger.info("Transcribed in %.2fs (lang=%s): %s", elapsed, lang, text[:80])
        return text

    def unload_model(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("Model unloaded")
