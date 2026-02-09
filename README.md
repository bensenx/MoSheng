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
  <img src="https://img.shields.io/badge/platform-Windows_10%2F11-blue" alt="Platform">
  <img src="https://img.shields.io/badge/python-3.12--3.13-green" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-orange" alt="License">
  <img src="https://img.shields.io/badge/CUDA-12.8-76B900?logo=nvidia" alt="CUDA">
</p>

---

<!-- TODO: replace with actual screenshot/GIF
<p align="center">
  <img src="docs/images/demo.gif" alt="MoSheng Demo" width="600">
</p>
-->

<a name="english"></a>

## What is MoSheng?

**MoSheng (墨声)** is a local voice input tool for Windows. Hold a hotkey, speak, release — your words are instantly transcribed and pasted into any application.

Powered by [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B). **Runs 100% offline.** No cloud, no data leaves your machine.

## Features

- 🎤 **Dual Hotkeys** — `CapsLock` push-to-talk / `Right Ctrl` toggle mode
- ⚡ **Progressive Input** — auto-injects text on speech pauses, no need to wait until you finish
- 🔒 **Speaker Verification** — SpeechBrain ECAPA-TDNN two-stage verification, responds only to your voice
- 🔄 **Multiple Models** — Qwen3-ASR-1.7B (accurate) / 0.6B (lightweight), switch in settings
- 📖 **Custom Vocabulary** — import CSV/TXT word lists to boost recognition of domain terms
- 🎨 **GPU Shader Overlay** — real-time audio visualization with QML + GLSL fragment shader
- 🪟 **Glassmorphism UI** — dark theme with DWM Acrylic backdrop
- 🌐 **Bilingual** — Chinese / English interface, auto-detected
- 🚀 **Autostart** — one-click Windows startup toggle
- 📦 **One-click Install** — download, unzip, run

## Requirements

| Item | Requirement |
|------|-------------|
| OS | Windows 10 / 11 |
| GPU | NVIDIA GPU with CUDA 12.8 (RTX 30 series or above recommended) |
| VRAM | ~4 GB for 1.7B model / ~2 GB for 0.6B model |
| Python | 3.12 - 3.13 (auto-installed by distribution package) |
| Disk | ~5 GB (model + dependencies) |

> No NVIDIA GPU? CPU mode is available (slower). The 0.6B model has lower hardware requirements.

## Installation

### Option A: Distribution Package (Recommended)

