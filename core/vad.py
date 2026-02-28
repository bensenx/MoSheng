"""Silero VAD wrapper for voice activity detection."""

import logging

import numpy as np
import torch

logger = logging.getLogger(__name__)


class SileroVAD:
    """Silero VAD V5 wrapper. 512 samples per chunk at 16kHz."""

    _THRESHOLD = 0.5
    _CHUNK_SIZE = 512  # V5: fixed 512 samples at 16kHz (32ms)
    _SAMPLE_RATE = 16000

    def __init__(self):
        self._model = None

    @property
    def chunk_size(self) -> int:
        return self._CHUNK_SIZE

    def load_model(self) -> None:
        """Load Silero VAD model via torch.hub (downloads ~2MB on first call)."""
        self._model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
        self._model.eval()
        logger.info("Silero VAD loaded (CPU, threshold=%.2f)", self._THRESHOLD)

    def reset_states(self) -> None:
        """Reset LSTM hidden states. Call before each recording session."""
        if self._model is not None:
            self._model.reset_states()

    def process_chunk(self, audio: np.ndarray) -> float:
        """Process a 512-sample chunk and return speech probability (0.0–1.0)."""
        tensor = torch.from_numpy(audio).float()
        with torch.no_grad():
            prob = self._model(tensor, self._SAMPLE_RATE).item()
        return prob

    def is_speech(self, audio: np.ndarray) -> bool:
        """Return True if the 512-sample chunk contains speech."""
        return self.process_chunk(audio) >= self._THRESHOLD

    def unload(self) -> None:
        """Release model resources."""
        self._model = None
        logger.info("Silero VAD unloaded")
