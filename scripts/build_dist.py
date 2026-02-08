"""Build MoSheng distribution package.

Usage:
    uv run python scripts/build_dist.py

Produces dist/MoSheng/ containing everything needed to run the app.
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(ROOT, "dist", "MoSheng")

# Source files and directories to include in the distribution
SRC_FILES = [
    "main.py",
    "config.py",
    "settings_manager.py",
    "i18n.py",
    "_setup.cmd",
]

SRC_DIRS = [
    "core",
    "ui",
    "utils",
    "assets",
    "configs",
]


def clean():
    """Remove previous build artifacts."""
    if os.path.exists(DIST_DIR):
        print(f"Cleaning {DIST_DIR} ...")
        shutil.rmtree(DIST_DIR)

    # PyInstaller build artifacts
    build_dir = os.path.join(ROOT, "build")
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)

    spec_tmp = os.path.join(ROOT, "launcher.spec")
    if os.path.isfile(spec_tmp):
        os.remove(spec_tmp)


def build_launcher():
    """Compile launcher.py to MoSheng.exe with PyInstaller."""
    print("\n=== Building MoSheng.exe launcher ===")
    launcher_py = os.path.join(ROOT, "launcher.py")
    icon_path = os.path.join(ROOT, "assets", "icon.ico")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name=MoSheng",
        "--distpath", DIST_DIR,
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", ROOT,
    ]
    if os.path.isfile(icon_path):
        cmd.extend(["--icon", icon_path])
    cmd.append(launcher_py)

    subprocess.run(cmd, check=True, cwd=ROOT)

    # Clean up generated .spec file
    spec_file = os.path.join(ROOT, "MoSheng.spec")
    if os.path.isfile(spec_file):
        os.remove(spec_file)

    exe_path = os.path.join(DIST_DIR, "MoSheng.exe")
    if not os.path.isfile(exe_path):
        raise RuntimeError("MoSheng.exe was not created")
    print(f"  -> {exe_path} ({os.path.getsize(exe_path) / 1024 / 1024:.1f} MB)")


def copy_sources():
    """Copy application source files to dist."""
    print("\n=== Copying source files ===")
    for fname in SRC_FILES:
        src = os.path.join(ROOT, fname)
        dst = os.path.join(DIST_DIR, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            print(f"  {fname}")
        else:
            print(f"  WARNING: {fname} not found, skipping")

    for dname in SRC_DIRS:
        src = os.path.join(ROOT, dname)
        dst = os.path.join(DIST_DIR, dname)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", "*.pyo",
            ))
            print(f"  {dname}/")
        else:
            print(f"  WARNING: {dname}/ not found, skipping")


def copy_uv():
    """Copy uv.exe to dist."""
    print("\n=== Copying uv.exe ===")
    uv_path = shutil.which("uv")
    if uv_path is None:
        raise RuntimeError("uv not found in PATH")
    dst = os.path.join(DIST_DIR, "uv.exe")
    shutil.copy2(uv_path, dst)
    print(f"  {uv_path} -> {dst} ({os.path.getsize(dst) / 1024 / 1024:.1f} MB)")


def report_size():
    """Print final distribution size summary."""
    print("\n=== Distribution summary ===")
    total = 0
    for dirpath, _dirnames, filenames in os.walk(DIST_DIR):
        for f in filenames:
            fpath = os.path.join(dirpath, f)
            size = os.path.getsize(fpath)
            total += size
            rel = os.path.relpath(fpath, DIST_DIR)
            if size > 1024 * 1024:
                print(f"  {rel:50s} {size / 1024 / 1024:8.1f} MB")
    print(f"\n  Total: {total / 1024 / 1024:.1f} MB")
    print(f"  Output: {DIST_DIR}")


def main():
    os.chdir(ROOT)
    clean()
    os.makedirs(DIST_DIR, exist_ok=True)
    build_launcher()
    copy_sources()
    copy_uv()
    report_size()
    print("\nBuild complete!")


if __name__ == "__main__":
    main()