1. Download the latest `MoSheng-vX.X.X-win64.zip` from [Releases](https://github.com/bensenx/MoSheng/releases)
2. Extract to any directory
3. Run `MoSheng.exe`
4. First launch auto-installs Python environment and dependencies (~5 min, internet required)
5. First launch downloads the ASR model (~3.4 GB)

### Option B: From Source

Requires [UV](https://docs.astral.sh/uv/) package manager:

```bash
git clone https://github.com/bensenx/MoSheng.git
cd MoSheng
uv run python main.py
```

> UV automatically creates a virtual environment and installs Python + all dependencies.

## Configuration

Right-click the system tray icon → **Settings** to open the settings window.

### Hotkeys

| Mode | Default Key | Description |
|------|------------|-------------|
| Push-to-talk (PTT) | `CapsLock` | Hold to record, release to transcribe |
| Toggle | `Right Ctrl` | Press to start, press again to stop |

Hotkeys are fully customizable. PTT mode has a 300 ms long-press threshold to prevent accidental triggers.

### Progressive Input

When enabled, text is automatically injected after a silence of 0.8 seconds — no need to wait until you finish speaking. Great for long paragraphs.

### Speaker Verification

When enabled, only your registered voice is recognized. Go to Settings → **Enroll Voice** and record 3 audio segments.

### Custom Vocabulary

Add domain terms or names to `~/.mosheng/vocabulary.csv` (one per line) to improve recognition accuracy.

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| ASR | [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) | 1.7B / 0.6B |
| Speaker Verification | [SpeechBrain ECAPA-TDNN](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb) | 192-dim embeddings, two-stage |
| UI | PySide6 (Qt 6) | Glassmorphism + DWM Acrylic |
| Audio Overlay | QML + GLSL Shader | GPU-rendered visualization |
| GPU | PyTorch + CUDA 12.8 | RTX 30/40/50 series |
| Package Manager | [UV](https://docs.astral.sh/uv/) | Fast dependency resolution |
| Distribution | PyInstaller + UV | Launcher + runtime auto-install |

## Building

```bash
uv run python scripts/build_dist.py
```

Produces `dist/MoSheng/` containing `MoSheng.exe`, `uv.exe`, source code, and config files.

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
  text_injector.py       Text injection (SendInput)
  hotkey_manager.py      Hotkey management
  key_suppression_hook.py  WH_KEYBOARD_LL hook
  model_downloader.py    Model download manager
ui/
  app.py                 App coordinator (tray + worker)
  overlay_window.py      Audio overlay (QML Shader)
  overlay.qml            QML scene
  settings_window.py     Settings window
  splash_screen.py       Splash screen
  styles.py              Glassmorphism styles
  enrollment_dialog.py   Voice enrollment dialog
utils/
  autostart.py           Windows autostart
  logger.py              Logging config
assets/
  shaders/smoke.frag     GLSL fragment shader
```

---

<a name="中文"></a>

## 简介

**墨声 (MoSheng)** 是一款 Windows 本地智能语音输入工具。

按住 `CapsLock` 说话 → 松手 → 文字自动粘贴到任意应用。

基于 [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)，**100% 本地运行**，无需网络，隐私安全。

## 功能亮点

- 🎤 **双快捷键** — `CapsLock` 按住录音 (PTT) / `Right Ctrl` 按键切换
- ⚡ **渐进式输入** — 说话停顿时自动注入已识别文本，无需等待说完
- 🔒 **声纹识别** — SpeechBrain ECAPA-TDNN 两级验证，只响应注册用户
- 🔄 **多模型选择** — Qwen3-ASR-1.7B（精准）/ 0.6B（轻量）
- 📖 **自定义词汇表** — CSV/TXT 导入 + 预置术语，提高专业词识别率
- 🎨 **GPU Shader 可视化** — QML + GLSL 实时音频频谱动画
- 🪟 **Glassmorphism UI** — DWM Acrylic 毛玻璃暗色主题
- 🌐 **中英双语** — 界面语言自动检测
- 🚀 **开机自启** — Windows 注册表一键开关
- 📦 **一键安装** — 下载分发包，双击即用

## 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 / 11 |
| GPU | NVIDIA GPU，支持 CUDA 12.8（推荐 RTX 30 系以上）|
| 显存 | 1.7B 模型 ~4GB / 0.6B 模型 ~2GB |
| Python | 3.12 - 3.13（分发包自动安装） |
| 磁盘 | ~5GB（含模型和依赖） |

> 没有 NVIDIA GPU？可使用 CPU 模式（速度较慢）。0.6B 模型对配置要求更低。

## 安装

### 方式 A：下载分发包（推荐）

1. 从 [Releases](https://github.com/bensenx/MoSheng/releases) 下载最新的 `MoSheng-vX.X.X-win64.zip`
2. 解压到任意目录
3. 双击 `MoSheng.exe`
4. 首次运行会自动安装 Python 环境和依赖（需联网，约 5 分钟）
5. 首次运行会自动下载 ASR 模型（~3.4GB）

### 方式 B：源码运行

需要 [UV](https://docs.astral.sh/uv/) 包管理器：

```bash
git clone https://github.com/bensenx/MoSheng.git
cd MoSheng
uv run python main.py
```

> UV 会自动创建虚拟环境、安装 Python 和所有依赖。

## 配置

右键系统托盘图标 → 「设置」打开设置窗口。

### 快捷键

| 模式 | 默认快捷键 | 说明 |
|------|-----------|------|
| 按住录音 (PTT) | `CapsLock` | 按住说话，松手识别 |
| 切换录音 | `Right Ctrl` | 按一次开始，再按一次停止 |

快捷键可在设置中自定义。PTT 模式有 300ms 长按阈值，避免误触。

### 渐进式输入

启用后，说话停顿超过 0.8 秒自动注入已识别文本，无需等待说完。适合长段落输入。

### 声纹识别

启用后，只识别注册用户的声音。在设置中点击「注册声纹」，按提示录制 3 段语音即可。

### 自定义词汇表

在 `~/.mosheng/vocabulary.csv` 中添加专业术语、人名等，每行一个，帮助提高识别准确率。

---

## License

[MIT](LICENSE) © 2026 bensenx
