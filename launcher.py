"""MoSheng launcher — compiled to MoSheng.exe with PyInstaller.

Checks if the venv is ready, runs first-time setup if needed,
then launches the app via pythonw.exe (no console window).

Only uses stdlib so the compiled exe stays small (~10 MB).
"""

import ctypes
import os
import subprocess
import sys

CURRENT_VERSION = "1.0.0"

CREATE_NEW_CONSOLE = 0x00000010


def get_app_dir() -> str:
    """Return the directory where the launcher (or script) lives."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def fatal_msgbox(msg: str) -> None:
    """Show a native Windows error dialog."""
    ctypes.windll.user32.MessageBoxW(0, msg, "MoSheng - 错误", 0x10)


def load_mirror_env(app_dir: str) -> None:
    """Parse mirror.env and inject vars into the current process env."""
    path = os.path.join(app_dir, "mirror.env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if key:
                    os.environ[key] = value


def needs_setup(app_dir: str) -> bool:
    """Check whether the venv exists and matches the current version."""
    venv_pythonw = os.path.join(app_dir, ".venv", "Scripts", "pythonw.exe")
    version_marker = os.path.join(app_dir, ".venv", ".mosheng_version")

    if not os.path.isfile(venv_pythonw):
        return True
    if not os.path.isfile(version_marker):
        return True
    with open(version_marker, encoding="utf-8") as f:
        if f.read().strip() != CURRENT_VERSION:
            return True
    return False


def run_setup(app_dir: str) -> bool:
    """Run _setup.cmd in a new console window. Returns True on success."""
    setup_script = os.path.join(app_dir, "_setup.cmd")
    if not os.path.isfile(setup_script):
        fatal_msgbox(f"找不到安装脚本：{setup_script}")
        return False

    # Write a tiny wrapper script that:
    #   - calls _setup.cmd
    #   - on failure, keeps the console open so the user can read errors
    #   - on success, exits cleanly (console closes)
    # This avoids cmd /c quoting issues and guarantees errors are visible.
    wrapper = os.path.join(app_dir, "_run_setup.cmd")
    with open(wrapper, "w", encoding="ascii") as f:
        f.write("@echo off\r\n")
        f.write('call "%~dp0_setup.cmd"\r\n')
        f.write("if errorlevel 1 (\r\n")
        f.write("    echo.\r\n")
        f.write("    echo Setup failed. Press any key to close...\r\n")
        f.write("    pause >nul\r\n")
        f.write(")\r\n")
        f.write("exit\r\n")

    try:
        ret = subprocess.call(
            ["cmd", "/c", wrapper],
            cwd=app_dir,
            creationflags=CREATE_NEW_CONSOLE,
        )
    finally:
        try:
            os.remove(wrapper)
        except OSError:
            pass

    if ret != 0:
        # Check if _setup.cmd left a log file with details
        log_path = os.path.join(app_dir, "_setup.log")
        detail = ""
        if os.path.isfile(log_path):
            with open(log_path, encoding="utf-8", errors="replace") as f:
                detail = f.read().strip()[-500:]  # last 500 chars
        if detail:
            fatal_msgbox(f"安装失败（退出码 {ret}）:\n\n{detail}")
        else:
            fatal_msgbox(
                f"安装失败（退出码 {ret}）。\n\n"
                "请在 MoSheng 文件夹中手动运行 _setup.cmd 查看详细错误。"
            )
    return ret == 0


def launch_app(app_dir: str) -> None:
    """Start the main application via pythonw.exe (no console)."""
    pythonw = os.path.join(app_dir, ".venv", "Scripts", "pythonw.exe")
    main_py = os.path.join(app_dir, "main.py")

    subprocess.Popen(
        [pythonw, main_py],
        cwd=app_dir,
    )


def main() -> None:
    app_dir = get_app_dir()

    # Load mirror config so HF_ENDPOINT is set before the app imports
    load_mirror_env(app_dir)

    if needs_setup(app_dir):
        if not run_setup(app_dir):
            fatal_msgbox("依赖安装失败，请检查网络连接后重试。")
            return
        # Reload mirror.env in case _setup.cmd just created it
        load_mirror_env(app_dir)

    # Final check
    pythonw = os.path.join(app_dir, ".venv", "Scripts", "pythonw.exe")
    if not os.path.isfile(pythonw):
        fatal_msgbox("虚拟环境创建失败，请删除 .venv 文件夹后重试。")
        return

    launch_app(app_dir)


if __name__ == "__main__":
    main()
