# Changelog

## v1.2.0 (2026-02-21)

### Features

- **Text Processing** — new post-processing pipeline applied after ASR transcription
  - Remove filler words: Chinese (嗯/呃/哦/唔/那个/然后/就是…) and English (um/uh/hmm/er…)
  - Smart punctuation: in progressive mode, intermediate pauses become commas; final period injected at session end, producing flowing prose
  - Toggle each option independently in Settings → Text Processing
- **Unicode character injection** — new `inject_char_unicode()` method for zero-latency single-character input via SendInput

### Fixes

- Fix Text Processing settings section rendered outside scroll area (stuck at bottom of settings window)
- Splash screen now shows "First load may take a few minutes" hint during ASR model loading, explaining the expected wait on new machines
- Speaker verification hint now warns that very short words (<1s) may be incorrectly filtered

## v1.1.0-macos (2026-02-14)

### 🍎 macOS 支持

- **macOS .app 打包**: 通过 `scripts/install_macos.sh` 创建原生 .app bundle
  - 自动创建 .icns 图标
  - Info.plist 包含麦克风权限声明
  - 支持双击启动或从终端 `open MoSheng.app`
- **MPS (Metal) 后端优化**: 完整支持 Apple Silicon GPU 加速
- **Benchmark 报告**: 真实语音测试，覆盖中文/英文/中英混合/技术术语等场景

### 📊 性能发现

- 1.7B 模型在 MPS 上平均 1.7s 完成识别（真实语音）
- 0.6B 模型在 MPS 上反而慢 5-10 倍（平均 14.3s）
- **macOS 推荐使用 1.7B 模型**

### 🛠️ 构建

- 新增 `scripts/install_macos.sh` macOS 安装脚本
- 更新 `results/benchmark.md` 真实语音基准测试报告
- 使用 .app wrapper 方案代替 PyInstaller（避免 5-10GB 打包体积）

## v1.0.0

- 初始发布
- Windows 支持 (PyInstaller)
- Qwen3-ASR 0.6B / 1.7B 模型支持
- 实时语音识别覆盖层
