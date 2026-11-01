from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from ankitts_log import get_logger, text_preview
from providers.audio import encode_mp3, tempo_from_rate
from providers.base import (
    Capabilities,
    HealthStatus,
    Provider,
    ProviderError,
    ProviderUnavailable,
)
from providers.secrets import read_user_environment
from speech_text import SPEECH_TEXT_VERSION


POCKET_PROVIDER_ID = "pocket-tts"
WORKER_SCRIPT = Path(__file__).resolve().parent / "pocket_worker.py"
WORKER_PROTOCOL = 1
FAILURE_COOLDOWN_SECONDS = 60
SHUTDOWN_GRACE_SECONDS = 5

logger = get_logger(
    "providers.pocket"
)

_hash_lock = threading.Lock()
_hash_cache = {}


def file_sha256(
    path,
):
    """SHA-256 of a file, cached per (path, size, mtime)."""

    path = Path(
        path
    )

    stat = path.stat()

    key = (
        str(
            path.resolve()
        ),
        stat.st_size,
        stat.st_mtime_ns,
    )

    with _hash_lock:
        cached = _hash_cache.get(
            key
        )

    if cached is not None:
        return cached

    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as file:
        for block in iter(
            lambda: file.read(
                1 << 20
            ),
            b"",
        ):
            digest.update(
                block
            )

    value = digest.hexdigest()

    with _hash_lock:
        _hash_cache[
            key
        ] = value

    return value


def engine_package_version(
    engine_python,
    package="pocket_tts",
):
    """Read an installed package version from the engine venv's dist-info."""

    venv_root = Path(
        engine_python
    ).resolve().parent.parent

    for dist_info in sorted(
        (
            venv_root
            / "Lib"
            / "site-packages"
        ).glob(
            f"{package}-*.dist-info"
        )
    ):
        return dist_info.name[
            len(package) + 1 : -len(".dist-info")
        ]

    return "unknown"


