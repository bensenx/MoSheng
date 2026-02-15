"""MoSheng launcher — macOS version.

Simple launcher that checks for dependencies and starts the app.
"""

import os
import subprocess
import sys


def get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def fatal_msgbox(msg: str) -> None:
    try:
        escaped = msg.replace('\\', '\\\\').replace('"', '\\"')
        subprocess.run([
            "osascript", "-e",
            f'display dialog "{escaped}" with title "MoSheng - 错误" buttons {{"OK"}} default button "OK" with icon stop',
        ], timeout=30)
    except Exception:
        print(f"ERROR: {msg}", file=sys.stderr)


def main() -> None:
    app_dir = get_app_dir()
    main_py = os.path.join(app_dir, "main.py")

    if not os.path.isfile(main_py):
        fatal_msgbox(f"找不到 main.py: {main_py}")
        return

    subprocess.Popen([sys.executable, main_py], cwd=app_dir)


if __name__ == "__main__":
    main()
