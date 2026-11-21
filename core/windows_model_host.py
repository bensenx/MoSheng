"""Windows GPU inference lives in one disposable process per dictation session."""

import logging
import multiprocessing
import threading
import time
import weakref
from uuid import uuid4

from core.asr_base import ASRBase

logger = logging.getLogger(__name__)


def _serve(pipe, config):
    from utils.logger import setup_logging
    setup_logging()
    try:
        started = time.perf_counter()
        import torch
        from core.asr_qwen import QwenASREngine
        if config is None:
            # Import CPU-side code while paused. Even CUDA device discovery must
            # wait for the user's load request.
            import qwen_asr
            if torch.cuda.is_initialized():
                logger.warning("Standby imports initialized CUDA; discarding process")
                return
            if not pipe.poll():
                # Return idle working-set pages to Windows while a game is running.
                import ctypes
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.K32EmptyWorkingSet(ctypes.c_void_p(-1))
            logger.info("[dictation] standby imports ready in %.3f s", time.perf_counter() - started)
            op, config = pipe.recv()
            if op == "close":
                return
            if op != "load":
                raise ValueError(f"Unexpected standby request: {op}")
        if config["device"] in ("auto", "cuda:0"):
            config["device"] = "cuda:0" if torch.cuda.is_available() else "cpu"
        asr = QwenASREngine(**config)
        speaker = None
        leases = set()
        asr.load_model()
        pipe.send((True, None))
        while True:
            op, args = pipe.recv()
            if op == "close":
                break
            try:
                if op == "warmup":
                    result = asr.warmup()
                elif op == "transcribe":
                    result = asr.transcribe(*args)
                elif op == "speaker_load":
                    if speaker is None:
                        from core.speaker_verifier import SpeakerVerifier
                        candidate = SpeakerVerifier(device=config["device"])
                        candidate.load_model()
                        speaker = candidate
                        del candidate
                    leases.add(args[0])
                    result = None
                elif op == "speaker_release":
                    leases.discard(args[0])
                    if not leases and speaker is not None:
                        speaker.unload_model()
                        speaker = None
                    result = None
                elif op == "embedding":
                    result = speaker.extract_embedding(*args)
                else:
                    raise ValueError(f"Unknown inference request: {op}")
                pipe.send((True, result))
            except Exception as exc:
                logger.exception("GPU inference request failed: %s", op)
                pipe.send((False, str(exc)))
    except (EOFError, BrokenPipeError):
        pass  # The desktop process exited.
    except Exception as exc:
        logger.exception("GPU inference host failed")
        try:
            pipe.send((False, str(exc)))
        except OSError:
            pass
    finally:
        pipe.close()


def _spawn(config):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(target=_serve, args=(child, config), name="MoSheng-Inference", daemon=True)
    try:
        process.start()
    except BaseException:
        parent.close()
        raise
    finally:
        child.close()
    return process, parent


class WindowsModelStandby:
    """One disposable, weight-free interpreter, transferred to the next session."""

    def __init__(self):
        self._pending = None

    def prepare(self):
        if self._pending is None:
            self._pending = _spawn(None)

    def take(self):
        pending, self._pending = self._pending, None
        return pending

    def close(self):
        pending = self.take()
        if pending:
            process, pipe = pending
            pipe.close()
            if process.is_alive():
                process.terminate()
            process.join()
            process.close()


class WindowsModelHost(ASRBase):
    def __init__(self, **config):
        self._config = config
        self._process = None
        self._pipe = None
        self._lock = threading.RLock()

    @staticmethod
    def get_name():
        return "Qwen3-ASR"

    @property
    def is_ready(self):
        return self._process is not None and self._process.is_alive()

    def _receive(self):
        ok, value = self._pipe.recv()
        if not ok:
            raise RuntimeError(value)
        return value

    def load_model(self, standby=None):
        pending = standby.take() if standby is not None else None
        if pending:
            self._process, self._pipe = pending
            try:
                self._pipe.send(("load", self._config))
                self._receive()
            except (EOFError, OSError):
                # Windows may have reclaimed the waiting process. Cold start once.
                self.unload_model()
            except BaseException:
                self.unload_model()
                raise
            else:
                logger.info("[dictation] inference pid=%d (from standby)", self._process.pid)
                return
        self._process, self._pipe = _spawn(self._config)
        logger.info("[dictation] inference pid=%d", self._process.pid)
        try:
            self._receive()
        except BaseException:
            self.unload_model()
            raise

    def _call(self, op, *args):
        with self._lock:
            if not self.is_ready:
                raise RuntimeError("Inference process is unavailable")
            self._pipe.send((op, args))
            return self._receive()

    def warmup(self):
        self._call("warmup")

    def transcribe(self, audio, sample_rate=16000, context=""):
        return self._call("transcribe", audio, sample_rate, context)

    def speaker_verifier(self):
        from core.speaker_verifier import SpeakerVerifier
        # Enrollment and thresholds stay local; only embedding inference needs CUDA.
        host = self
        token = uuid4().hex
        host._call("speaker_load", token)

        class HostedVerifier(SpeakerVerifier):
            @property
            def is_ready(self):
                return host.is_ready

            def extract_embedding(self, audio, sample_rate=16000):
                return host._call("embedding", audio, sample_rate)

            def unload_model(self):
                cleanup()

        verifier = HostedVerifier()
        cleanup = weakref.finalize(verifier, self._drop_speaker, token)
        return verifier

    def _drop_speaker(self, token):
        # The last in-flight recording may release its reference on the UI thread.
        def drop():
            with self._lock:
                if self.is_ready:
                    try:
                        self._call("speaker_release", token)
                    except (OSError, EOFError, RuntimeError):
                        logger.debug("Speaker host already closed", exc_info=True)
        threading.Thread(target=drop, name="ReleaseSpeaker", daemon=True).start()

    def unload_model(self):
        with self._lock:
            process = self._process
            if process is None:
                return
            try:
                if process.is_alive():
                    self._pipe.send(("close", ()))
            except (OSError, EOFError):
                pass
            self._pipe.close()
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join()
            self._process = self._pipe = None
            process.close()
