"""Windows clipboard and installer regressions, plus offline Qwen cache recovery."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from safetensors.numpy import save_file

from core import model_downloader as models


@unittest.skipUnless(sys.platform == "win32", "Windows login startup")
class AutostartTests(unittest.TestCase):
    def test_registration_and_existing_entries(self):
        from utils import autostart
        reg = self.enterContext(patch.object(autostart, "winreg"))
        reg.REG_SZ = 1
        reg.KEY_QUERY_VALUE = 1
        reg.KEY_SET_VALUE = 2
        cmd = autostart._get_executable_command()
        self.assertTrue(cmd.endswith('" --autostart'))
        self.assertTrue(autostart.set_autostart(True))
        self.assertEqual(reg.SetValueEx.call_args.args[-1], cmd)
        reg.SetValueEx.reset_mock()
        reg.QueryValueEx.return_value = (cmd.removesuffix(" --autostart"), 1)
        autostart.refresh_autostart_command()
        self.assertEqual(reg.SetValueEx.call_args.args[-1], cmd)
        reg.SetValueEx.reset_mock()
        for existing in (cmd, '"custom-wrapper.exe" --custom-option'):
            reg.QueryValueEx.return_value = (existing, 1)
            autostart.refresh_autostart_command()
        reg.QueryValueEx.side_effect = FileNotFoundError
        autostart.refresh_autostart_command()
        reg.SetValueEx.assert_not_called()

    def test_launcher_forwards_only_the_login_flag(self):
        import launcher
        root = Path("C:/MoSheng Test")
        with patch.object(launcher.subprocess, "Popen") as start:
            for args in ([], ["--autostart"]):
                with patch.object(sys, "argv", ["MoSheng.exe", *args]):
                    launcher.launch_app(root, root / "runtime")
                self.assertEqual(start.call_args.args[0][1:], [str(root / "main.py"), *args])


@unittest.skipUnless(sys.platform == "win32", "Windows clipboard")
class ClipboardTests(unittest.TestCase):
    def setUp(self):
        from core import text_injector as module
        clip = self.enterContext(patch.object(module, "win32clipboard", autospec=True))
        self.formats = {module.win32con.CF_UNICODETEXT: "original"}
        clip.IsClipboardFormatAvailable.side_effect = self.formats.__contains__
        clip.GetClipboardData.side_effect = self.formats.__getitem__
        clip.SetClipboardData.side_effect = self.formats.__setitem__
        clip.EmptyClipboard.side_effect = self.formats.clear
        clip.RegisterClipboardFormat.return_value = 0xC001
        self.text_format = module.win32con.CF_UNICODETEXT
        self.enterContext(patch.object(module.time, "sleep"))
        self.enterContext(patch.object(module, "_send_paste"))
        self.timers = self.enterContext(patch.object(module.threading, "Timer"))
        self.injector = module.TextInjector()

    def copy(self, text):
        self.formats.clear()
        self.formats[self.text_format] = text

    def fire(self, index):
        call = self.timers.call_args_list[index]
        call.args[1](*call.kwargs["args"])

    def test_new_copy_of_identical_text_survives_restore(self):
        self.injector.inject_text("dictated")
        self.copy("dictated")
        self.fire(0)
        self.assertEqual(self.formats[self.text_format], "dictated")

    def test_overlapping_timers_restore_original_in_either_order(self):
        for first, second in ((0, 1), (1, 0)):
            with self.subTest(first=first):
                self.timers.reset_mock()
                self.injector.inject_text("first")
                self.injector.inject_text("second")
                self.fire(first)
                self.assertEqual(self.formats[self.text_format], "second" if first == 0 else "original")
                self.fire(second)
                self.assertEqual(self.formats[self.text_format], "original")

    def test_progressive_restores_latest_external_copy(self):
        for copy_between in (False, True):
            with self.subTest(copy_between=copy_between):
                self.injector.save_clipboard()
                self.copy("before first paste")
                self.injector.inject_text_no_restore("part one")
                if copy_between:
                    self.copy("between segments")
                self.injector.inject_text_no_restore("part two")
                self.injector.restore_saved_clipboard()
                self.fire(-1)
                self.assertEqual(self.formats[self.text_format],
                                 "between segments" if copy_between else "before first paste")

    def test_empty_session_and_disabled_restore_do_not_schedule(self):
        self.injector.save_clipboard()
        self.injector.restore_saved_clipboard()
        self.injector.restore_clipboard = False
        self.injector.inject_text("keep me")
        self.timers.assert_not_called()
        self.assertEqual(self.formats, {self.text_format: "keep me"})


class CacheTests(unittest.TestCase):
    def setUp(self):
        from huggingface_hub import constants
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(constants, "HF_HUB_CACHE", str(root)))
        self.model_id = "Qwen/Qwen3-ASR-1.7B"
        repo = root / "models--Qwen--Qwen3-ASR-1.7B"
        self.revision = "a" * 40
        (repo / "refs").mkdir(parents=True)
        self.ref = repo / "refs" / "main"
        self.snapshot = repo / "snapshots" / self.revision
        self.snapshot.mkdir(parents=True)
        self.remote = root / "remote"
        self.remote.mkdir()
        self.shards = ["model-00001-of-00002.safetensors", "model-00002-of-00002.safetensors"]

    def write_model(self, directory, sharded):
        for name in models._CONFIG_FILES:
            (directory / name).write_text('{"sample":1}' if name.endswith(".json") else "#version: 0.2\na b")
        tensor = np.arange(3, dtype=np.float32)
        if sharded:
            mapping = {"layer0": self.shards[0], "layer1": self.shards[1]}
            for key, name in mapping.items():
                save_file({key: tensor}, directory / name)
            (directory / models._INDEX).write_text(json.dumps({"weight_map": mapping}))
        else:
            save_file({"layer0": tensor}, directory / "model.safetensors")

    def test_only_the_complete_selected_revision_is_available_offline(self):
        self.ref.write_text(self.revision)
        self.assertIsNone(models.cached_snapshot(self.model_id))
        self.write_model(self.snapshot, sharded=False)
        self.assertEqual(models.cached_snapshot(self.model_id), self.snapshot)
        self.ref.write_text("b" * 40)
        self.assertIsNone(models.cached_snapshot(self.model_id))
        self.ref.write_text(self.revision)
        (self.snapshot / "tokenizer_config.json").write_text("{")
        self.assertIsNone(models.cached_snapshot(self.model_id))

    def test_interrupted_sharded_download_resumes_and_repairs_corruption(self):
        self.write_model(self.remote, sharded=True)
        files = sorted(self.remote.iterdir())
        siblings = [SimpleNamespace(rfilename=f.name, size=f.stat().st_size) for f in files]
        interrupt = True
        forced = []

        def download(model_id, name, revision=None, force_download=False):
            nonlocal interrupt
            self.assertEqual(model_id, self.model_id)
            if revision is None:
                self.assertEqual(name, "config.json")
                self.ref.write_text(self.revision)
            else:
                self.assertEqual(revision, self.revision)
            if name == self.shards[1] and interrupt:
                interrupt = False
                raise OSError("interrupted")
            if force_download:
                forced.append(name)
            path = self.snapshot / name
            if force_download or not path.exists():
                shutil.copyfile(self.remote / name, path)
            return str(path)

        self.enterContext(patch("huggingface_hub.hf_hub_download", side_effect=download))
        info = self.enterContext(patch("huggingface_hub.model_info", return_value=SimpleNamespace(siblings=siblings)))
        first = models.ModelDownloadThread(self.model_id)
        with self.assertLogs(models.logger, level="ERROR"):
            first.run()
        self.assertIsNone(first.snapshot)
        self.assertEqual(first.failure, "interrupted")
        self.assertIsNone(models.cached_snapshot(self.model_id))
        bad = self.snapshot / self.shards[0]
        bad.write_bytes(b"x" * bad.stat().st_size)
        retry = models.ModelDownloadThread(self.model_id)
        retry.run()
        self.assertEqual(retry.failure, "")
        self.assertEqual(retry.snapshot, self.snapshot)
        self.assertEqual(forced, [self.shards[0]])
        info.assert_called_with(self.model_id, revision=self.revision, files_metadata=True)
        self.assertEqual(models.cached_snapshot(self.model_id), self.snapshot)
        (self.snapshot / self.shards[1]).unlink()
        self.assertIsNone(models.cached_snapshot(self.model_id))


@unittest.skipUnless(sys.platform == "win32" and shutil.which("uv"), "Windows with uv")
class InstallerTests(unittest.TestCase):
    def setUp(self):
        import launcher
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())) / "MoSheng tests"
        self.root.mkdir()
        self.app = self.root / "Build one"
        self.app.mkdir()
        self.profile = self.root / "profile"
        self.profile.mkdir()
        env = dict(USERPROFILE=str(self.profile), LOCALAPPDATA=str(self.profile / "Local"),
                   UV_CACHE_DIR=str(self.root / "cache"), UV_PYTHON=sys._base_executable,
                   UV_PYTHON_DOWNLOADS="never", UV_OFFLINE="1")
        self.enterContext(patch.dict(os.environ, env))
        self.variant = self.enterContext(patch.object(launcher, "dependency_variant", return_value="cpu"))
        source = Path(launcher.__file__).parent
        shutil.copyfile(source / "_setup.cmd", self.app / "_setup.cmd")
        shutil.copyfile(shutil.which("uv"), self.app / "uv.exe")
        configs = self.app / "configs"
        configs.mkdir()
        project = '[project]\nname="fixture"\nversion="0.1.0"\nrequires-python=">=3.11"\ndependencies=[]\n'
        (self.root / "pyproject.toml").write_text(project)
        subprocess.run([self.app / "uv.exe", "lock", "--offline"], cwd=self.root, capture_output=True, check=True)
        for variant in ("cpu", "cuda"):
            (configs / f"pyproject-{variant}.toml").write_text(project)
            shutil.copyfile(self.root / "uv.lock", configs / f"uv-{variant}.lock")
        self.results = []

        def run_hidden(cmd, cwd, env, creationflags):
            result = subprocess.run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=45)
            self.results.append(result)
            return result.returncode

        self.console = self.enterContext(patch.object(launcher.subprocess, "call", side_effect=run_hidden))

    def test_first_install_failure_retry_then_reuse_from_another_build(self):
        import launcher
        setup = self.app / "_setup.cmd"
        valid = setup.read_bytes()
        setup.write_text("@exit /b 1\n")
        with self.assertRaises(OSError):
            launcher.ensure_runtime(self.app)
        self.assertFalse(launcher.is_ready(launcher.runtime_for(self.app, "cpu")))
        setup.write_bytes(valid)
        runtime = launcher.ensure_runtime(self.app)
        self.assertTrue(launcher.is_ready(runtime))
        self.assertEqual(len(self.results), 2)
        self.assertTrue((self.profile / ".mosheng/settings.json").is_file())
        build2 = self.root / "Build two"
        shutil.copytree(self.app, build2)
        (build2 / "app_version.py").write_text('APP_VERSION="2.0"')
        (build2 / "main.py").write_text("print('updated')")
        with patch.object(launcher.subprocess, "run", side_effect=AssertionError("unexpected sync")):
            self.assertEqual(launcher.ensure_runtime(build2), runtime)
        self.assertEqual(len(self.results), 2)
        self.assertFalse((build2 / ".venv").exists())
        with patch.object(launcher.subprocess, "Popen") as start:
            launcher.launch_app(build2, runtime)
        self.assertEqual(start.call_args.args[0], [str(runtime / ".venv/Scripts/pythonw.exe"), str(build2 / "main.py")])
        self.assertEqual(start.call_args.kwargs["cwd"], build2)

    def test_existing_user_offline_migration_and_dependency_change(self):
        import launcher
        settings = self.profile / ".mosheng/settings.json"
        settings.parent.mkdir()
        settings.write_text('{"asr":{"model_name":"existing"}}')
        old = launcher.ensure_runtime(self.app)
        lock = self.app / "configs/uv-cpu.lock"
        contents = lock.read_bytes().replace(b"\r\n", b"\n")
        lock.write_bytes(contents.replace(b"\n", b"\r\n"))
        self.assertEqual(launcher.runtime_for(self.app, "cpu"), old)
        lock.write_bytes(contents + b"\n# updated fixture lock\n")
        updated = launcher.ensure_runtime(self.app)
        self.assertNotEqual(updated, old)
        self.assertTrue(launcher.is_ready(old))
        self.assertTrue(launcher.is_ready(updated))
        self.assertEqual(json.loads(settings.read_text())["asr"]["model_name"], "existing")
        self.assertNotEqual(launcher.runtime_for(self.app, "cuda"), updated)
        (updated / ".venv/Scripts/pythonw.exe").unlink()
        self.assertFalse(launcher.is_ready(updated))
        self.assertEqual(launcher.ensure_runtime(self.app), updated)
        self.assertTrue(launcher.is_ready(updated))
        self.console.assert_not_called()

    def test_two_launchers_prepare_the_environment_once(self):
        import launcher
        settings = self.profile / ".mosheng/settings.json"
        settings.parent.mkdir()
        settings.write_text("{}")
        # Run the real installer in two separate Windows processes. Record each uv sync.
        script = """