class PocketWorker:
    """One engine process spoken to over stdin/stdout JSON lines."""

    def __init__(
        self,
        engine_python,
        start_timeout,
        request_timeout,
        script=WORKER_SCRIPT,
    ):
        self.engine_python = str(
            engine_python
        )
        self.script = str(
            script
        )
        self.start_timeout = start_timeout
        self.request_timeout = request_timeout
        self.process = None
        self.responses = queue.Queue()
        self.next_id = 0
        self.hello = None

    @property
    def running(self):
        return (
            self.process is not None
            and self.process.poll() is None
        )

    def start(self):
        environment = dict(
            os.environ
        )

        environment[
            "PYTHONIOENCODING"
        ] = "utf-8"

        environment[
            "PYTHONUNBUFFERED"
        ] = "1"

        token = read_user_environment(
            "HF_TOKEN"
        )

        if token:
            environment[
                "HF_TOKEN"
            ] = token

        creation_flags = getattr(
            subprocess,
            "CREATE_NO_WINDOW",
            0,
        )

        started = time.perf_counter()

        self.process = subprocess.Popen(
            [
                self.engine_python,
                "-I",
                "-u",
                self.script,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            creationflags=creation_flags,
        )

        self.responses = queue.Queue()

        threading.Thread(
            target=self._read_stdout,
            args=(
                self.process,
                self.responses,
            ),
            name="ankitts-pocket-stdout",
            daemon=True,
        ).start()

        threading.Thread(
            target=self._drain_stderr,
            args=(
                self.process,
            ),
            name="ankitts-pocket-stderr",
            daemon=True,
        ).start()

        self.hello = self.request(
            {
                "op": "hello",
                "protocol": WORKER_PROTOCOL,
            },
            self.start_timeout,
        )

        logger.info(
            "Pocket worker started in %.1f s (pid %s): pocket-tts %s, "
            "torch %s, Python %s",
            time.perf_counter()
            - started,
            self.process.pid,
            self.hello.get(
                "pocket_tts_version"
            ),
            self.hello.get(
                "torch_version"
            ),
            self.hello.get(
                "python"
            ),
        )

    @staticmethod
    def _read_stdout(
        process,
        responses,
    ):
        for raw_line in process.stdout:
            line = raw_line.decode(
                "utf-8",
                errors="replace",
            ).strip()

            if not line:
                continue

            try:
                responses.put(
                    json.loads(
                        line
                    )
                )

            except json.JSONDecodeError:
                logger.warning(
                    "Pocket worker wrote a non-protocol line: %s",
                    text_preview(
                        line
                    ),
                )

        responses.put(
            None
        )

    @staticmethod
    def _drain_stderr(
        process,
    ):
        for raw_line in process.stderr:
            line = raw_line.decode(
                "utf-8",
                errors="replace",
            ).rstrip()

            if line:
                logger.info(
                    "worker: %s",
                    line,
                )

    def request(
        self,
        payload,
        timeout,
    ):
        if not self.running:
            raise ProviderUnavailable(
                "The Pocket worker is not running."
            )

        self.next_id += 1
        request_id = self.next_id

        message = dict(
            payload,
            id=request_id,
        )

        try:
            self.process.stdin.write(
                (
                    json.dumps(
                        message,
                        ensure_ascii=False,
                    )
                    + "\n"
                ).encode(
                    "utf-8"
                )
            )

            self.process.stdin.flush()

        except OSError as error:
            self.kill()

            raise ProviderUnavailable(
                f"The Pocket worker stopped accepting requests: {error}"
            ) from error

        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()

            if remaining <= 0:
                self.kill()

                raise ProviderError(
                    f'The Pocket worker did not answer "{payload["op"]}" '
                    f"within {timeout} s; it was stopped."
                )

            try:
                response = self.responses.get(
                    timeout=remaining
                )

            except queue.Empty:
                continue

            if response is None:
                self.kill()

                raise ProviderUnavailable(
                    "The Pocket worker exited "
                    f"(code {self.process.poll() if self.process else None})."
                )

            if response.get(
                "id"
            ) != request_id:
                logger.warning(
                    "Ignoring an unexpected Pocket response id %r.",
                    response.get(
                        "id"
                    ),
                )

                continue

            if not response.get(
                "ok"
            ):
                raise ProviderError(
                    response.get(
                        "error",
                        "unknown worker error",
                    )
                )

            return response

    def close(self):
        if self.process is None:
            return

        if self.running:
            try:
                self.request(
                    {
                        "op": "shutdown",
                    },
                    SHUTDOWN_GRACE_SECONDS,
                )

                self.process.wait(
                    SHUTDOWN_GRACE_SECONDS
                )

            except Exception:
                pass

        self.kill()

    def kill(self):
        process = self.process

        if process is None:
            return

        if process.poll() is None:
            process.kill()

            try:
                process.wait(
                    SHUTDOWN_GRACE_SECONDS
                )

            except subprocess.TimeoutExpired:
                pass

        self.process = None


class PocketProvider(Provider):
    """Kyutai Pocket TTS, cloned from reference clips, in a worker process."""

    provider_id = "pocket"

    def __init__(
        self,
        config=None,
    ):
        super().__init__(
            config
        )

        self.engine_python = Path(
            str(
                self.config.get(
                    "engine_python",
                    "",
                )
            )
        )
        self.models = dict(
            self.config.get(
                "models",
                {},
            )
        )
        self.reference_clips = {
            language: str(
                path
            )
            for language, path in self.config.get(
                "reference_clips",
                {},
            ).items()
            if path
        }
        self.start_timeout = float(
            self.config.get(
                "start_timeout_seconds",
                180,
            )
        )
        self.request_timeout = float(
            self.config.get(
                "request_timeout_seconds",
                300,
            )
        )
        self.idle_shutdown = float(
            self.config.get(
                "idle_shutdown_seconds",
                300,
            )
        )
        self.worker_script = Path(
            self.config.get(
                "worker_script",
                WORKER_SCRIPT,
            )
        )

        self._lock = threading.Lock()
        self._worker = None
        self._idle_timer = None
        self._down_until = 0.0
        self._down_reason = ""
        self._warned_ignored = False
        self.last_timing = None

    def capabilities(self):
        return Capabilities(
            languages=frozenset(
                language
                for language in self.models
                if language in self.reference_clips
            ),
            native_rate=False,
            volume=False,
            pitch=False,
            local=True,
            max_parallel=1,
        )

    def uses_own_voice(self):
        return True

    def identity(
        self,
        language,
    ):
        model = self.models.get(
            language
        )

        clip = self.reference_clips.get(
            language
        )

        if not model or not clip:
            raise ProviderUnavailable(
                f"Pocket has no model and clip for {language}."
            )

        clip_path = Path(
            clip
        )

        if not clip_path.is_file():
            raise ProviderUnavailable(
                f"Pocket reference clip is missing: {clip_path}"
            )

        return {
            "provider": POCKET_PROVIDER_ID,
            "provider_model": f"pocket-tts/{model}",
            "provider_version": engine_package_version(
                self.engine_python
            ),
            "reference_sha256": file_sha256(
                clip_path
            ),
            "speech_text_version": SPEECH_TEXT_VERSION,
        }

    def voices(
        self,
        language,
    ):
        clip = self.reference_clips.get(
            language
        )

        return [
            f"clone:{Path(clip).name}"
        ] if clip else []

    def health(
        self,
        language=None,
    ):
        if time.monotonic() < self._down_until:
            return HealthStatus(
                False,
                f"recent failure ({self._down_reason}); retry in "
                f"{self._down_until - time.monotonic():.0f} s",
            )

        if not self.engine_python.is_file():
            return HealthStatus(
                False,
                f"engine Python not found: {self.engine_python}",
            )

        if not self.worker_script.is_file():
            return HealthStatus(
                False,
                f"worker script not found: {self.worker_script}",
            )

        languages = (
            [language]
            if language is not None
            else list(
                self.models
            )
        )

        for current in languages:
            if not self.models.get(
                current
            ):
                return HealthStatus(
                    False,
                    f"no Pocket model configured for {current}",
                )

            clip = self.reference_clips.get(
                current
            )

            if not clip or not Path(
                clip
            ).is_file():
                return HealthStatus(
                    False,
                    f"reference clip for {current} not found: {clip}",
                )

        return HealthStatus(
            True,
            "configured",
        )

    def _mark_down(
        self,
        reason,
    ):
        self._down_until = (
            time.monotonic()
            + FAILURE_COOLDOWN_SECONDS
        )
        self._down_reason = reason

    def _ensure_worker(self):
        if (
            self._worker is not None
            and self._worker.running
        ):
            return self._worker

        worker = PocketWorker(
            self.engine_python,
            self.start_timeout,
            self.request_timeout,
            self.worker_script,
        )

        try:
            worker.start()

        except Exception as error:
            worker.kill()
            self._mark_down(
                f"worker start failed: {error}"
            )

            raise ProviderUnavailable(
                f"The Pocket worker could not start: {error}"
            ) from error

        self._worker = worker

        return worker

    def _schedule_idle_shutdown(self):
        if self._idle_timer is not None:
            self._idle_timer.cancel()

        if self.idle_shutdown <= 0:
            return

        self._idle_timer = threading.Timer(
            self.idle_shutdown,
            self._idle_close,
        )

        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _idle_close(self):
        with self._lock:
            if self._worker is not None:
                logger.info(
                    "Stopping the idle Pocket worker."
                )

                self._worker.close()
                self._worker = None

    def synthesize(
        self,
        text,
        language,
        profile,
        output_path,
    ):
        identity = self.identity(
            language
        )

        if not self._warned_ignored and (
            profile.volume not in ("+0%", "")
            or profile.pitch not in ("+0Hz", "")
        ):
            logger.info(
                "Pocket ignores volume and pitch (profile %s has %s, %s).",
                language,
                profile.volume,
                profile.pitch,
            )

            self._warned_ignored = True

        tempo = tempo_from_rate(
            profile.rate
        )

        output_path = Path(
            output_path
        )

        wav_path = output_path.with_name(
            f".{output_path.name}.pocket.wav"
        )

        started = time.perf_counter()

        with self._lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()

            worker = self._ensure_worker()

            try:
                response = worker.request(
                    {
                        "op": "synthesize",
                        "model": self.models[
                            language
                        ],
                        "reference": self.reference_clips[
                            language
                        ],
                        "reference_sha256": identity[
                            "reference_sha256"
                        ],
                        "text": text,
                        "output": str(
                            wav_path
                        ),
                    },
                    self.request_timeout,
                )

            except ProviderError as error:
                # A dead or killed (timed-out) worker cools down; a
                # per-request error from a live worker does not.
                if not worker.running:
                    self._mark_down(
                        str(
                            error
                        )
                    )

                raise

            finally:
                self._schedule_idle_shutdown()

        try:
            encode_mp3(
                wav_path,
                output_path,
                tempo,
            )

        except Exception as error:
            raise ProviderError(
                f"Encoding Pocket audio failed: {error}"
            ) from error

        finally:
            if wav_path.exists():
                wav_path.unlink()

        wall = time.perf_counter() - started
        audio_seconds = float(
            response.get(
                "audio_seconds",
                0,
            )
        )

        self.last_timing = {
            "wall_seconds": round(
                wall,
                3,
            ),
            "audio_seconds": audio_seconds,
            "rtf": (
                round(
                    wall / audio_seconds,
                    3,
                )
                if audio_seconds
                else None
            ),
            "load_seconds": response.get(
                "load_seconds"
            ),
            "voice_seconds": response.get(
                "voice_seconds"
            ),
            "synth_seconds": response.get(
                "synth_seconds"
            ),
            "tempo": str(
                tempo
            ),
        }

        logger.info(
            "Pocket %s: %.2f s audio in %.2f s (RTF %s; load %s s, "
            "voice %s s)",
            language,
            audio_seconds,
            wall,
            self.last_timing[
                "rtf"
            ],
            response.get(
                "load_seconds"
            ),
            response.get(
                "voice_seconds"
            ),
        )

    def close(self):
        if self._idle_timer is not None:
            self._idle_timer.cancel()

        with self._lock:
            if self._worker is not None:
                self._worker.close()
                self._worker = None
