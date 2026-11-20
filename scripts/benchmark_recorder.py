"""Measure cumulative VAD buffer read time at 16 kHz with 50 ms callbacks."""

from pathlib import Path
from statistics import median
import sys
from time import perf_counter_ns
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.audio_recorder import AudioRecorder


def measure(seconds: int) -> float:
    recorder = AudioRecorder()
    block = np.zeros((800, 1), dtype=np.float32)
    elapsed = 0
    with patch("core.audio_recorder.sd.InputStream"):
        recorder.start_recording()
        for _ in range(seconds * 20):
            recorder._audio_callback(block, len(block), None, None)
            start = perf_counter_ns()
            samples = recorder.get_new_samples()
            elapsed += perf_counter_ns() - start
            assert samples is not None and len(samples) == len(block)
        recorder.stop_recording()
    return elapsed / 1_000_000


if __name__ == "__main__":
    for duration in (5, 30, 60):
        milliseconds = median(measure(duration) for _ in range(5))
        print(f"{duration:2}s of audio: {milliseconds:.3f} ms of buffer reads")
