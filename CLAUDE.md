# VoiceInput

Windows 本地语音输入工具，基于 Qwen3-ASR-1.7B。支持**按住录音**和**按键切换**两种模式，松开/再按后自动识别并粘贴文本。可在设置中选择麦克风、快捷键、录音模式等。

## 运行

```bash
uv run --project E:\VoiceInput python E:\VoiceInput\main.py
```

## 环境

- **包管理**: UV (`pyproject.toml` + `uv.lock`)，不使用 requirements.txt
- **Python**: 3.12-3.13（3.14 无 PyTorch CUDA wheels）
- **PyTorch CUDA**: `torch` 必须作为直接依赖才能让 `[tool.uv.sources]` 指向 cu128 索引
- **GPU**: RTX 5090 (Blackwell/sm_120) 需要 cu128 索引；cu124 仅支持到 sm_90
- **依赖覆盖**: `override-dependencies` 强制 `numba>=0.60`, `llvmlite>=0.43`, `librosa>=0.10`（qwen-asr 传递依赖版本过低）

## 项目结构

```
main.py                 入口：环境检查 → 模型加载 → 托盘应用
config.py               默认配置常量（含 input_device）
settings_manager.py     用户设置持久化 (~/.voiceinput/settings.json)
pyproject.toml          UV 项目配置（依赖、CUDA 索引、构建）
core/
  asr_base.py           ASR 抽象基类 (ABC)，可替换模型
  asr_qwen.py           Qwen3-ASR-1.7B 实现（含音频诊断日志）
  audio_recorder.py     sounddevice 录音，16kHz 单声道 float32，支持指定设备
  text_injector.py      剪贴板写入 + ctypes SendInput 模拟 Ctrl+V
  hotkey_manager.py     全局快捷键，支持 push_to_talk / toggle 两种模式
ui/
  tray_app.py           系统托盘 + 组件协调器（核心调度）
  overlay_window.py     悬浮状态窗口（录音中/识别中/结果），支持运行时开关
  settings_window.py    ttkbootstrap 设置界面（快捷键、模式、麦克风、GPU 设备、输出选项）
utils/
  logger.py             日志配置
```

## 设置项

| 分类 | 项目 | 运行时热更新 |
|------|------|:---:|
| 快捷键 | 按键组合、录音模式（按住/切换） | ✓ |
| 语音识别 | ASR 模型、GPU 设备 | ✗ 需重启 |
| 音频输入 | 麦克风设备选择 | ✓ |
| 输出 | 提示音、悬浮窗、剪贴板恢复 | ✓ |

## 线程模型

- **主线程**: `ttkbootstrap.Window` + `tk.mainloop()` 阻塞（Windows 要求 Tcl/Tk 在主线程创建）
- **pystray 线程**: 系统托盘 `Icon.run()`（daemon 线程）
- **keyboard 线程**: 快捷键 press/release 事件 → 写入 cmd_queue
- **Worker 线程**: 从 cmd_queue 读命令，驱动录音→识别→粘贴流程
- **PortAudio 回调线程**: 音频帧写入 buffer

## 编码注意事项

### ctypes SendInput
- INPUT 结构体 union 必须包含 MOUSEINPUT + KEYBDINPUT + HARDWAREINPUT 三个成员，否则 `sizeof(INPUT)` 为 24（应为 40），`SendInput` 会静默失败
- `keyboard.send()` 底层用已废弃的 `keybd_event`，在 Win11 记事本和 cmd 中不可靠；用 ctypes `SendInput` 代替
- 调用粘贴前必须 `_release_modifiers()` 用 `GetAsyncKeyState` 检测并释放残留修饰键
- Cursor/VS Code 内嵌终端 (xterm.js) 对 SendInput Ctrl+V 不响应，属环境限制

### ttkbootstrap / tkinter
- **LabelFrame 不支持 `bootstyle=` 和 `padding=`**（Python 3.13，ttkbootstrap 猴子补丁映射到经典 tkinter.LabelFrame）。用子元素 `padx`/`pady` 替代
- **设置窗口不要写死高度**，用 `winfo_reqwidth/reqheight` 让内容决定窗口大小，否则高 DPI 下按钮会被裁掉
- `ttkbootstrap.Toplevel(master=parent)` 必须传 `master=`
- `after_idle` 是 Tk 跨线程调度的安全方式

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

### 通用
- 跨类访问用公开属性/方法，不直接读写 `_private` 成员
- 线程同步用 `threading.Event`，不用 `time.sleep`
