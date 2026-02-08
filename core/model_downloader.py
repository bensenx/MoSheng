"""HuggingFace model download with progress tracking for MoSheng."""

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


def is_model_cached(model_id: str) -> bool:
    """Check if a HuggingFace model is already downloaded in the local cache."""
    from huggingface_hub import constants

    repo_name = model_id.replace("/", "--")
    cache_path = Path(constants.HF_HUB_CACHE) / f"models--{repo_name}"
    # A fully downloaded model has both refs/ and snapshots/ subdirectories
    return (cache_path / "refs").is_dir() and (cache_path / "snapshots").is_dir()


class ModelDownloadThread(QThread):
    """Download a HuggingFace model in a background thread with progress signals."""

    progress = Signal(int)    # 0-100 percentage
    finished_ok = Signal()    # download succeeded
    error = Signal(str)       # download failed, carries error message

    def __init__(self, model_id: str, parent=None):
        super().__init__(parent)
        self._model_id = model_id

    def run(self):
        try:
            from huggingface_hub import model_info, hf_hub_download

            logger.info("Downloading model: %s", self._model_id)

            # Get file list with sizes for byte-level progress tracking
            info = model_info(self._model_id)
            files_with_size = [
                (s.rfilename, s.size or 0) for s in info.siblings
            ]
            total_size = sum(size for _, size in files_with_size)
            if total_size == 0:
                total_size = 1  # prevent division by zero

            # Download files one by one, tracking progress by bytes
            bytes_done = 0
            for filename, file_size in files_with_size:
                hf_hub_download(
                    repo_id=self._model_id,
                    filename=filename,
                )
                bytes_done += file_size
                pct = min(int(bytes_done * 100 / total_size), 100)
                self.progress.emit(pct)

            logger.info("Model download completed: %s", self._model_id)
            self.finished_ok.emit()
        except Exception as e:
            logger.exception("Model download failed: %s", self._model_id)
            self.error.emit(str(e))
