# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for VoiceInput."""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect transformers data files
transformers_datas = collect_data_files("transformers", include_py_files=True)
qwen_asr_datas = collect_data_files("qwen_asr", include_py_files=True)

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("assets", "assets"),
        *transformers_datas,
        *qwen_asr_datas,
    ],
    hiddenimports=[
        "torch",
        "transformers",
        "qwen_asr",
        "sounddevice",
        "numpy",
        "keyboard",
        "win32clipboard",
        "win32con",
        "pystray",
        "PIL",
        "ttkbootstrap",
        *collect_submodules("ttkbootstrap"),
        *collect_submodules("transformers"),
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "scipy",
        "pandas",
        "notebook",
        "IPython",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoiceInput",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico" if os.path.exists("assets/icon.ico") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VoiceInput",
)
