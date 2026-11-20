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
        self._stream_lock = threading.Lock()
        self._recording = False
        self._current_rms: float = 0.0
        self._smoothed_rms: float = 0.0
        self._rms_alpha: float = 0.6  # EMA smoothing factor (higher = more responsive)
        # Ring buffer for FFT: keeps last 2048 samples (~128ms @ 16kHz)
        self._recent = np.zeros(2048, dtype=np.float32)
        self._recent_pos: int = 0
        self._vad_block = 0

    @property
    def is_recording(self) -> bool:
        return self._recording

    def check_device(self) -> None:
        sd.check_input_settings(device=self._device, channels=self._channels,
                                dtype="float32", samplerate=self._sample_rate)

    def start_recording(self) -> None:
        with self._stream_lock:
            if self._recording:
                return
            stream = sd.InputStream(
                samplerate=self._sample_rate, channels=self._channels, dtype="float32",
                device=self._device, callback=self._audio_callback,
            )
            with self._lock:
                self._buffer.clear()
                self._smoothed_rms = self._current_rms = 0.0
                self._vad_block = 0
                # PortAudio can deliver the first block inside start().
                self._stream = stream
            try:
                stream.start()
            except Exception:
                with self._lock:
                    self._stream = None
                    self._buffer.clear()
                stream.close()
                raise
            self._recording = True
        logger.info("Recording started (sr=%d)", self._sample_rate)

    def stop_recording(self) -> np.ndarray | None:
        with self._stream_lock:
            if not self._recording:
                return None
            with self._lock:
                self._recording = False
                stream, self._stream = self._stream, None
            try:
                try:
                    stream.stop()
                finally:
                    stream.close()
            except Exception:
                with self._lock:
                    self._buffer.clear()
                    self._vad_block = 0
                raise
            return self.drain_buffer()

    def drain_buffer(self) -> np.ndarray | None:
        """Return accumulated audio and clear the buffer without stopping the stream."""
        with self._lock:
            if not self._buffer:
                return None
            blocks, self._buffer = self._buffer, []
            self._vad_block = 0
        audio = np.concatenate(blocks, axis=0).reshape(-1)
        duration = len(audio) / self._sample_rate
        logger.info("Buffer drained: %.2fs, %d samples", duration, len(audio))
        return audio

    def _audio_callback(self, indata: np.ndarray, frames: int,
                        time_info, status) -> None:
        if status:
            logger.warning("Audio callback status: %s", status)
        with self._lock:
            if self._stream is not None:
                self._buffer.append(indata.copy())
                self._current_rms = float(np.sqrt(np.mean(indata ** 2)))
                self._smoothed_rms = (self._rms_alpha * self._current_rms
                                      + (1 - self._rms_alpha) * self._smoothed_rms)
                # Update ring buffer for FFT
                flat = indata[:, 0] if indata.ndim > 1 else indata.flatten()
                n = len(flat)
                pos = self._recent_pos
                buf_len = len(self._recent)
                if n >= buf_len:
                    self._recent[:] = flat[-buf_len:]
                    self._recent_pos = 0
                    return
                if pos + n <= buf_len:
                    self._recent[pos:pos + n] = flat
                else:
                    first = buf_len - pos
                    self._recent[pos:] = flat[:first]
                    self._recent[:n - first] = flat[first:]
                self._recent_pos = (pos + n) % buf_len

    @property
    def device(self) -> int | None:
        return self._device

    @device.setter
    def device(self, value: int | None) -> None:
        self._device = value

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def get_recent_samples(self, n_samples: int = 1024) -> np.ndarray:
        """Return a consistent snapshot of the most recent samples."""
        with self._lock:
            pos = self._recent_pos
            buf = self._recent
            if pos >= n_samples:
                return buf[pos - n_samples:pos].copy()
            return np.concatenate([buf[-(n_samples - pos):], buf[:pos]])

    def get_new_samples(self) -> np.ndarray | None:
        """Return unprocessed audio samples since last call (for VAD).

        Returns None if no new samples are available.
        """
        with self._lock:
            end = len(self._buffer)
            if end == self._vad_block:
                return None
            blocks = self._buffer[self._vad_block:end]
            self._vad_block = end
        return np.concatenate(blocks, axis=0).reshape(-1)

    @property
    def current_rms(self) -> float:
        with self._lock:
            return self._smoothed_rms
