# 🏎️ MoSheng ASR Model Benchmark

Automated benchmark comparing Qwen3-ASR model variants on Apple Silicon.

## System Info

| Item | Value |
|---|---|
| Platform | macOS-15.3.1-arm64-arm-64bit-Mach-O |
| CPU | Apple M4 |
| RAM | 16 GB |
| Python | 3.14.3 |
| PyTorch | 2.10.0 |
| MPS Available | ✅ |
| Device Used | mps |

## Model Loading

| Model | Load Time | Memory Usage |
|---|---|---|
| Qwen3-ASR-0.6B | 30.83s | ~1302 MB |
| Qwen3-ASR-1.7B | 9.69s | ~0 MB |

## Inference Speed

RTF (Real-Time Factor) = processing time ÷ audio duration. **RTF < 1.0 = faster than real-time.**

| Audio Duration | Qwen3-ASR-0.6B | RTF | Qwen3-ASR-1.7B | RTF |
|---|---|---|---|---|
| 1.0s | 0.112s ±0.000s | 0.112 ✅ | 0.248s ±0.006s | 0.248 ✅ |
| 2.0s | 0.793s ±0.941s | 0.396 ✅ | 0.292s ±0.054s | 0.146 ✅ |
| 3.0s | 0.472s ±0.469s | 0.157 ✅ | 0.293s ±0.028s | 0.098 ✅ |
| 5.0s | 0.323s ±0.228s | 0.065 ✅ | 0.362s ±0.056s | 0.072 ✅ |
| 10.0s | 1.011s ±1.119s | 0.101 ✅ | 0.466s ±0.043s | 0.047 ✅ |

### Speed Comparison

| Audio Duration | Qwen3-ASR-0.6B | Qwen3-ASR-1.7B | Speedup |
|---|---|---|---|
| 1.0s | 0.112s | 0.248s | 2.2× |
| 2.0s | 0.793s | 0.292s | 0.4× |
| 3.0s | 0.472s | 0.293s | 0.6× |
| 5.0s | 0.323s | 0.362s | 1.1× |
| 10.0s | 1.011s | 0.466s | 0.5× |

## 💡 Recommendation

| Use Case | Recommended Model |
|---|---|
| Fast dictation, short sentences | **Qwen3-ASR-0.6B** — lower latency, lighter on memory |
| Long-form / mixed-language / technical terms | **Qwen3-ASR-1.7B** — higher accuracy on complex content |
| Low-RAM devices (8GB) | **Qwen3-ASR-0.6B** — ~1.2GB vs ~3.4GB model size |
| Apple Silicon (MPS) | Both work well; 0.6B has better real-time factor |
| NVIDIA GPU (CUDA) | Both are fast; 1.7B recommended for best accuracy |
