# MoSheng (墨声)

声音，化为笔墨。Windows 本地智能语音输入工具，基于 Qwen3-ASR-1.7B。支持**按住录音**和**按键切换**两种模式，松开/再按后自动识别并粘贴文本。支持**渐进式输入**（停顿时自动输入已识别文本）。暗色毛玻璃 Glassmorphism UI 风格。

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
i18n.py                 国际化：73 个翻译键（zh/en），tr() 查找 + 系统语言自动检测
settings_manager.py     用户设置持久化 (~/.mosheng/settings.json)
pyproject.toml          UV 项目配置（依赖、CUDA 索引、构建）
launcher.py             分发包入口（仅 stdlib，PyInstaller 编译为 MoSheng.exe）
_setup.cmd              首次运行安装脚本（GPU 检测、镜像选择、uv sync）
core/
  asr_base.py           ASR 抽象基类 (ABC)，可替换模型
  asr_qwen.py           Qwen3-ASR-1.7B 实现（含音频诊断日志）
  audio_recorder.py     sounddevice 录音，16kHz 单声道 float32，支持指定设备，drain_buffer + EMA RMS
  speaker_verifier.py   声纹识别：SpeechBrain ECAPA-TDNN 两级验证（快速路径/慢速分段）
  text_injector.py      剪贴板写入 + ctypes SendInput 模拟 Ctrl+V，hotkey-aware 修饰键释放
  hotkey_manager.py     WH_KEYBOARD_LL 钩子级按键抑制 + VK 码分组匹配，支持 push_to_talk / toggle
  key_suppression_hook.py  ctypes 低级键盘钩子，选择性抑制物理按键，放行 SendInput 注入事件
ui/
  app.py                QSystemTrayIcon + WorkerThread 组件协调器（核心调度）
  splash_screen.py      启动加载界面（glassmorphism，模型加载期间显示）
  overlay_window.py     QWidget 悬浮状态窗口（录音中/识别中/结果/已过滤），click-through + fade animation
  enrollment_dialog.py  声纹注册引导对话框（3 段录音 + 背景线程处理）
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
| 快捷键 | 按键组合、录音模式（按住/切换）、渐进式输入、静音阈值/时长 | ✓ |
| 语言 | 界面语言（中文/English） | ✗ 需重启 |
| 语音识别 | ASR 模型、GPU 设备 | ✗ 需重启 |
| 音频输入 | 麦克风设备选择 | ✓ |
| 输出 | 提示音、悬浮窗、剪贴板恢复 | ✓ |
| 词汇 | 自定义词汇表、CSV/TXT 导入 | ✓ |
| 声纹识别 | 启用/禁用、注册声纹、阈值配置 | ✓ 懒加载/卸载 |

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
- **KeySuppressionHook 线程**: WH_KEYBOARD_LL 钩子 + 消息泵，VK 码分组匹配触发 start/stop → 写入 worker cmd_queue
- **WorkerThread (QThread)**: 从 cmd_queue 读命令，驱动录音→声纹验证→识别→粘贴流程，通过 `state_changed` 信号更新 UI；渐进模式下 50ms 轮询 RMS 检测停顿
- **PortAudio 回调线程**: 音频帧写入 buffer

## 编码注意事项

### ctypes SendInput
- INPUT 结构体 union 必须包含 MOUSEINPUT + KEYBDINPUT + HARDWAREINPUT 三个成员，否则 `sizeof(INPUT)` 为 24（应为 40），`SendInput` 会静默失败
- `keyboard.send()` 底层用已废弃的 `keybd_event`，在 Win11 记事本和 cmd 中不可靠；用 ctypes `SendInput` 代替
- `_send_ctrl_v(hotkey_vks)` 接收快捷键 VK 集合，跳过被钩子抑制的按键（OS 不认为它们被按下），仅释放非快捷键修饰键
- Cursor/VS Code 内嵌终端 (xterm.js) 对 SendInput Ctrl+V 不响应，属环境限制

### WH_KEYBOARD_LL 钩子 (key_suppression_hook.py)
- 钩子回调必须在有消息泵的线程上运行（`GetMessageW` 循环），否则收不到事件
- `SetWindowsHookExW` 的 argtypes/restype 必须显式声明为 `c_void_p`，默认 `c_int` 在 64 位系统上截断句柄
- 通过 `LLKHF_INJECTED` 标志区分物理按键和 SendInput 注入事件，注入事件始终放行
- 回调返回 1 抑制事件（不调用 `CallNextHookEx`），返回 `CallNextHookEx(...)` 放行
- 快捷键在钩子层面被吞掉 → OS 完全看不到 → 无 Win 键开始菜单、无截图、无剪贴板历史等副作用

### 快捷键 VK 码分组匹配
- 每个按键名映射为一组 VK 码：如 "ctrl" → `{0x11, 0xA2, 0xA3}`（通用 + 左 + 右）
- 匹配条件：每个组中至少有一个 VK 被按下（`_all_groups_pressed()`），而非要求所有 VK 同时按下
- VK 码表来自 `keyboard._winkeyboard.official_virtual_keys`，仅读取数据不使用其钩子

