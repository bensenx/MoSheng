"""MoSheng launcher (cross-platform).

Windows: compiled to MoSheng.exe with PyInstaller, manages venv setup.
macOS: simple launcher (the .app bundle uses a shell script instead).
"""

import os
import subprocess
import sys

CURRENT_VERSION = "1.1.1"


def get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def fatal_msgbox(msg: str) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "MoSheng - 错误", 0x10)
    elif sys.platform == "darwin":
        try:
            escaped = msg.replace('\\', '\\\\').replace('"', '\\"')
            subprocess.run([
                "osascript", "-e",
                f'display dialog "{escaped}" with title "MoSheng - 错误" buttons {{"OK"}} default button "OK" with icon stop',
            ], timeout=30)
        except Exception:
            print(f"ERROR: {msg}", file=sys.stderr)
    else:
        print(f"ERROR: {msg}", file=sys.stderr)


# ---- Windows-specific setup ----

if sys.platform == "win32":
    CREATE_NEW_CONSOLE = 0x00000010

    def load_mirror_env(app_dir: str) -> None:
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
        setup_script = os.path.join(app_dir, "_setup.cmd")
        if not os.path.isfile(setup_script):
            fatal_msgbox(f"找不到安装脚本：{setup_script}")
            return False

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
                ["cmd", "/c", wrapper], cwd=app_dir,
                creationflags=CREATE_NEW_CONSOLE,
            )
        finally:
            try:
                os.remove(wrapper)
            except OSError:
                pass

        if ret != 0:
            log_path = os.path.join(app_dir, "_setup.log")
            detail = ""
            if os.path.isfile(log_path):
                with open(log_path, encoding="utf-8", errors="replace") as f:
                    detail = f.read().strip()[-500:]
            if detail:
                fatal_msgbox(f"安装失败（退出码 {ret}）:\n\n{detail}")
            else:
                fatal_msgbox(
                    f"安装失败（退出码 {ret}）。\n\n"
                    "请在 MoSheng 文件夹中手动运行 _setup.cmd 查看详细错误。"
                )
        return ret == 0

    def launch_app(app_dir: str) -> None:
        pythonw = os.path.join(app_dir, ".venv", "Scripts", "pythonw.exe")
        main_py = os.path.join(app_dir, "main.py")
        subprocess.Popen([pythonw, main_py], cwd=app_dir)


def main() -> None:
    app_dir = get_app_dir()

    if sys.platform == "win32":
        load_mirror_env(app_dir)
        if needs_setup(app_dir):
            if not run_setup(app_dir):
                fatal_msgbox("依赖安装失败，请检查网络连接后重试。")
                return
            load_mirror_env(app_dir)
        pythonw = os.path.join(app_dir, ".venv", "Scripts", "pythonw.exe")
        if not os.path.isfile(pythonw):
            fatal_msgbox("虚拟环境创建失败，请删除 .venv 文件夹后重试。")
            return
        launch_app(app_dir)
    else:
        # macOS / other: simple launch
        main_py = os.path.join(app_dir, "main.py")
        if not os.path.isfile(main_py):
            fatal_msgbox(f"找不到 main.py: {main_py}")
            return
        subprocess.Popen([sys.executable, main_py], cwd=app_dir)


if __name__ == "__main__":
    main()
