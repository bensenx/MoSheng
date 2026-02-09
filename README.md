<p align="center">
  <img src="assets/icon.png" alt="MoSheng Logo" width="128" height="128">
</p>

<h1 align="center">墨声 MoSheng</h1>

<p align="center">
  <strong>声音，化为笔墨。</strong>
</p>

<p align="center">
  <a href="#english">English</a> ·
  <a href="#features">功能</a> ·
  <a href="#installation">安装</a> ·
  <a href="#configuration">配置</a> ·
  <a href="#tech-stack">技术栈</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows_10%2F11-blue" alt="Platform">
  <img src="https://img.shields.io/badge/python-3.12--3.13-green" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-orange" alt="License">
  <img src="https://img.shields.io/badge/CUDA-12.8-76B900?logo=nvidia" alt="CUDA">
</p>

---

<!-- TODO: 替换为实际截图/GIF
<p align="center">
  <img src="docs/images/demo.gif" alt="MoSheng Demo" width="600">
</p>
-->

## 简介

**墨声 (MoSheng)** 是一款 Windows 本地智能语音输入工具。

按住 `CapsLock` 说话 → 松手 → 文字自动粘贴到任意应用。

基于 [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)，**100% 本地运行**，无需网络，隐私安全。

## 五色墨韵 ✨

说话时，屏幕底部浮现**五色墨韵**波形：

| 曲线 | 颜色 | 频段 |
|------|------|------|
| 松烟墨 | ██ | Bass |
| 靛蓝 | ██ | Low-mid |
| 赭石 | ██ | Mid |
| 朱砂 | ██ | High-mid |
| 藤黄 | ██ | Treble |

五种传统中国墨色映射五个声音频段，GPU Shader (GLSL) 实时渲染。

**声音，真的化为了笔墨。**

<!-- TODO: 替换为 Overlay 各状态截图
<p align="center">
  <img src="docs/images/overlay-recording.png" alt="Recording" width="300">
  <img src="docs/images/overlay-recognizing.png" alt="Recognizing" width="300">
</p>
-->

<a name="features"></a>
## 功能亮点

- 🎨 **五色墨韵** — QML + GPU Shader 频谱可视化，五种传统墨色随声波流动
- 🎤 **双快捷键** — `CapsLock` 按住录音 (PTT) / `Right Ctrl` 按键切换
- ⚡ **渐进式输入** — 说话停顿时自动注入已识别文本，无需等待说完
- 🔒 **声纹识别** — SpeechBrain ECAPA-TDNN 两级验证，只响应注册用户
- 🔄 **多模型选择** — Qwen3-ASR-1.7B（精准）/ 0.6B（轻量）
- 📖 **自定义词汇表** — CSV/TXT 导入 + 预置术语，提高专业词识别率
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

<a name="installation"></a>
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
# 克隆仓库
git clone https://github.com/bensenx/MoSheng.git
cd MoSheng

# 安装依赖并运行
uv run python main.py
```

> UV 会自动创建虚拟环境、安装 Python 和所有依赖。

<a name="configuration"></a>
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

<a name="tech-stack"></a>
## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 语音识别 | [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) | 1.7B / 0.6B 两种规格 |
| 声纹识别 | [SpeechBrain ECAPA-TDNN](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb) | 192 维嵌入，两级验证 |
| UI 框架 | PySide6 (Qt 6) | Glassmorphism + DWM Acrylic |
| 频谱可视化 | QML + GLSL Shader | GPU 渲染五色墨韵 |
| GPU 加速 | PyTorch + CUDA 12.8 | 适配 RTX 30/40/50 系列 |
| 包管理 | [UV](https://docs.astral.sh/uv/) | 快速依赖解析和安装 |
| 分发 | PyInstaller + UV | Launcher + 运行时自动安装 |

## 构建分发包

```bash
uv run python scripts/build_dist.py
```

产出 `dist/MoSheng/`，包含 `MoSheng.exe`、`uv.exe`、源码和配置文件。

## 项目结构

```
main.py                  入口
config.py                默认配置
i18n.py                  国际化 (zh/en)
settings_manager.py      设置持久化
core/
  asr_qwen.py            Qwen3-ASR 实现
  audio_recorder.py      音频录制 (sounddevice)
  speaker_verifier.py    声纹验证 (SpeechBrain)
  text_injector.py       文本注入 (SendInput)
  hotkey_manager.py      快捷键管理
  key_suppression_hook.py  WH_KEYBOARD_LL 钩子
  model_downloader.py    模型下载管理
ui/
  app.py                 应用主体 (托盘 + Worker)
  overlay_window.py      五色墨韵 Overlay (QML Shader)
  overlay.qml            QML 场景
  settings_window.py     设置窗口
  splash_screen.py       启动界面
  styles.py              Glassmorphism 样式
  enrollment_dialog.py   声纹注册对话框
utils/
  autostart.py           开机自启
  logger.py              日志配置
assets/
  shaders/smoke.frag     GLSL 片段着色器
```

---

<a name="english"></a>
## English

**MoSheng** is a Windows local voice input tool powered by Qwen3-ASR.

Hold `CapsLock` → speak → release → text is automatically pasted into any application. 100% local, no internet required.

**Key Features:**
- Five-color ink wash GPU shader visualization (松烟墨/靛蓝/赭石/朱砂/藤黄)
- Push-to-talk (CapsLock) and toggle (Right Ctrl) modes
- Progressive input — auto-inject text during speech pauses
- Speaker verification — responds only to registered voice
- Multiple ASR models — 1.7B (accurate) / 0.6B (lightweight)
- Glassmorphism dark UI with DWM Acrylic backdrop
- Bilingual interface (Chinese / English)

**Requirements:** Windows 10/11, NVIDIA GPU (CUDA 12.8), Python 3.12-3.13

**Install:** Download from [Releases](https://github.com/bensenx/MoSheng/releases), unzip, and run `MoSheng.exe`.

---

## License

[MIT](LICENSE) © 2026 bensenx
