"""Synthesized audio feedback for recording start/stop events."""
import logging
import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100

def _make_bell(freq: float, duration: float) -> np.ndarray:
    """2-partial bell tone with exponential decay."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    # Fundamental + upper partial at 2.756x ratio with 3x faster decay
    decay1 = np.exp(-4 * t / duration)
    decay2 = np.exp(-12 * t / duration)
    wave = 0.7 * np.sin(2 * np.pi * freq * t) * decay1
    wave += 0.3 * np.sin(2 * np.pi * freq * 2.756 * t) * decay2
    # Apply short attack (5ms)
    attack_samples = int(0.005 * SAMPLE_RATE)
    wave[:attack_samples] *= np.linspace(0, 1, attack_samples)
    return (wave * 0.6).astype(np.float32)

def _make_chime_tone(freq: float, duration: float) -> np.ndarray:
    """Single chime tone with smooth decay."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    decay = np.exp(-5 * t / duration)
    wave = np.sin(2 * np.pi * freq * t) * decay
    attack_samples = int(0.003 * SAMPLE_RATE)
    wave[:attack_samples] *= np.linspace(0, 1, attack_samples)
    return (wave * 0.5).astype(np.float32)

def _make_chime_sequence(freqs: list, duration: float, gap: float) -> np.ndarray:
    """Ascending or descending chime sequence."""
    gap_samples = int(gap * SAMPLE_RATE)
    total_samples = int((duration + gap * (len(freqs) - 1)) * SAMPLE_RATE) + gap_samples
    result = np.zeros(total_samples, dtype=np.float32)
    for i, freq in enumerate(freqs):
        tone = _make_chime_tone(freq, duration)
        offset = i * gap_samples
        end = offset + len(tone)
        if end > len(result):
            tone = tone[:len(result) - offset]
        result[offset:offset + len(tone)] += tone
    # Normalize
    peak = np.max(np.abs(result))
    if peak > 0.8:
        result = result / peak * 0.8
    return result

def _make_soft(freq: float, duration: float) -> np.ndarray:
    """Soft tone with trapezoid envelope."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    n = len(t)
    envelope = np.ones(n)
    attack = int(0.05 * n)
    release = int(0.3 * n)
    envelope[:attack] = np.linspace(0, 1, attack)
    envelope[n - release:] = np.linspace(1, 0, release)
    wave = np.sin(2 * np.pi * freq * t) * envelope
    return (wave * 0.35).astype(np.float32)


SILENCE = np.zeros(int(0.1 * SAMPLE_RATE), dtype=np.float32)


class SoundPlayer:
    """Plays synthesized notification sounds for recording feedback."""

    STYLES = ("bell", "chime", "soft", "off")

    def __init__(self, style: str = "bell"):
        self._style = style if style in self.STYLES else "bell"
        self._sounds: dict[str, dict[str, np.ndarray]] = {}
        self._pregenerate()

    def _pregenerate(self) -> None:
        """Pre-generate all sounds at construction time for zero-latency playback."""
        # Bell: A5=880Hz start, E5=659Hz stop
        self._sounds["bell"] = {
            "start": _make_bell(880.0, 0.55),
            "stop": _make_bell(659.25, 0.55),
        }
        # Chime: D6=1174Hz->G6=1568Hz ascending start; G5=784Hz->D5=587Hz descending stop
        self._sounds["chime"] = {
            "start": _make_chime_sequence([1174.66, 1567.98], 0.35, 0.09),
            "stop": _make_chime_sequence([783.99, 587.33], 0.35, 0.09),
        }
        # Soft: C6=1046Hz start, G5=784Hz stop
        self._sounds["soft"] = {
            "start": _make_soft(1046.50, 0.28),
            "stop": _make_soft(783.99, 0.28),
        }
        # Off: silence
        self._sounds["off"] = {
            "start": SILENCE,
            "stop": SILENCE,
        }

    @property
    def style(self) -> str:
        return self._style

    @style.setter
    def style(self, value: str) -> None:
        if value in self.STYLES:
            self._style = value

    def play_start(self) -> None:
        self._play("start")

    def play_stop(self) -> None:
        self._play("stop")

    def _play(self, event: str) -> None:
        try:
            audio = self._sounds[self._style][event]
            sd.play(audio, samplerate=SAMPLE_RATE, blocking=False)
        except Exception as e:
            logger.debug("Sound playback failed: %s", e)