import os, sys, time
from pathlib import Path
from unittest.mock import patch
import launcher
app = Path(sys.argv[1])
run = launcher.subprocess.run
def observe(cmd, **kwargs):
    if cmd[1] == 'sync':
        (app / (str(os.getpid()) + '.sync')).touch()
        time.sleep(0.3)
    return run(cmd, **kwargs)
with patch.object(launcher, 'dependency_variant', return_value='cpu'), patch.object(launcher.subprocess, 'run', observe):
    print(launcher.ensure_runtime(app))
"""
        children = [subprocess.Popen([sys.executable, "-c", script, str(self.app)],
                                     cwd=Path(launcher.__file__).parent, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE) for _ in range(2)]
        for child in children:
            _, stderr = child.communicate(timeout=30)
            self.assertEqual(child.returncode, 0, stderr)
        self.assertEqual(len(list(self.app.glob("*.sync"))), 1)


@unittest.skipUnless(sys.platform == "win32", "Windows input method")
class InputModeTests(unittest.TestCase):
    def test_caret_uses_accessibility_for_missing_or_offscreen_native_point(self):
        from unittest.mock import Mock
        from core import windows_input_mode as ime

        info = SimpleNamespace(hwndFocus=10, hwndActive=11, flags=0)
        self.enterContext(patch.object(ime.win32gui, "GetWindowRect", return_value=(-300, 50, 0, 500)))
        foreground = self.enterContext(patch.object(ime.win32gui, "GetForegroundWindow", return_value=11))
        self.enterContext(patch.object(ime.win32api, "MonitorFromPoint", return_value=3))
        self.enterContext(patch.object(ime.win32api, "GetMonitorInfo", return_value={
            "Monitor": (-800, 0, 0, 600), "Device": "display2"}))
        native = self.enterContext(patch.object(ime, "_caret_point", return_value=(-280, 90, 18)))
        automation = Mock()
        self.assertEqual(ime.badge_anchor(info, automation), ime.BadgeAnchor((-800, 0), (520, 90), 18))
        automation.point.assert_not_called()
        automation.point.return_value = (-100, 150, 22)
        for unavailable in (None, (0, 0)):
            native.return_value = unavailable
            self.assertEqual(ime.badge_anchor(info, automation), ime.BadgeAnchor((-800, 0), (700, 150), 22))
        foreground.return_value = 12
        self.assertIsNone(ime.badge_anchor(info, automation))
        foreground.return_value = 11
        automation.point.return_value = None
        self.assertIsNone(ime.badge_anchor(info, automation))

    def test_keyboard_layout_and_chinese_ime_submodes(self):
        from core import windows_input_mode as ime
        self.enterContext(patch.object(ime.win32process, "GetWindowThreadProcessId", return_value=(1, 1)))
        layout = self.enterContext(patch.object(ime.win32api, "GetKeyboardLayout"))
        window = self.enterContext(patch.object(ime.imm32, "ImmGetDefaultIMEWnd", return_value=10))
        query = self.enterContext(patch.object(ime, "_ime_value"))
        for hkl, values, expected in (
            (0x0409, [], "EN"), (0x0809, [], "EN"), (0x0411, [], None),
            (0x0804, [1, 1025], "中"), (0x0804, [1, 1024], "EN"),
            (0x0404, [0], "EN"), (0x0804, [None], None), (0x0804, [1, None], None),
        ):
            with self.subTest(layout=hkl, values=values):
                layout.return_value = hkl
                query.side_effect = values
                self.assertEqual(ime.window_mode(1), expected)
        window.return_value = 0
        self.assertIsNone(ime.window_mode(1))

    def test_native_ime_message_accepts_zero_and_rejects_missing_window(self):
        from core import windows_input_mode as ime
        import win32gui
        wc = win32gui.WNDCLASS()
        wc.lpszClassName = "MoShengInputModeTest"
        wc.hInstance = ime.win32api.GetModuleHandle(None)

        def proc(hwnd, msg, command, data):
            if msg == ime.WM_IME_CONTROL:
                return 1025 if command == ime.IMC_GETCONVERSIONMODE else 0
            return win32gui.DefWindowProc(hwnd, msg, command, data)

        wc.lpfnWndProc = proc
        atom = win32gui.RegisterClass(wc)
        self.addCleanup(win32gui.UnregisterClass, wc.lpszClassName, wc.hInstance)
        hwnd = win32gui.CreateWindow(atom, "", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
        try:
            self.assertEqual(ime._ime_value(hwnd, ime.IMC_GETOPENSTATUS), 0)
            self.assertEqual(ime._ime_value(hwnd, ime.IMC_GETCONVERSIONMODE), 1025)
        finally:
            win32gui.DestroyWindow(hwnd)
        self.assertIsNone(ime._ime_value(hwnd, ime.IMC_GETOPENSTATUS))
