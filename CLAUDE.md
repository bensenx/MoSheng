# MoSheng (墨声)

声音，化为笔墨。Windows 本地智能语音输入工具，基于 Qwen3-ASR-1.7B。支持**按住录音**和**按键切换**两种模式，松开/再按后自动识别并粘贴文本。暗色毛玻璃 Glassmorphism UI 风格。

## 运行

```bash
uv run --project E:\VoiceInput python E:\VoiceInput\main.py
```

## 环境

- **包管理**: UV (`pyproject.toml` + `uv.lock`)，不使用 requirements.txt
- **Python**: 3.12-3.13（3.14 无 PyTorch CUDA wheels）
- **UI 框架**: PySide6 (Qt)，暗色毛玻璃 Glassmorphism 主题 (DWM Acrylic backdrop)
- **PyTorch CUDA**: `torch` 必须作为直接依赖才能让 `[tool.uv.sources]` 指向 cu128 索引
- **GPU**: RTX 5090 (Blackwell/sm_120) 需要 cu128 索引；cu124 仅支持到 sm_90
- **依赖覆盖**: `override-dependencies` 强制 `numba>=0.60`, `llvmlite>=0.43`, `librosa>=0.10`（qwen-asr 传递依赖版本过低）

## 项目结构

```
main.py                 入口：单实例互斥锁 → QApplication → 加载界面 → 环境检查 → 模型加载 → 事件循环
config.py               默认配置常量（含 input_device）
settings_manager.py     用户设置持久化 (~/.mosheng/settings.json)
pyproject.toml          UV 项目配置（依赖、CUDA 索引、构建）
launcher.py             分发包入口（仅 stdlib，PyInstaller 编译为 MoSheng.exe）
_setup.cmd              首次运行安装脚本（GPU 检测、镜像选择、uv sync）
core/
  asr_base.py           ASR 抽象基类 (ABC)，可替换模型
  asr_qwen.py           Qwen3-ASR-1.7B 实现（含音频诊断日志）
  audio_recorder.py     sounddevice 录音，16kHz 单声道 float32，支持指定设备
  text_injector.py      剪贴板写入 + ctypes SendInput 模拟 Ctrl+V
  hotkey_manager.py     全局快捷键，支持 push_to_talk / toggle 两种模式
ui/
  app.py                QSystemTrayIcon + WorkerThread 组件协调器（核心调度）
  splash_screen.py      启动加载界面（glassmorphism，模型加载期间显示）
  overlay_window.py     QWidget 悬浮状态窗口（录音中/识别中/结果），click-through + fade animation
  settings_window.py    QDialog 设置界面（Glassmorphism + DWM Acrylic backdrop）
  styles.py             Glassmorphism QSS + 颜色常量 + ToggleSwitch + load_icon_pixmap + draw_section_icon
utils/
  logger.py             日志配置
configs/
  pyproject-cuda.toml   CUDA 版 pyproject（cu128 索引）
  pyproject-cpu.toml    CPU 版 pyproject（PyPI torch）
  uv-cuda.lock          CUDA 版锁文件
  uv-cpu.lock           CPU 版锁文件
scripts/
  build_dist.py         构建分发包（PyInstaller + 源码复制 + uv.exe）
```

## 设置项

| 分类 | 项目 | 运行时热更新 |
|------|------|:---:|
| 快捷键 | 按键组合、录音模式（按住/切换） | ✓ |
| 语音识别 | ASR 模型、GPU 设备 | ✗ 需重启 |
| 音频输入 | 麦克风设备选择 | ✓ |
| 输出 | 提示音、悬浮窗、剪贴板恢复 | ✓ |
| 词汇 | 自定义词汇表、CSV/TXT 导入 | ✓ |

## 分发包

### 构建

```bash
uv run python scripts/build_dist.py
```

产出 `dist/MoSheng/`（~70MB），包含：
- `MoSheng.exe` — PyInstaller 编译的 launcher（仅 stdlib，~7MB）
- `uv.exe` — 包管理器（~57MB）
- 源码（main.py, core/, ui/, utils/, assets/）
- `_setup.cmd` + `configs/` — 首次运行安装

### 用户运行流程

