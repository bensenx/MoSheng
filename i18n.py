"""Internationalization module for MoSheng (墨声)."""

import logging

logger = logging.getLogger(__name__)

_current_language: str = "zh"

SUPPORTED_LANGUAGES = {
    "zh": "中文",
    "en": "English",
}

_TRANSLATIONS: dict[str, dict[str, str]] = {
    # ---- main.py ----
    "error.title": {
        "zh": "MoSheng - 错误",
        "en": "MoSheng - Error",
    },
    "error.pytorch_load_failed": {
        "zh": "PyTorch 加载失败: {error}",
        "en": "Failed to load PyTorch: {error}",
    },
    "error.no_microphone": {
        "zh": "未检测到麦克风: {error}",
        "en": "No microphone detected: {error}",
    },
    "error.unhandled_exception": {
        "zh": "程序发生未处理的异常，请查看日志文件。",
        "en": "An unhandled exception occurred. Please check the log file.",
    },
    "error.model_download_failed": {
        "zh": "模型下载失败:\n{error}",
        "en": "Model download failed:\n{error}",
    },
    "splash.downloading_model": {
        "zh": "正在下载模型 {name}...",
        "en": "Downloading model {name}...",
    },
    "splash.download_progress": {
        "zh": "正在下载模型... {percent}%",
        "en": "Downloading model... {percent}%",
    },

    # ---- ui/app.py (WorkerThread) ----
    "worker.no_content": {
        "zh": "未识别到内容",
        "en": "No content recognized",
    },
    "worker.too_short": {
        "zh": "录音太短",
        "en": "Recording too short",
    },
    "worker.recognition_failed": {
        "zh": "识别失败",
        "en": "Recognition failed",
    },

    # ---- ui/app.py (tray) ----
    "tray.ready": {
        "zh": "MoSheng - 就绪",
        "en": "MoSheng - Ready",
    },
    "tray.recording": {
        "zh": "MoSheng - 录音中",
        "en": "MoSheng - Recording",
    },
    "tray.recognizing": {
        "zh": "MoSheng - 识别中",
        "en": "MoSheng - Recognizing",
    },
    "tray.settings": {
        "zh": "设置",
        "en": "Settings",
    },
    "tray.quit": {
        "zh": "退出",
        "en": "Quit",
    },

    # ---- ui/overlay_window.py ----
    "overlay.recognizing": {
        "zh": "识别中...",
        "en": "Recognizing...",
    },
    "overlay.filtered": {
        "zh": "已过滤",
        "en": "Filtered",
    },
    "overlay.recording": {
        "zh": "录音中",
        "en": "Recording",
    },

    # ---- ui/settings_window.py ----
    "settings.title": {
        "zh": "MoSheng 设置",
        "en": "MoSheng Settings",
    },
    "settings.app_name": {
        "zh": "墨声",
        "en": "MoSheng",
    },
    "settings.subtitle": {
        "zh": "MoSheng \u00b7 本地智能语音输入",
        "en": "MoSheng \u00b7 Local Intelligent Voice Input",
    },
    "settings.language_label": {
        "zh": "界面语言",
        "en": "Language",
    },
    "settings.restart_hint": {
        "zh": "更改语言后需重启应用",
        "en": "Restart required after changing language",
    },
    "settings.restart_required": {
        "zh": "语言已更改，请重启应用以生效。\n\nLanguage changed. Please restart the app.",
        "en": "Language changed. Please restart the app.\n\n语言已更改，请重启应用以生效。",
    },
    # -- Hotkey section --
    "settings.hotkey_section": {
        "zh": "快捷键设置",
        "en": "Hotkey Settings",
    },
    "settings.hotkey_label": {
        "zh": "快捷键",
        "en": "Hotkey",
    },
    "settings.long_press_threshold": {
        "zh": "长按阈值",
        "en": "Long Press Threshold",
    },
    "settings.change_binding": {
        "zh": "修改绑定",
        "en": "Change Binding",
    },
    "settings.press_hotkey": {
        "zh": "请按下快捷键...",
        "en": "Press hotkey...",
    },
    "settings.waiting_input": {
        "zh": "等待输入...",
        "en": "Waiting for input...",
    },
    "settings.mode_label": {
        "zh": "录音模式",
        "en": "Recording Mode",
    },
    "settings.push_to_talk": {
        "zh": "按住录音",
        "en": "Push to Talk",
    },
    "settings.toggle_mode": {
        "zh": "按键切换",
        "en": "Toggle",
    },
    "settings.progressive_input": {
        "zh": "渐进式输入（停顿时自动输入已识别文本）",
        "en": "Progressive input (auto-type on pause)",
    },
    "settings.silence_threshold": {
        "zh": "静音阈值",
        "en": "Silence Threshold",
    },
    "settings.silence_duration": {
        "zh": "静音时长(秒)",
        "en": "Silence Duration (s)",
    },
    # -- ASR section --
    "settings.asr_section": {
        "zh": "语音识别",
        "en": "Speech Recognition",
    },
    "settings.asr_model": {
        "zh": "ASR 模型",
        "en": "ASR Model",
    },
    "settings.device_label": {
        "zh": "推理设备",
        "en": "Inference Device",
    },
    # -- Audio input section --
    "settings.audio_section": {
        "zh": "音频输入",
        "en": "Audio Input",
    },
    "settings.microphone": {
        "zh": "麦克风",
        "en": "Microphone",
    },
    "settings.system_default": {
        "zh": "系统默认",
        "en": "System Default",
    },
    # -- Speaker verification section --
    "settings.speaker_section": {
        "zh": "声纹识别",
        "en": "Speaker Verification",
    },
    "settings.enable_speaker": {
        "zh": "启用声纹验证",
        "en": "Enable Speaker Verification",
    },
    "settings.speaker_hint": {
        "zh": "注册声纹后，将自动过滤其他人的语音输入",
        "en": "After enrollment, voice input from others will be filtered",
    },
    "settings.enroll_voice": {
        "zh": "录制声纹",
        "en": "Enroll Voice",
    },
    "settings.enrolled_samples": {
        "zh": "已注册 ({count} 个样本)",
        "en": "Enrolled ({count} samples)",
    },
    "settings.enrolled": {
        "zh": "已注册",
        "en": "Enrolled",
    },
    "settings.not_enrolled": {
        "zh": "未注册声纹",
        "en": "Not Enrolled",
    },
    # -- Output section --
    "settings.output_section": {
        "zh": "输出设置",
        "en": "Output Settings",
    },
    "settings.sound_toggle": {
        "zh": "录音开始/结束提示音",
        "en": "Play sound on record start/stop",
    },
    "settings.sound_style_label": {
        "zh": "提示音",
        "en": "Notification Sound",
    },
    "settings.sound_style_bell": {
        "zh": "铃声",
        "en": "Bell",
    },
    "settings.sound_style_chime": {
        "zh": "风铃",
        "en": "Chime",
    },
    "settings.sound_style_soft": {
        "zh": "轻柔",
        "en": "Soft",
    },
    "settings.sound_style_off": {
        "zh": "关闭",
        "en": "Off",
    },
    "settings.overlay_toggle": {
        "zh": "显示悬浮状态窗口",
        "en": "Show floating status overlay",
    },
    "settings.restore_clipboard": {
        "zh": "粘贴后恢复剪贴板",
        "en": "Restore clipboard after paste",
    },
    # -- Vocabulary section --
    "settings.vocab_section": {
        "zh": "自定义词汇",
        "en": "Custom Vocabulary",
    },
    "settings.vocab_toggle": {
        "zh": "启用生词辅助识别",
        "en": "Enable vocabulary-assisted recognition",
    },
    "settings.vocab_hint": {
        "zh": "在 CSV 文件中添加专业术语、人名等，每行一个词汇",
        "en": "Add terms, names, etc. in CSV file (one per line)",
    },
    "settings.vocab_count": {
        "zh": "已收录 {count} 个词汇",
        "en": "{count} terms loaded",
    },
    "settings.open_vocab": {
        "zh": "打开词汇表",
        "en": "Open Vocabulary File",
    },
    "settings.vocab_file_header": {
        "zh": "# 每行一个词汇（专业术语、人名等），帮助语音识别更准确\n",
        "en": "# One term per line (technical terms, names, etc.) to improve recognition accuracy\n",
    },
    # -- General --
    "settings.general_section": {
        "zh": "通用",
        "en": "General",
    },
    "settings.autostart": {
        "zh": "开机自动启动",
        "en": "Start at login",
    },
    "settings.autostart_hint": {
        "zh": "登录 Windows 时自动启动墨声",
        "en": "Automatically start MoSheng when you log in",
    },
    "settings.restart_required_model": {
        "zh": "ASR 模型已更改，需要重启应用生效。\nThe ASR model has changed. Please restart to apply.",
        "en": "ASR 模型已更改，需要重启应用生效。\nThe ASR model has changed. Please restart to apply.",
    },
    # -- Buttons --
    "settings.save": {
        "zh": "保存",
        "en": "Save",
    },
    "settings.cancel": {
        "zh": "取消",
        "en": "Cancel",
    },

    # ---- ui/enrollment_dialog.py ----
    "enrollment.title": {
        "zh": "声纹注册",
        "en": "Voice Enrollment",
    },
    "enrollment.instruction": {
        "zh": "请在安静环境下录制 3 段语音样本",
        "en": "Please record 3 voice samples in a quiet environment",
    },
    "enrollment.sample_n": {
        "zh": "样本 {n}",
        "en": "Sample {n}",
    },
    "enrollment.prompt_1": {
        "zh": "请自然地说一段话，例如：今天天气真不错，适合出去散步。",
        "en": "Please speak naturally, e.g.: The weather is really nice today, perfect for a walk.",
    },
    "enrollment.prompt_2": {
        "zh": "请继续说一段话，例如：我正在使用墨声语音输入工具。",
        "en": "Please continue speaking, e.g.: I am using MoSheng voice input tool.",
    },
    "enrollment.prompt_3": {
        "zh": "最后一段，例如：声音化为笔墨，记录每一个想法。",
        "en": "Last one, e.g.: Voice turns to ink, recording every thought.",
    },
    "enrollment.start_recording": {
        "zh": "开始录制",
        "en": "Start Recording",
    },
    "enrollment.stop_recording": {
        "zh": "停止录制",
        "en": "Stop Recording",
    },
    "enrollment.recording": {
        "zh": "正在录制...",
        "en": "Recording...",
    },
    "enrollment.too_short": {
        "zh": "录音太短（至少 {seconds} 秒），请重试",
        "en": "Recording too short (min {seconds}s), please retry",
    },
    "enrollment.sample_done": {
        "zh": "样本 {n} 录制完成",
        "en": "Sample {n} recorded",
    },
    "enrollment.processing": {
        "zh": "正在处理声纹...",
        "en": "Processing voiceprint...",
    },
    "enrollment.failed": {
        "zh": "注册失败: {error}",
        "en": "Enrollment failed: {error}",
    },

    # -- Text processing section --
    "settings.text_processing_section": {
        "zh": "文本处理",
        "en": "Text Processing",
    },
    "settings.remove_fillers": {
        "zh": "去除语气词（嗯、啊、um、uh…）",
        "en": "Remove filler words (嗯, 啊, um, uh…)",
    },
    "settings.smart_punctuation": {
        "zh": "智能标点（分句自动转逗号，末句保留句号）",
        "en": "Smart punctuation (commas between clauses, period at end)",
    },

    # ---- core/speaker_verifier.py ----
    "verifier.model_not_loaded": {
        "zh": "模型未加载",
        "en": "Model not loaded",
    },
    "verifier.samples_too_different": {
        "zh": "样本 {i} 和 {j} 的声纹差异过大 (相似度: {score})，请在安静环境下重新录制",
        "en": "Samples {i} and {j} are too different (similarity: {score}). Please re-record in a quiet environment",
    },
    "verifier.enrollment_success": {
        "zh": "声纹注册成功",
        "en": "Voice enrollment successful",
    },
}


