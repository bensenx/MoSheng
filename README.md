<p align="center">
  <img src="assets/icon.png" alt="MoSheng Logo" width="128" height="128">
</p>

<h1 align="center">墨声 MoSheng</h1>

<p align="center">
  <strong>Voice, into ink. — 声音，化为笔墨。</strong>
</p>

<p align="center">
  <a href="#中文">中文</a> ·
  <a href="#english">English</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows_|_macOS-blue" alt="Platform">
  <img src="https://img.shields.io/badge/python-3.12+-green" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-orange" alt="License">
  <img src="https://img.shields.io/badge/CUDA-12.8-76B900?logo=nvidia" alt="CUDA">
  <img src="https://img.shields.io/badge/Apple_Silicon-MPS-black?logo=apple" alt="MPS">
</p>

---

<a name="english"></a>

## What is MoSheng?

**MoSheng (墨声)** is a local voice input tool. Hold a hotkey, speak, release — your words are instantly transcribed and pasted into any application.

Powered by [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B). **Runs 100% offline.** No cloud, no data leaves your machine.

## Features

- 🎤 **Dual Hotkeys** — Push-to-talk / toggle mode with customizable keys
- ⚡ **Progressive Input** — auto-injects text on speech pauses, no need to wait until you finish
- 🔒 **Speaker Verification** — SpeechBrain ECAPA-TDNN two-stage verification, responds only to your voice
- 🔄 **Multiple Models** — Qwen3-ASR-1.7B (accurate) / 0.6B (lightweight), switch in settings
- 📖 **Custom Vocabulary** — import CSV/TXT word lists to boost recognition of domain terms
- 🎨 **GPU Shader Overlay** — real-time audio visualization with QML + GLSL fragment shader
- 🪟 **Native UI** — dark theme with platform-native effects
- 🌐 **Bilingual** — Chinese / English interface, auto-detected
- 🚀 **Autostart** — one-click startup toggle
- 📦 **One-click Install** — download, run, done

## Platform Support

| | Windows | macOS |
|---|---|---|
| OS | Windows 10 / 11 | macOS 13+ (Apple Silicon) |
| GPU | NVIDIA CUDA 12.8 | Apple MPS (Metal) |
| Default Hotkey (PTT) | `CapsLock` | `Right ⌘` |
| Default Hotkey (Toggle) | `Right Ctrl` | `Fn + F5` |
| Autostart | Registry | launchd |
| UI Effect | DWM Acrylic | Native Qt |

## Requirements

### Windows

| Item | Requirement |
|------|-------------|
| GPU | NVIDIA GPU with CUDA 12.8 (RTX 30 series or above recommended) |
| VRAM | ~4 GB for 1.7B model / ~2 GB for 0.6B model |
| Disk | ~5 GB (model + dependencies) |

### macOS

| Item | Requirement |
|------|-------------|
| Chip | Apple Silicon (M1 / M2 / M3 / M4) |
| RAM | 16 GB recommended |
| Disk | ~5 GB (model + dependencies) |
| Permissions | Accessibility + Microphone |

> **⚠️ macOS users: Use the 1.7B model.** Our [benchmarks](results/benchmark.md) show 1.7B is 5-10× faster than 0.6B on Apple Silicon MPS.

## Installation

### Windows

#### Option A: Distribution Package (Recommended)