1. 双击 `MoSheng.exe`
2. Launcher 检查 `.venv/.mosheng_version`，不匹配则运行 `_setup.cmd`
3. `_setup.cmd`：GPU 检测 → 选择 CUDA/CPU pyproject.toml → `uv sync`
4. Launcher 启动 `pythonw.exe main.py`（无控制台）

### 分发包注意事项

- `_setup.cmd` 必须纯 ASCII（cmd.exe 用系统代码页 GBK 解析，UTF-8 中文会错位）
- `if errorlevel 1 goto :label` 比 `if !ERRORLEVEL! NEQ 0` 更可靠
- 版本更新时同步 `launcher.py:CURRENT_VERSION` 和 `_setup.cmd` 写入的版本号

## 线程模型

- **主线程**: `QApplication.exec()` 事件循环，拥有所有 QWidget 和 QSystemTrayIcon
- **keyboard 线程**: 快捷键 press/release 事件 → 写入 worker cmd_queue
- **WorkerThread (QThread)**: 从 cmd_queue 读命令，驱动录音→识别→粘贴流程，通过 `state_changed` 信号更新 UI
- **PortAudio 回调线程**: 音频帧写入 buffer

## 编码注意事项

### ctypes SendInput
- INPUT 结构体 union 必须包含 MOUSEINPUT + KEYBDINPUT + HARDWAREINPUT 三个成员，否则 `sizeof(INPUT)` 为 24（应为 40），`SendInput` 会静默失败
- `keyboard.send()` 底层用已废弃的 `keybd_event`，在 Win11 记事本和 cmd 中不可靠；用 ctypes `SendInput` 代替
- 调用粘贴前必须 `_release_modifiers()` 用 `GetAsyncKeyState` 检测并释放残留修饰键
- Cursor/VS Code 内嵌终端 (xterm.js) 对 SendInput Ctrl+V 不响应，属环境限制

### PySide6 / Qt
- `QApplication.setQuitOnLastWindowClosed(False)` — 托盘应用必须设置，否则关闭设置窗口会退出程序
- 跨线程 UI 更新用 Qt 信号/槽（自动 `QueuedConnection`）或 `QMetaObject.invokeMethod`
- Overlay click-through 用 `winId()` 直接获取 HWND + Windows API `SetWindowLongW`
- `Qt.WA_TranslucentBackground` + `paintEvent` 中 `QPainter.drawRoundedRect` 实现圆角透明窗口
- QSS 样式表集中在 `ui/styles.py`，全局应用于 `QApplication`
- 统一图标渲染：`load_icon_pixmap(logical_size)` 以 4x 物理像素加载，适配 1x–4x DPI
- Splash screen 不用 DWM Acrylic（会产生系统边框），仅 `WA_TranslucentBackground` + `paintEvent`
- Splash 直接设 `setWindowOpacity(1.0)`，主线程阻塞时 fade-in 动画不运行

### keyboard 库
- hook 回调跑在 keyboard 自己的线程上，修改共享状态需加锁
- Windows 按住键会连续触发 KEY_DOWN，push_to_talk 用 `_is_active` 防抖，toggle 用 `_toggle_fired` 防抖
- KEY_UP 事件可能因窗口焦点切换丢失

### 音频录制
- `sounddevice.InputStream(device=N)` 指定输入设备，`None` 为系统默认
- ASR 返回空文本时先检查麦克风：日志中 `Audio stats: rms=` 若接近 0 说明麦克风未采集到声音
- 用户环境有多个音频设备（无线麦、虚拟声卡、蓝牙耳机），务必提供设备选择

### PyTorch
- `torch.cuda.get_device_properties(0).total_memory`（不是 `total_mem`）
- Python 3.14 暂无 PyTorch CUDA wheels（截至 2026-02）

### 启动流程（main.py）
- 单实例保护：`CreateMutexW("MoSheng_SingleInstance")` + `GetLastError() == 183`
- QApplication 在模型加载**之前**创建，以便显示 splash screen
- 模型加载在主线程阻塞，splash 保持可见但动画暂停（已足够提供视觉反馈）

### 通用
- 跨类访问用公开属性/方法，不直接读写 `_private` 成员
- 线程同步用 `threading.Event`，不用 `time.sleep`