def set_language(lang: str) -> None:
    """Set the active language."""
    global _current_language
    if lang not in SUPPORTED_LANGUAGES:
        logger.warning("Unsupported language '%s', falling back to 'zh'", lang)
        lang = "zh"
    _current_language = lang
    logger.info("Language set to: %s", lang)


def get_language() -> str:
    """Return the current active language code."""
    return _current_language


def detect_system_language() -> str:
    """Auto-detect system locale, return 'en' or 'zh' (default)."""
    try:
        from PySide6.QtCore import QLocale
        locale_name = QLocale.system().name()
        if locale_name.startswith("en"):
            return "en"
    except Exception:
        pass
    return "zh"


def init_language(settings_manager) -> None:
    """Initialize language from settings, or auto-detect on first run."""
    saved = settings_manager.get("language", default=None)
    if saved and saved in SUPPORTED_LANGUAGES:
        set_language(saved)
    else:
        detected = detect_system_language()
        set_language(detected)
        settings_manager.set("language", detected)
        settings_manager.save()


def tr(key: str, **kwargs) -> str:
    """Look up a translated string by key, with optional format parameters.

    Usage:
        tr("settings.vocab_count", count=42)
        tr("enrollment.too_short", seconds=3)
    """
    entry = _TRANSLATIONS.get(key)
    if entry is None:
        logger.warning("Missing translation key: '%s'", key)
        return key

    text = entry.get(_current_language)
    if text is None:
        text = entry.get("zh", key)

    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            logger.warning("Format error for key '%s' with kwargs %s", key, kwargs)

    return text