1. Download `MoSheng-vX.X.X-win64.zip` from [Releases](https://github.com/bensenx/MoSheng/releases)
2. Extract to any directory
3. Run `MoSheng.exe`
4. First launch auto-installs Python environment and dependencies (~5 min)
5. First launch downloads the ASR model (~3.4 GB)

#### Option B: From Source

```bash
git clone https://github.com/bensenx/MoSheng.git
cd MoSheng
uv run python main.py
```

### macOS

#### Option A: DMG Install (Recommended)

1. Download `MoSheng-v1.1.0-macOS.dmg` from [Releases](https://github.com/bensenx/MoSheng/releases/tag/v1.1.0-macos)
2. Open the DMG and drag **MoSheng** to **Applications**
3. **First launch:** Right-click MoSheng.app → **Open** → click **Open** (Gatekeeper one-time prompt)
4. Grant **Accessibility** permission when prompted (System Settings → Privacy & Security → Accessibility)
5. Grant **Microphone** permission when prompted
6. First launch auto-installs Python dependencies via [uv](https://docs.astral.sh/uv/) (~3 min)
7. First launch downloads the ASR model (~3.4 GB)

> **Gatekeeper note:** MoSheng is not notarized with Apple. On first launch, macOS will show a security warning. Right-click → Open bypasses this. Alternatively, run in Terminal:
> ```bash
> xattr -cr /Applications/MoSheng.app
> ```

#### Option B: From Source

```bash
git clone https://github.com/bensenx/MoSheng.git
cd MoSheng
git checkout macos
uv run python main.py
```

#### Option C: Install Script

```bash
curl -fsSL https://raw.githubusercontent.com/bensenx/MoSheng/macos/scripts/install_macos.sh | bash
```

## Configuration

Right-click the system tray icon → **Settings** to open the settings window.

### Hotkeys

| Mode | Windows Default | macOS Default | Description |
|------|----------------|---------------|-------------|
| Push-to-talk (PTT) | `CapsLock` | `Right ⌘` | Hold to record, release to transcribe |
| Toggle | `Right Ctrl` | `Fn + F5` | Press to start, press again to stop |

Hotkeys are fully customizable. PTT mode has a 300 ms long-press threshold to prevent accidental triggers.

### Progressive Input

When enabled, text is automatically injected after a silence of 0.8 seconds — no need to wait until you finish speaking. Great for long paragraphs.

### Speaker Verification

When enabled, only your registered voice is recognized. Go to Settings → **Enroll Voice** and record 3 audio segments.

### Custom Vocabulary

Add domain terms or names to `~/.mosheng/vocabulary.csv` (one per line) to improve recognition accuracy.

## Benchmark

Real-world voice test on **Apple M4 / 16GB / macOS 15.3.1**:

| Test | 1.7B | 0.6B |
|------|------|------|
| Simple Chinese | 1.06s ✅ | 3.43s ✅ |
| Daily conversation | 1.26s ✅ | 3.73s ✅ |
| Numbers & time | 1.76s ✅ | 17.35s ⚠️ |
| Mixed CN/EN | 1.58s ✅ | 16.40s ⚠️ |
| Technical terms | 1.78s ✅ | 19.58s ⚠️ |
| Long sentence | 3.64s ✅ | 32.50s 🐌 |
| English | 1.22s ✅ | 12.01s ⚠️ |
| Punctuation & tone | 1.20s ✅ | 9.45s ⚠️ |

**→ On Apple Silicon, 1.7B is 5-10× faster than 0.6B with identical accuracy.**

Full benchmark: [results/benchmark.md](results/benchmark.md)

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| ASR | [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) | 1.7B / 0.6B |
| Speaker Verification | [SpeechBrain ECAPA-TDNN](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb) | 192-dim embeddings |
| UI | PySide6 (Qt 6) | Cross-platform |
| Audio Overlay | QML + GLSL Shader | GPU-rendered visualization |
| GPU | PyTorch (CUDA / MPS) | NVIDIA or Apple Silicon |
| Package Manager | [UV](https://docs.astral.sh/uv/) | Fast dependency resolution |

## Building

### Windows
```bash
uv run python scripts/build_dist.py
```

### macOS
```bash
uv run python scripts/build_macos.py
```

Produces `dist/MoSheng.app`. To create DMG:
```bash
hdiutil create -volname MoSheng -srcfolder dist/MoSheng.app -ov -format UDZO dist/MoSheng.dmg
```

## Project Structure

```
main.py                  Entry point
config.py                Default configuration
i18n.py                  Internationalization (zh/en)
settings_manager.py      Settings persistence
core/
  asr_qwen.py            Qwen3-ASR engine
  audio_recorder.py      Audio recording (sounddevice)
  speaker_verifier.py    Speaker verification (SpeechBrain)
  text_injector.py       Text injection (Ctrl+V / Cmd+V)
  hotkey_manager.py      Hotkey management (Win32 / CGEventTap)
  key_suppression_hook.py  Key suppression (Windows only)
  model_downloader.py    Model download manager
ui/
  app.py                 App coordinator (tray + worker)
  overlay_window.py      Audio overlay (QML Shader)
  overlay.qml            QML scene
  settings_window.py     Settings window
  splash_screen.py       Splash screen
  styles.py              Theme styles
  enrollment_dialog.py   Voice enrollment dialog
utils/
  autostart.py           Autostart (Registry / launchd)
  logger.py              Logging config
scripts/
  build_dist.py          Windows distribution build
  build_macos.py         macOS .app + DMG build
  benchmark_models.py    Model benchmark script
assets/
  shaders/smoke.frag     GLSL fragment shader
results/
  benchmark.md           Performance benchmark report
```

---

<a name="中文"></a>

## 简介

**墨声 (MoSheng)** 是一款本地智能语音输入工具，支持 Windows 和 macOS。

按住快捷键说话 → 松手 → 文字自动粘贴到任意应用。

基于 [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)，**100% 本地运行**，无需网络，隐私安全。

## 功能亮点

- 🎤 **双快捷键** — 按住录音 (PTT) / 按键切换，可自定义
- ⚡ **渐进式输入** — 说话停顿时自动注入已识别文本，无需等待说完
- 🔒 **声纹识别** — SpeechBrain ECAPA-TDNN 两级验证，只响应注册用户
- 🔄 **多模型选择** — Qwen3-ASR-1.7B（精准）/ 0.6B（轻量）
- 📖 **自定义词汇表** — CSV/TXT 导入 + 预置术语，提高专业词识别率
- 🎨 **GPU Shader 可视化** — QML + GLSL 实时音频频谱动画
- 🪟 **原生 UI** — 深色主题，平台原生特效
- 🌐 **中英双语** — 界面语言自动检测
- 🚀 **开机自启** — 一键开关
- 📦 **一键安装** — 下载即用

## 平台支持

| | Windows | macOS |
|---|---|---|
| 系统 | Windows 10 / 11 | macOS 13+ (Apple Silicon) |
| GPU | NVIDIA CUDA 12.8 | Apple MPS (Metal) |
| 默认快捷键 (PTT) | `CapsLock` | `右 ⌘` |
| 默认快捷键 (Toggle) | `Right Ctrl` | `Fn + F5` |
| 开机自启 | 注册表 | launchd |

## 系统要求

### Windows

| 项目 | 要求 |
|------|------|
| GPU | NVIDIA GPU，支持 CUDA 12.8（推荐 RTX 30 系以上）|
| 显存 | 1.7B 模型 ~4GB / 0.6B 模型 ~2GB |
| 磁盘 | ~5GB（含模型和依赖） |

### macOS

| 项目 | 要求 |
|------|------|
| 芯片 | Apple Silicon (M1 / M2 / M3 / M4) |
| 内存 | 建议 16GB |
| 磁盘 | ~5GB（含模型和依赖） |
| 权限 | 辅助功能 + 麦克风 |

> **⚠️ macOS 用户请使用 1.7B 模型。** 我们的[性能测试](results/benchmark.md)显示，在 Apple Silicon MPS 上 1.7B 比 0.6B 快 5-10 倍。

## 安装

### Windows

#### 方式 A：下载分发包（推荐）

1. 从 [Releases](https://github.com/bensenx/MoSheng/releases) 下载最新的 `MoSheng-vX.X.X-win64.zip`
2. 解压到任意目录
3. 双击 `MoSheng.exe`
4. 首次运行自动安装 Python 环境和依赖（需联网，约 5 分钟）
5. 首次运行自动下载 ASR 模型（~3.4GB）

#### 方式 B：源码运行

```bash
git clone https://github.com/bensenx/MoSheng.git
cd MoSheng
uv run python main.py
```

### macOS

#### 方式 A：DMG 安装（推荐）

1. 从 [Releases](https://github.com/bensenx/MoSheng/releases/tag/v1.1.0-macos) 下载 `MoSheng-v1.1.0-macOS.dmg`
2. 打开 DMG，将 **MoSheng** 拖入 **Applications（应用程序）**
3. **首次启动：** 右键点击 MoSheng.app → **打开** → 点击 **打开**（Gatekeeper 一次性提示）
4. 授权**辅助功能**权限（系统设置 → 隐私与安全性 → 辅助功能）
5. 授权**麦克风**权限
6. 首次启动自动通过 [uv](https://docs.astral.sh/uv/) 安装 Python 依赖（约 3 分钟）
7. 首次启动自动下载 ASR 模型（~3.4GB）

> **安全提示：** MoSheng 未经 Apple 公证。首次打开时 macOS 会显示安全警告，右键 → 打开 即可绕过。也可在终端执行：
> ```bash
> xattr -cr /Applications/MoSheng.app
> ```

#### 方式 B：源码运行

```bash
git clone https://github.com/bensenx/MoSheng.git
cd MoSheng && git checkout macos
uv run python main.py
```

#### 方式 C：安装脚本

```bash
curl -fsSL https://raw.githubusercontent.com/bensenx/MoSheng/macos/scripts/install_macos.sh | bash
```

## 性能测试

在 **Apple M4 / 16GB / macOS 15.3.1** 上的真实语音测试：

| 测试场景 | 1.7B | 0.6B |
|---------|------|------|
| 简单中文 | 1.06秒 ✅ | 3.43秒 ✅ |
| 日常对话 | 1.26秒 ✅ | 3.73秒 ✅ |
| 数字和时间 | 1.76秒 ✅ | 17.35秒 ⚠️ |
| 中英混合 | 1.58秒 ✅ | 16.40秒 ⚠️ |
| 技术术语 | 1.78秒 ✅ | 19.58秒 ⚠️ |
| 长句子 | 3.64秒 ✅ | 32.50秒 🐌 |
| 纯英文 | 1.22秒 ✅ | 12.01秒 ⚠️ |
| 语气标点 | 1.20秒 ✅ | 9.45秒 ⚠️ |

**→ 在 Apple Silicon 上，1.7B 比 0.6B 快 5-10 倍，准确率完全一致。**

完整报告：[results/benchmark.md](results/benchmark.md)

## 配置

右键系统托盘图标 → 「设置」打开设置窗口。

### 快捷键

| 模式 | Windows 默认 | macOS 默认 | 说明 |
|------|-------------|-----------|------|
| 按住录音 (PTT) | `CapsLock` | `右 ⌘` | 按住说话，松手识别 |
| 切换录音 | `Right Ctrl` | `Fn + F5` | 按一次开始，再按一次停止 |

快捷键可在设置中自定义。PTT 模式有 300ms 长按阈值，避免误触。

### 渐进式输入

启用后，说话停顿超过 0.8 秒自动注入已识别文本，无需等待说完。适合长段落输入。

### 声纹识别

启用后，只识别注册用户的声音。在设置中点击「注册声纹」，录制 3 段语音。

### 自定义词汇表

在 `~/.mosheng/vocabulary.csv` 中添加专业术语，每行一个，帮助提高识别率。

---

## License

[MIT](LICENSE) © 2026 bensenx
