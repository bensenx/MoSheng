#!/usr/bin/env python3
"""Benchmark Qwen3-ASR models (0.6B vs 1.7B) on Apple Silicon.

Generates a markdown report with load times, inference speed, memory usage,
and transcription accuracy for both models across multiple test cases.

Usage:
    uv run python scripts/benchmark_models.py [--device mps|cpu] [--output results/benchmark.md]
"""

import argparse
import gc
import json
import os
import platform
import subprocess
import sys
import time

import numpy as np
import torch

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Test sentences — recorded via TTS or synthesized silence + real audio
# We generate synthetic audio for reproducibility, but also time with
# real microphone recordings if available.
# ---------------------------------------------------------------------------

MODELS = [
    {"name": "Qwen3-ASR-0.6B", "model_id": "Qwen/Qwen3-ASR-0.6B"},
    {"name": "Qwen3-ASR-1.7B", "model_id": "Qwen/Qwen3-ASR-1.7B"},
]

# Durations in seconds to benchmark inference scaling
AUDIO_DURATIONS = [1.0, 2.0, 3.0, 5.0, 10.0]

# Number of inference runs per duration for stable timing
WARMUP_RUNS = 2
BENCH_RUNS = 3


def get_system_info() -> dict:
    """Collect system information for the report."""
    info = {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "torch": torch.__version__,
    }

    # macOS chip info
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=5,
        )
        info["cpu"] = result.stdout.strip()
    except Exception:
        info["cpu"] = platform.processor()

    # RAM
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True, text=True, timeout=5,
        )
        info["ram_gb"] = int(result.stdout.strip()) / (1024**3)
    except Exception:
        info["ram_gb"] = 0

    # MPS availability
    info["mps_available"] = (
        hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    )

    return info


def get_memory_usage_mb() -> float:
    """Get current process RSS in MB."""
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    except Exception:
        return 0.0


def generate_test_audio(duration: float, sr: int = 16000) -> np.ndarray:
    """Generate a synthetic audio signal (tone + noise) for benchmarking.

    Not meaningful for accuracy testing, but gives consistent inference load.
    """
    t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
    # Mix of tones to simulate speech-like spectral content
    signal = (
        0.3 * np.sin(2 * np.pi * 200 * t)
        + 0.2 * np.sin(2 * np.pi * 500 * t)
        + 0.1 * np.sin(2 * np.pi * 1200 * t)
        + 0.05 * np.random.randn(len(t)).astype(np.float32)
    )
    return signal / np.max(np.abs(signal)) * 0.8


def find_real_audio_files() -> list[dict]:
    """Look for .wav files in a test_audio/ directory for accuracy testing."""
    audio_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "test_audio",
    )
    results = []
    if not os.path.isdir(audio_dir):
        return results

    for fname in sorted(os.listdir(audio_dir)):
        if not fname.endswith(".wav"):
            continue
        json_path = os.path.join(audio_dir, fname.replace(".wav", ".json"))
        expected = ""
        if os.path.isfile(json_path):
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
                expected = data.get("expected", "")

        results.append({
            "path": os.path.join(audio_dir, fname),
            "name": fname,
            "expected": expected,
        })
    return results


def load_wav(path: str) -> tuple[np.ndarray, int]:
    """Load a WAV file as float32 numpy array."""
    import wave
    with wave.open(path, "rb") as wf:
        sr = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
        dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
        sample_width = wf.getsampwidth()
        audio = np.frombuffer(raw, dtype=dtype_map.get(sample_width, np.int16))
        audio = audio.astype(np.float32) / np.iinfo(dtype_map.get(sample_width, np.int16)).max
        if wf.getnchannels() > 1:
            audio = audio[::wf.getnchannels()]  # take first channel
    return audio, sr


