"""HuggingFace model download with progress tracking for MoSheng."""

import logging
import re
from pathlib import Path

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


_CONFIG_FILES = ("config.json", "preprocessor_config.json", "tokenizer_config.json",
                 "chat_template.json", "vocab.json", "merges.txt")
_INDEX = "model.safetensors.index.json"
_GENERATION_CONFIG = "generation_config.json"


def _invalid_files(snapshot: Path) -> set[str]:
    """Validate the two supported Qwen layouts without reading tensor payloads."""
    import json
    from safetensors import SafetensorError, safe_open

    invalid = set()
    config_files = list(_CONFIG_FILES)
    if (snapshot / _GENERATION_CONFIG).exists():
        config_files.append(_GENERATION_CONFIG)
    for name in config_files:
        try:
            path = snapshot / name
            if name.endswith(".json"):
                data = json.loads(path.read_bytes())
                if not isinstance(data, dict) or not data:
                    invalid.add(name)
            elif not path.stat().st_size:
                invalid.add(name)
        except (OSError, ValueError):
            invalid.add(name)

    weights = {"model.safetensors": set()}
    if (snapshot / _INDEX).exists():
        try:
            mapping = json.loads((snapshot / _INDEX).read_bytes())["weight_map"]
            if not isinstance(mapping, dict) or not mapping:
                raise ValueError("Empty weight map")
            weights = {}
            for key, name in mapping.items():
                if Path(name).name != name or not name.endswith(".safetensors"):
                    raise ValueError("Invalid shard name")
                weights.setdefault(name, set()).add(key)
        except (KeyError, TypeError, ValueError, OSError):
            return invalid | {_INDEX}

    for name, expected in weights.items():
        try:
            with safe_open(str(snapshot / name), framework="numpy") as tensors:
                keys = set(tensors.keys())
                if not keys or not expected.issubset(keys):
                    invalid.add(name)
        except (SafetensorError, OSError):
            invalid.add(name)
    return invalid


def cached_snapshot(model_id: str) -> Path | None:
    """Resolve the selected main revision strictly from the local Hub cache."""
    from huggingface_hub import constants

    repo = Path(constants.HF_HUB_CACHE) / ("models--" + model_id.replace("/", "--"))
    try:
        revision = (repo / "refs" / "main").read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        return None
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        return None
    snapshot = repo / "snapshots" / revision
    return snapshot if snapshot.is_dir() and not _invalid_files(snapshot) else None


def is_model_cached(model_id: str) -> bool:
    return cached_snapshot(model_id) is not None


class ModelDownloadThread(QThread):
    """Download a HuggingFace model in a background thread with progress signals."""

    progress = Signal(int)    # 0-100 percentage
    finished_ok = Signal()    # download succeeded
    error = Signal(str)       # download failed, carries error message

    def __init__(self, model_id: str, parent=None):
        super().__init__(parent)
        self._model_id = model_id
        self.snapshot: Path | None = None
        self.failure = ""

    def run(self):
        try:
            from huggingface_hub import model_info, hf_hub_download

            logger.info("Downloading model: %s", self._model_id)

            # Resolving one file by branch also updates refs/main. Pin every
            # subsequent request to that same commit, including any repair.
            config = Path(hf_hub_download(self._model_id, "config.json"))
            snapshot = config.parent
            info = model_info(self._model_id, revision=snapshot.name, files_metadata=True)
            files = [f for f in info.siblings if f.rfilename in (*_CONFIG_FILES, _INDEX, _GENERATION_CONFIG)
                     or f.rfilename.endswith(".safetensors")]
            total = sum(f.size or 0 for f in files)
            done = 0
            for i, file in enumerate(files, 1):
                name = file.rfilename
                path = snapshot / name
                repair = path.is_file() and file.size is not None and path.stat().st_size != file.size
                hf_hub_download(self._model_id, name, revision=snapshot.name, force_download=repair)
                done += file.size or 0
                self.progress.emit(min(99, int(100 * (done / total if total else i / len(files)))))

            invalid = _invalid_files(snapshot)
            if invalid:
                available = {f.rfilename for f in files}
                if invalid - available and _INDEX in available:
                    # A damaged index can reference a shard absent from this revision.
                    invalid.add(_INDEX)
                for name in sorted(invalid & available):
                    hf_hub_download(self._model_id, name, revision=snapshot.name, force_download=True)
                invalid = _invalid_files(snapshot)
            if invalid:
                raise ValueError("Incomplete model snapshot: " + ", ".join(sorted(invalid)))
            self.snapshot = snapshot
            self.progress.emit(100)
            logger.info("Model download completed: %s", self._model_id)
            self.finished_ok.emit()
        except Exception as e:
            logger.exception("Model download failed: %s", self._model_id)
            self.failure = str(e)
            self.error.emit(self.failure)
