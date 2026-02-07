"""ASR engine abstract base class."""

from abc import ABC, abstractmethod

import numpy as np


class ASRBase(ABC):
    """Abstract base class for ASR engines. Subclass to add new models."""

    @abstractmethod
    def load_model(self) -> None:
        """Load model into memory/GPU."""

    @abstractmethod
    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe audio numpy array to text."""

    @abstractmethod
    def unload_model(self) -> None:
        """Release model resources."""

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        """Whether the model is loaded and ready for inference."""

    @staticmethod
    @abstractmethod
    def get_name() -> str:
        """Display name for settings UI."""