### PySide6 / Qt
- `QApplication.setQuitOnLastWindowClosed(False)` — 托盘应用必须设置，否则关闭设置窗口会退出程序
- 跨线程 UI 更新用 Qt 信号/槽（自动 `QueuedConnection`）或 `QMetaObject.invokeMethod`
- Overlay click-through 用 `winId()` 直接获取 HWND + Windows API `SetWindowLongW`
- `Qt.WA_TranslucentBackground` + `paintEvent` 中 `QPainter.drawRoundedRect` 实现圆角透明窗口
- QSS 样式表集中在 `ui/styles.py`，全局应用于 `QApplication`
- 统一图标渲染：`load_icon_pixmap(logical_size)` + `draw_section_icon()` 以屏幕实际 DPR 渲染（`_screen_dpr()`），避免非整数缩放模糊
- Splash screen 不用 DWM Acrylic（会产生系统边框），仅 `WA_TranslucentBackground` + `paintEvent`
- Splash 直接设 `setWindowOpacity(1.0)`，主线程阻塞时 fade-in 动画不运行

### keyboard 库
- 快捷键监听已改用 WH_KEYBOARD_LL 钩子（`key_suppression_hook.py`），keyboard 库仅用于设置窗口的快捷键捕获 UI 和 VK 码表查询
- Windows 按住键会连续触发 KEY_DOWN，push_to_talk 用 `_is_active` 防抖，toggle 用 `_toggle_fired` 防抖
- KEY_UP 事件可能因窗口焦点切换丢失

### 渐进式输入 (progressive input)
- WorkerThread 在 `_handle_start()` 末尾进入 `_run_progressive_loop()`，50ms 轮询 cmd_queue + EMA 平滑 RMS
- 语音→静音转换后等待 `silence_duration`（默认 0.8s），然后 `drain_buffer()` + `_flush_and_inject()`
- 每个分段都经过声纹验证（如已启用）和词汇表上下文
- 剪贴板在循环开始前 `save_clipboard()`，每段用 `inject_text_no_restore()`，循环结束后一次性 `restore_saved_clipboard()`
- 最终 flush 失败时：若之前有成功注入则发 STATE_IDLE（清除 overlay），否则发 STATE_ERROR

### 音频录制
- `sounddevice.InputStream(device=N)` 指定输入设备，`None` 为系统默认
- ASR 返回空文本时先检查麦克风：日志中 `Audio stats: rms=` 若接近 0 说明麦克风未采集到声音
- 用户环境有多个音频设备（无线麦、虚拟声卡、蓝牙耳机），务必提供设备选择

### PyTorch
- `torch.cuda.get_device_properties(0).total_memory`（不是 `total_mem`）
- Python 3.14 暂无 PyTorch CUDA wheels（截至 2026-02）

### 国际化 (i18n.py)
- 简单 Python 字典方案：`_TRANSLATIONS[key][lang]`，无外部依赖
- `tr(key, **kwargs)` 查找翻译 + `str.format()`，回退链：当前语言 → zh → key 字符串
- `init_language(settings_manager)` 在启动时调用：从设置读取，首次运行用 `QLocale.system().name()` 自动检测
- 语言切换需重启（保存时弹出双语 `QMessageBox` 提示），避免运行时全量刷新 UI 的复杂度
- 模块级常量（如 `PROMPTS` 列表）不可在导入时调用 `tr()`，须改为函数延迟求值（如 `_get_prompts()`）
- `speaker_verifier.py` 中用局部 `from i18n import tr` 而非顶层导入，因为 speechbrain import 是延迟的

### 启动流程（main.py）
- 单实例保护：`CreateMutexW("MoSheng_SingleInstance")` + `GetLastError() == 183`
- QApplication 在模型加载**之前**创建，以便显示 splash screen
- `SettingsManager()` + `init_language()` 在 splash 之前初始化，确保后续 `tr()` 可用
- 模型加载在主线程阻塞，splash 保持可见但动画暂停（已足够提供视觉反馈）

### 声纹识别 (speaker_verifier.py)
- 模型：SpeechBrain ECAPA-TDNN (`speechbrain/spkrec-ecapa-voxceleb`)，192 维嵌入
- torchaudio 2.10+ 移除了 `list_audio_backends()`，需在 import speechbrain 前加 shim
- 两级验证：快速路径（整段音频嵌入 vs 质心，<50ms）→ 慢速路径（2s 窗口逐段分析）
- 阈值：high=0.40 直接通过，low=0.10 直接拒绝，中间进入慢速路径
- 注册：3 段音频 → 提取嵌入 → 交叉验证成对余弦相似度 → 计算质心 → 保存到 `~/.mosheng/speaker/`
- 懒加载：默认禁用，运行时可通过设置开关加载/卸载模型（`_apply_settings` 中处理）
- speechbrain 仅在 `load_model()` 方法内 import，禁用时零 import 开销
- `QTimer.singleShot` 不可取消 — 注册录制的自动停止和 overlay 隐藏定时器必须用可取消的 `QTimer` 实例（overlay 的 `_hide_timer` 在 `set_state()` 时 `.stop()` 防止渐进模式下结果闪烁）

### 通用
- 跨类访问用公开属性/方法，不直接读写 `_private` 成员
- 线程同步用 `threading.Event`，不用 `time.sleep`
