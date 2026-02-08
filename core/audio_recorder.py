"""Microphone audio recording using sounddevice."""

import logging
import threading

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


class AudioRecorder:
    def __init__(self, sample_rate: int = 16000, channels: int = 1,
                 device: int | None = None):
        self._sample_rate = sample_rate
        self._channels = channels
        self._device = device
        self._buffer: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start_recording(self) -> None:
        with self._lock:
            if self._recording:
                return
            self._buffer.clear()
            self._recording = True

        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
            device=self._device,
            callback=self._audio_callback,
        )
        self._stream.start()
        logger.info("Recording started (sr=%d)", self._sample_rate)

    def stop_recording(self) -> np.ndarray | None:
        with self._lock:
            if not self._recording:
                return None
            self._recording = False

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        with self._lock:
            if not self._buffer:
                return None
            audio = np.concatenate(self._buffer, axis=0).flatten()
            self._buffer.clear()

        duration = len(audio) / self._sample_rate
        logger.info("Recording stopped: %.2fs, %d samples", duration, len(audio))
        return audio

    def _audio_callback(self, indata: np.ndarray, frames: int,
                        time_info, status) -> None:
        if status:
            logger.warning("Audio callback status: %s", status)
        with self._lock:
            if self._recording:
                self._buffer.append(indata.copy())

    @property
    def device(self) -> int | None:
        return self._device

    @device.setter
    def device(self, value: int | None) -> None:
        self._device = value

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def recent_rms(self) -> float:
        """Return RMS of the most recent audio chunk, or 0.0 if none available."""
        with self._lock:
            if self._buffer:
                return float(np.sqrt(np.mean(self._buffer[-1] ** 2)))
        return 0.0
