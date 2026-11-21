"""MoSheng launcher (cross-platform).

Windows: compiled to MoSheng.exe with PyInstaller, manages venv setup.
macOS: simple launcher (the .app bundle uses a shell script instead).
"""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time



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

    def runtime_home() -> Path:
        return Path(os.environ["LOCALAPPDATA"]) / "MoSheng"

    def dependency_variant() -> str:
        smi = shutil.which("nvidia-smi")
        if smi:
            try:
                probe = subprocess.run([smi, "-L"], capture_output=True, timeout=5,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
                if probe.returncode == 0 and b"GPU " in probe.stdout:
                    return "cuda"
            except (OSError, subprocess.TimeoutExpired):
                pass
        return "cpu"

    def runtime_for(app: Path, variant: str) -> Path:
        digest = hashlib.sha256(platform.machine().lower().encode("ascii"))
        for name in (f"pyproject-{variant}.toml", f"uv-{variant}.lock"):
            data = (app / "configs" / name).read_bytes().replace(b"\r\n", b"\n")
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
        return runtime_home() / "runtimes" / f"{variant}-{digest.hexdigest()[:20]}"

    def is_ready(runtime: Path) -> bool:
        try:
            marked = (runtime / ".ready").read_bytes() == b"ok\n"
        except OSError:
            return False
        return (marked and (runtime / ".venv/Scripts/pythonw.exe").is_file()
                and (runtime / ".venv/Scripts/python.exe").is_file())

    @contextmanager
    def setup_lock(home: Path):
        # Windows releases this byte-range lock if an installer exits unexpectedly.
        import errno
        import msvcrt
        home.mkdir(parents=True, exist_ok=True)
        with (home / "setup.lock").open("a+b") as lock:
            lock.seek(0)
            while True:
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno != errno.EACCES:
                        raise
                    time.sleep(0.2)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

    def launch_environment(app: Path) -> dict:
        env = os.environ.copy()
        for path in (runtime_home() / "mirror.env", app / "mirror.env"):
            if path.is_file():
                for line in path.read_text(encoding="utf-8-sig").splitlines():
                    key, sep, value = line.strip().partition("=")
                    if sep and key in ("UV_INDEX_URL", "HF_ENDPOINT"):
                        env[key] = value.strip()
        return env

    def ensure_runtime(app: Path) -> Path:
        variant = dependency_variant()
        runtime = runtime_for(app, variant)
        if is_ready(runtime):
            return runtime
        home = runtime_home()
        with setup_lock(home):
            if is_ready(runtime):
                return runtime
            runtime.mkdir(parents=True, exist_ok=True)
            marker = runtime / ".ready"
            marker.unlink(missing_ok=True)
            shutil.copyfile(app / "configs" / f"pyproject-{variant}.toml", runtime / "pyproject.toml")
            shutil.copyfile(app / "configs" / f"uv-{variant}.lock", runtime / "uv.lock")
            if (app / "mirror.env").is_file() and not (home / "mirror.env").exists():
                shutil.copyfile(app / "mirror.env", home / "mirror.env")
            env = launch_environment(app)
            env.update(UV_PROJECT_ENVIRONMENT=str(runtime / ".venv"), MOSHENG_RUNTIME=str(runtime),
                       MOSHENG_HOME=str(home))
            uv = app / "uv.exe"
            if not uv.is_file():
                raise OSError(f"Missing uv.exe in {app}")
            venv = runtime / ".venv"
            if venv.is_dir() and not all((venv / "Scripts" / name).is_file()
                                         for name in ("python.exe", "pythonw.exe")):
                # Repair the interpreter launchers in place, preserving installed wheels.
                repair = subprocess.run([str(uv), "venv", "--allow-existing", str(venv)],
                                        env=env, cwd=runtime, capture_output=True,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                if repair.returncode:
                    raise OSError(repair.stderr.decode("utf-8", errors="replace"))
            options = ["sync", "--project", str(runtime), "--frozen", "--no-install-project"]
            configured = (Path(os.environ["USERPROFILE"]) / ".mosheng/settings.json").is_file()
            # Existing installs can normally populate the shared runtime from uv's wheel cache.
            # Only bring up a console if a download or first-time configuration is needed.
            log = home / "_setup.log"
            installed = False
            if configured:
                with log.open("wb") as output:
                    installed = subprocess.run([str(uv), *options, "--offline"], env=env, cwd=app,
                                               stdout=output, stderr=subprocess.STDOUT,
                                               creationflags=subprocess.CREATE_NO_WINDOW).returncode == 0
            if not installed:
                code = subprocess.call(["cmd.exe", "/d", "/c", "_setup.cmd"], cwd=app,
                                       env=env, creationflags=CREATE_NEW_CONSOLE)
                if code:
                    detail = log.read_text(encoding="utf-8", errors="replace")[-600:] if log.is_file() else ""
                    raise OSError(f"Setup failed ({code}). {log}\n{detail}")
            if not all((runtime / ".venv/Scripts" / name).is_file() for name in ("python.exe", "pythonw.exe")):
                raise OSError(f"Setup did not create a Python runtime in {runtime}")
            (runtime / ".ready.tmp").write_bytes(b"ok\n")
            (runtime / ".ready.tmp").replace(marker)
        return runtime

    def launch_app(app: Path, runtime: Path) -> None:
        pythonw = runtime / ".venv/Scripts/pythonw.exe"
        subprocess.Popen([str(pythonw), str(app / "main.py")], cwd=app, env=launch_environment(app))


def main() -> None:
    app_dir = get_app_dir()

    if sys.platform == "win32":
        try:
            app = Path(app_dir)
            runtime = ensure_runtime(app)
            if "--setup-only" not in sys.argv[1:]:
                launch_app(app, runtime)
        except (OSError, UnicodeError) as exc:
            fatal_msgbox(str(exc))
            if "--setup-only" in sys.argv[1:]:
                raise SystemExit(1)
    else:
        # macOS / other: simple launch
        main_py = os.path.join(app_dir, "main.py")
        if not os.path.isfile(main_py):
            fatal_msgbox(f"找不到 main.py: {main_py}")
            return
        subprocess.Popen([sys.executable, main_py], cwd=app_dir)


if __name__ == "__main__":
    main()
