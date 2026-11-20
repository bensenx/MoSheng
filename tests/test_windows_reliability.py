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
    def test_failed_setup_then_success_and_second_launch(self):
        import launcher
        root = Path(self.enterContext(tempfile.TemporaryDirectory())) / "MoSheng portable"
        root.mkdir()
        profile = root / "profile"
        profile.mkdir()
        env = dict(USERPROFILE=str(profile), UV_CACHE_DIR=str(root / "cache"),
                   UV_PYTHON=sys._base_executable, UV_PYTHON_DOWNLOADS="never", UV_OFFLINE="1")
        self.enterContext(patch.dict(os.environ, env))
        source = Path(launcher.__file__).parent
        for name in ("app_version.py", "_setup.cmd"):
            shutil.copyfile(source / name, root / name)
        (root / "mirror.env").write_text("UV_OFFLINE=1\n")
        self.enterContext(patch.object(launcher, "get_app_dir", return_value=str(root)))
        launched = self.enterContext(patch.object(launcher, "launch_app"))
        alert = self.enterContext(patch.object(launcher, "fatal_msgbox"))
        results = []

        def run_hidden(cmd, cwd, creationflags):
            result = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=45)
            results.append(result)
            return result.returncode

        self.enterContext(patch.object(launcher.subprocess, "call", side_effect=run_hidden))
        launcher.main()
        self.assertNotEqual(results[0].returncode, 0)
        alert.assert_called_once()
        launched.assert_not_called()
        self.assertTrue(launcher.needs_setup(str(root)))

        shutil.copyfile(shutil.which("uv"), root / "uv.exe")
        configs = root / "configs"
        configs.mkdir()
        project = '[project]\nname="fixture"\nversion="0.1.0"\nrequires-python=">=3.11"\ndependencies=[]\n'
        (root / "pyproject.toml").write_text(project)
        subprocess.run([root / "uv.exe", "lock", "--offline"], cwd=root, capture_output=True, check=True)
        for target in ("cpu", "cuda"):
            (configs / f"pyproject-{target}.toml").write_text(project)
            shutil.copyfile(root / "uv.lock", configs / f"uv-{target}.lock")
        launcher.main()
        self.assertEqual(results[-1].returncode, 0, results[-1].stdout + results[-1].stderr)
        marker = root / ".venv" / ".mosheng_version"
        self.assertEqual(marker.read_text().strip(), launcher.CURRENT_VERSION)
        self.assertFalse(launcher.needs_setup(str(root)))
        launcher.main()
        self.assertEqual(len(results), 2)
        self.assertEqual(launched.call_count, 2)
        marker.write_bytes(b"\xff")
        self.assertTrue(launcher.needs_setup(str(root)))