def benchmark_model(model_id: str, model_name: str, device: str) -> dict:
    """Run full benchmark for one model. Returns results dict."""
    print(f"\n{'='*60}")
    print(f"  Benchmarking: {model_name}")
    print(f"  Device: {device}")
    print(f"{'='*60}")

    results = {
        "model": model_name,
        "model_id": model_id,
        "device": device,
    }

    # --- Load model ---
    mem_before = get_memory_usage_mb()
    print(f"\n  Loading model...", end="", flush=True)
    t0 = time.time()

    from qwen_asr import Qwen3ASRModel
    dtype = torch.bfloat16 if device != "cpu" else torch.float32
    model = Qwen3ASRModel.from_pretrained(
        model_id,
        dtype=dtype,
        device_map=device,
        max_new_tokens=256,
    )

    load_time = time.time() - t0
    mem_after = get_memory_usage_mb()
    results["load_time_s"] = round(load_time, 2)
    results["memory_mb"] = round(mem_after - mem_before, 1)
    print(f" {load_time:.1f}s (Δmem: {mem_after - mem_before:.0f} MB)")

    # --- Warmup ---
    print(f"  Warming up ({WARMUP_RUNS} runs)...", end="", flush=True)
    dummy = np.zeros(16000, dtype=np.float32)
    for _ in range(WARMUP_RUNS):
        model.transcribe(audio=(dummy, 16000), language=None)
    print(" done")

    # --- Synthetic audio benchmarks (inference speed) ---
    print(f"\n  Inference speed (synthetic audio, {BENCH_RUNS} runs each):")
    speed_results = []

    for dur in AUDIO_DURATIONS:
        audio = generate_test_audio(dur)
        times = []
        for _ in range(BENCH_RUNS):
            t0 = time.time()
            model.transcribe(audio=(audio, 16000), language=None)
            times.append(time.time() - t0)

        avg = np.mean(times)
        std = np.std(times)
        rtf = avg / dur  # Real-Time Factor (< 1.0 = faster than real-time)
        speed_results.append({
            "duration_s": dur,
            "avg_time_s": round(avg, 3),
            "std_s": round(std, 3),
            "rtf": round(rtf, 3),
        })
        status = "✅" if rtf < 1.0 else "⚠️"
        print(f"    {dur:5.1f}s audio → {avg:.3f}s (±{std:.3f}s)  RTF={rtf:.3f} {status}")

    results["speed"] = speed_results

    # --- Real audio accuracy test (if available) ---
    real_files = find_real_audio_files()
    if real_files:
        print(f"\n  Accuracy test ({len(real_files)} files):")
        accuracy_results = []
        for entry in real_files:
            audio, sr = load_wav(entry["path"])
            t0 = time.time()
            out = model.transcribe(audio=(audio, sr), language=None)
            elapsed = time.time() - t0
            text = out[0].text if out else ""
            lang = out[0].language if out else ""

            accuracy_results.append({
                "file": entry["name"],
                "expected": entry["expected"],
                "got": text,
                "language": lang,
                "time_s": round(elapsed, 3),
                "match": text.strip() == entry["expected"].strip() if entry["expected"] else None,
            })
            match_icon = ""
            if entry["expected"]:
                match_icon = " ✅" if text.strip() == entry["expected"].strip() else " ❌"
            print(f"    {entry['name']}: \"{text[:60]}\" ({elapsed:.2f}s){match_icon}")

        results["accuracy"] = accuracy_results
    else:
        print(f"\n  ℹ️  No test_audio/ directory found. Skipping accuracy test.")
        print(f"     To enable: create test_audio/ with .wav files and optional .json ground truth.")

    # --- Cleanup ---
    del model
    gc.collect()
    if device == "mps":
        torch.mps.empty_cache()
    elif device.startswith("cuda"):
        torch.cuda.empty_cache()

    return results


