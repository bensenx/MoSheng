"""Build MoSheng macOS DMG distribution package.

Usage:
    uv run python scripts/build_macos.py

Produces dist/MoSheng-v1.1.0-macOS.dmg containing MoSheng.app.
"""

import os
import shutil
import subprocess
import sys
import plistlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "dist", "MoSheng.app")
CONTENTS = os.path.join(APP_DIR, "Contents")
MACOS_DIR = os.path.join(CONTENTS, "MacOS")
RESOURCES_DIR = os.path.join(CONTENTS, "Resources")
APP_RESOURCES = os.path.join(RESOURCES_DIR, "app")
DMG_NAME = "MoSheng-v1.1.0-macOS.dmg"

SRC_FILES = [
    "main.py",
    "config.py",
    "settings_manager.py",
    "i18n.py",
    "launcher.py",
    "pyproject.toml",
    "uv.lock",
]

SRC_DIRS = [
    "core",
    "ui",
    "utils",
    "assets",
    "configs",
]

LAUNCHER_SCRIPT = r"""#!/bin/bash
APP_DIR="$(cd "$(dirname "$0")/../Resources/app" && pwd)"
cd "$APP_DIR"

# First run: create venv and install deps
if [ ! -d ".venv" ]; then
    osascript -e 'display notification "正在安装依赖，首次启动需要几分钟..." with title "MoSheng 墨声"'
    ./uv sync 2>&1 | tee /tmp/mosheng-setup.log
    if [ $? -ne 0 ]; then
        osascript -e 'display alert "MoSheng Setup Failed" message "依赖安装失败，请检查网络连接。\n日志：/tmp/mosheng-setup.log" as critical'
        exit 1
    fi
fi

# Run the app
exec ./.venv/bin/python main.py "$@"
"""


def clean():
    print("Cleaning old build artifacts...")
    if os.path.exists(APP_DIR):
        shutil.rmtree(APP_DIR)
    dmg_path = os.path.join(ROOT, "dist", DMG_NAME)
    if os.path.exists(dmg_path):
        os.remove(dmg_path)


def create_app_structure():
    print("Creating .app bundle structure...")
    os.makedirs(MACOS_DIR, exist_ok=True)
    os.makedirs(APP_RESOURCES, exist_ok=True)


def create_info_plist():
    print("Creating Info.plist...")
    plist = {
        "CFBundleName": "MoSheng",
        "CFBundleDisplayName": "MoSheng 墨声",
        "CFBundleIdentifier": "com.mosheng.app",
        "CFBundleVersion": "1.1.0",
        "CFBundleShortVersionString": "1.1.0",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "mosheng",
        "CFBundleIconFile": "icon",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": "MoSheng 需要麦克风权限来进行语音输入",
        "NSAppleEventsUsageDescription": "MoSheng 需要辅助功能来模拟键盘输入",
    }
    with open(os.path.join(CONTENTS, "Info.plist"), "wb") as f:
        plistlib.dump(plist, f)


def create_launcher():
    print("Creating launcher script...")
    launcher_path = os.path.join(MACOS_DIR, "mosheng")
    with open(launcher_path, "w") as f:
        f.write(LAUNCHER_SCRIPT)
    os.chmod(launcher_path, 0o755)


def create_icon():
    print("Creating icon.icns...")
    icon_png = os.path.join(ROOT, "assets", "icon.png")
    if not os.path.isfile(icon_png):
        print("  WARNING: assets/icon.png not found, skipping icon")
        return

    iconset_dir = os.path.join(ROOT, "build", "icon.iconset")
    os.makedirs(iconset_dir, exist_ok=True)

    # Generate required icon sizes
    sizes = [16, 32, 64, 128, 256, 512]
    for size in sizes:
        subprocess.run(["sips", "-z", str(size), str(size), icon_png,
                        "--out", os.path.join(iconset_dir, f"icon_{size}x{size}.png")],
                       capture_output=True)
        # @2x variants
        if size <= 512:
            subprocess.run(["sips", "-z", str(size*2), str(size*2), icon_png,
                            "--out", os.path.join(iconset_dir, f"icon_{size}x{size}@2x.png")],
                           capture_output=True)

    icns_path = os.path.join(RESOURCES_DIR, "icon.icns")
    result = subprocess.run(["iconutil", "-c", "icns", iconset_dir, "-o", icns_path],
                           capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  WARNING: iconutil failed: {result.stderr}")
    else:
        print(f"  -> {icns_path}")

    shutil.rmtree(iconset_dir, ignore_errors=True)


def copy_sources():
    print("Copying source files...")
    for fname in SRC_FILES:
        src = os.path.join(ROOT, fname)
        dst = os.path.join(APP_RESOURCES, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            print(f"  {fname}")
        else:
            print(f"  WARNING: {fname} not found, skipping")

    for dname in SRC_DIRS:
        src = os.path.join(ROOT, dname)
        dst = os.path.join(APP_RESOURCES, dname)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", "*.pyo",
            ))
            print(f"  {dname}/")
        else:
            print(f"  WARNING: {dname}/ not found, skipping")


def copy_uv():
    print("Copying uv binary...")
    uv_path = shutil.which("uv")
    if uv_path is None:
        raise RuntimeError("uv not found in PATH")
    dst = os.path.join(APP_RESOURCES, "uv")
    shutil.copy2(uv_path, dst)
    os.chmod(dst, 0o755)
    print(f"  {uv_path} -> {dst} ({os.path.getsize(dst) / 1024 / 1024:.1f} MB)")


def create_dmg():
    print(f"\nCreating {DMG_NAME}...")
    dmg_staging = "/tmp/mosheng-dmg"
    if os.path.exists(dmg_staging):
        shutil.rmtree(dmg_staging)
    os.makedirs(dmg_staging)

    # Copy .app
    shutil.copytree(APP_DIR, os.path.join(dmg_staging, "MoSheng.app"), symlinks=True)

    # Applications shortcut
    os.symlink("/Applications", os.path.join(dmg_staging, "Applications"))

    dmg_path = os.path.join(ROOT, "dist", DMG_NAME)
    subprocess.run([
        "hdiutil", "create",
        "-volname", "MoSheng",
        "-srcfolder", dmg_staging,
        "-ov", "-format", "UDZO",
        dmg_path,
    ], check=True)

    shutil.rmtree(dmg_staging)
    print(f"  -> {dmg_path} ({os.path.getsize(dmg_path) / 1024 / 1024:.1f} MB)")


def report_size():
    print("\n=== Distribution summary ===")
    total = 0
    for dirpath, _, filenames in os.walk(APP_DIR):
        for f in filenames:
            fpath = os.path.join(dirpath, f)
            size = os.path.getsize(fpath)
            total += size
            rel = os.path.relpath(fpath, APP_DIR)
            if size > 1024 * 1024:
                print(f"  {rel:50s} {size / 1024 / 1024:8.1f} MB")
    print(f"\n  Total (uncompressed): {total / 1024 / 1024:.1f} MB")


def main():
    os.chdir(ROOT)
    clean()
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    create_app_structure()
    create_info_plist()
    create_launcher()
    create_icon()
    copy_sources()
    copy_uv()
    report_size()
    create_dmg()
    print("\nBuild complete!")


if __name__ == "__main__":
    main()