def generate_markdown_report(
    all_results: list[dict], sys_info: dict, output_path: str
) -> str:
    """Generate a markdown benchmark report."""
    lines = []
    lines.append("# 🏎️ MoSheng ASR Model Benchmark")
    lines.append("")
    lines.append("Automated benchmark comparing Qwen3-ASR model variants on Apple Silicon.")
    lines.append("")

    # System info
    lines.append("## System Info")
    lines.append("")
    lines.append(f"| Item | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Platform | {sys_info['platform']} |")
    lines.append(f"| CPU | {sys_info.get('cpu', 'N/A')} |")
    lines.append(f"| RAM | {sys_info.get('ram_gb', 0):.0f} GB |")
    lines.append(f"| Python | {sys_info['python']} |")
    lines.append(f"| PyTorch | {sys_info['torch']} |")
    lines.append(f"| MPS Available | {'✅' if sys_info['mps_available'] else '❌'} |")
    lines.append(f"| Device Used | {all_results[0]['device']} |")
    lines.append("")

    # Load time & memory comparison
    lines.append("## Model Loading")
    lines.append("")
    lines.append("| Model | Load Time | Memory Usage |")
    lines.append("|---|---|---|")
    for r in all_results:
        lines.append(f"| {r['model']} | {r['load_time_s']}s | ~{r['memory_mb']:.0f} MB |")
    lines.append("")

    # Speed comparison table
    lines.append("## Inference Speed")
    lines.append("")
    lines.append("RTF (Real-Time Factor) = processing time ÷ audio duration. **RTF < 1.0 = faster than real-time.**")
    lines.append("")

    # Build comparison table
    header = "| Audio Duration |"
    sep = "|---|"
    for r in all_results:
        header += f" {r['model']} | RTF |"
        sep += "---|---|"
    lines.append(header)
    lines.append(sep)

    durations = all_results[0]["speed"]
    for i, dur_entry in enumerate(durations):
        row = f"| {dur_entry['duration_s']:.1f}s |"
        for r in all_results:
            s = r["speed"][i]
            status = "✅" if s["rtf"] < 1.0 else "⚠️"
            row += f" {s['avg_time_s']:.3f}s ±{s['std_s']:.3f}s | {s['rtf']:.3f} {status} |"
        lines.append(row)
    lines.append("")

    # Speed multiplier
    if len(all_results) == 2:
        lines.append("### Speed Comparison")
        lines.append("")
        a, b = all_results[0], all_results[1]
        lines.append(f"| Audio Duration | {a['model']} | {b['model']} | Speedup |")
        lines.append("|---|---|---|---|")
        for i in range(len(a["speed"])):
            sa, sb = a["speed"][i], b["speed"][i]
            speedup = sb["avg_time_s"] / sa["avg_time_s"] if sa["avg_time_s"] > 0 else 0
            lines.append(
                f"| {sa['duration_s']:.1f}s | {sa['avg_time_s']:.3f}s | "
                f"{sb['avg_time_s']:.3f}s | {speedup:.1f}× |"
            )
        lines.append("")

    # Accuracy (if available)
    has_accuracy = any("accuracy" in r for r in all_results)
    if has_accuracy:
        lines.append("## Accuracy Comparison")
        lines.append("")
        lines.append("| File | Expected |")
        for r in all_results:
            lines[-1] = lines[-1].rstrip("|") + f" {r['model']} |"
        lines.append("|---|---|" + "---|" * len(all_results))

        # Get union of files
        first_acc = all_results[0].get("accuracy", [])
        for i, entry in enumerate(first_acc):
            row = f"| {entry['file']} | {entry.get('expected', '')} |"
            for r in all_results:
                acc = r.get("accuracy", [])
                if i < len(acc):
                    e = acc[i]
                    match = ""
                    if e.get("match") is True:
                        match = " ✅"
                    elif e.get("match") is False:
                        match = " ❌"
                    row += f" {e['got']}{match} |"
                else:
                    row += " N/A |"
            lines.append(row)
        lines.append("")

    # Recommendation
    lines.append("## 💡 Recommendation")
    lines.append("")
    lines.append("| Use Case | Recommended Model |")
    lines.append("|---|---|")
    lines.append("| Fast dictation, short sentences | **Qwen3-ASR-0.6B** — lower latency, lighter on memory |")
    lines.append("| Long-form / mixed-language / technical terms | **Qwen3-ASR-1.7B** — higher accuracy on complex content |")
    lines.append("| Low-RAM devices (8GB) | **Qwen3-ASR-0.6B** — ~1.2GB vs ~3.4GB model size |")
    lines.append("| Apple Silicon (MPS) | Both work well; 0.6B has better real-time factor |")
    lines.append("| NVIDIA GPU (CUDA) | Both are fast; 1.7B recommended for best accuracy |")
    lines.append("")

    report = "\n".join(lines)

    # Write to file
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n📄 Report saved to: {output_path}")

    # Also save raw JSON
    json_path = output_path.replace(".md", ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"system": sys_info, "results": all_results}, f, indent=2, ensure_ascii=False)
    print(f"📊 Raw data saved to: {json_path}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Benchmark Qwen3-ASR models")
    parser.add_argument("--device", default="auto", help="Device: mps, cpu, or auto")
    parser.add_argument("--output", default="results/benchmark.md", help="Output report path")
    parser.add_argument("--models", nargs="+", default=None, help="Model IDs to benchmark")
    args = parser.parse_args()

    # Determine device
    if args.device == "auto":
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda:0"
        else:
            device = "cpu"
    else:
        device = args.device

    print("🏎️  MoSheng ASR Model Benchmark")
    print(f"   Device: {device}")

    sys_info = get_system_info()
    print(f"   CPU: {sys_info.get('cpu', 'N/A')}")
    print(f"   RAM: {sys_info.get('ram_gb', 0):.0f} GB")
    print(f"   PyTorch: {sys_info['torch']}")

    models = MODELS
    if args.models:
        models = [m for m in MODELS if m["model_id"] in args.models]

    all_results = []
    for m in models:
        results = benchmark_model(m["model_id"], m["name"], device)
        all_results.append(results)

    report = generate_markdown_report(all_results, sys_info, args.output)
    print(f"\n{'='*60}")
    print("  Benchmark complete!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
