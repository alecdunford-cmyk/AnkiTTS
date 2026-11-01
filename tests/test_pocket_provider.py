from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

from providers import pocket
from providers.base import ProviderError
from providers.pocket import PocketProvider, engine_package_version
from settings import SpeechProfile


TESTS_DIR = Path(__file__).resolve().parent
FAKE_WORKER = TESTS_DIR / "fake_pocket_worker.py"
REAL_WORKER = pocket.WORKER_SCRIPT

PROFILE = SpeechProfile("fr", "fr-FR-DeniseNeural", "+0%", "+0%", "+0Hz")


def make_clip(directory, name="clip.wav", content=b"RIFF-fake-clip"):
    path = Path(directory) / name
    path.write_bytes(content)
    return path


def make_provider(directory, **overrides):
    clip = make_clip(directory)
    config = {
        "engine_python": sys.executable,
        "models": {"fr": "french", "en": "english"},
        "reference_clips": {"fr": str(clip)},
        "start_timeout_seconds": 20,
        "request_timeout_seconds": 5,
        "idle_shutdown_seconds": 0,
        "worker_script": str(FAKE_WORKER),
    }
    config.update(overrides)
    return PocketProvider(config)


def check_capabilities_and_health():
    with TemporaryDirectory() as directory:
        provider = make_provider(directory)
        capabilities = provider.capabilities()

        assert capabilities.languages == frozenset({"fr"})
        assert not capabilities.native_rate
        assert not capabilities.volume and not capabilities.pitch
        assert capabilities.max_parallel == 1
        assert provider.health("fr").ok

        missing_engine = make_provider(
            directory, engine_python=str(Path(directory) / "none" / "python.exe")
        )
        assert not missing_engine.health("fr").ok
        assert "engine Python not found" in missing_engine.health("fr").detail

        missing_clip = make_provider(
            directory, reference_clips={"fr": str(Path(directory) / "gone.wav")}
        )
        assert not missing_clip.health("fr").ok
        assert "reference clip" in missing_clip.health("fr").detail
        assert not provider.health("ja").ok


def check_identity_hashes_clip_and_reads_version():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        site_packages = root / "venv" / "Lib" / "site-packages"
        (site_packages / "pocket_tts-4.0.1.dist-info").mkdir(parents=True)
        engine_python = root / "venv" / "Scripts" / "python.exe"

        assert engine_package_version(engine_python) == "4.0.1"
        assert engine_package_version(root / "elsewhere" / "python.exe") == "unknown"

        provider = make_provider(directory, engine_python=str(engine_python))
        identity = provider.identity("fr")
        clip = Path(directory) / "clip.wav"

        assert identity == {
            "provider": "pocket-tts",
            "provider_model": "pocket-tts/french",
            "provider_version": "4.0.1",
            "reference_sha256": hashlib.sha256(clip.read_bytes()).hexdigest(),
        }

        assert provider.cache_fields("fr", PROFILE) == {
            "voice": None,
            "rate": "+0%",
            "volume": None,
            "pitch": None,
        }

        time.sleep(0.02)
        clip.write_bytes(b"RIFF-re-recorded")
        assert provider.identity("fr")["reference_sha256"] != identity["reference_sha256"]


def check_worker_is_reused_and_writes_mp3():
    if shutil.which("ffmpeg") is None:
        print("(ffmpeg not on PATH; skipped)", end=" ")
        return

    with TemporaryDirectory() as directory:
        provider = make_provider(directory)

        try:
            first = Path(directory) / "one.mp3"
            second = Path(directory) / "two.mp3"
            provider.synthesize("bonjour", "fr", PROFILE, first)
            pid = provider._worker.process.pid
            provider.synthesize("salut", "fr", PROFILE, second)

            assert provider._worker.process.pid == pid
            assert first.stat().st_size > 0 and second.stat().st_size > 0
            assert provider.last_timing["audio_seconds"] == 0.5
            assert not list(Path(directory).glob(".*.pocket.wav"))

        finally:
            provider.close()

        assert provider._worker is None


def check_error_response_keeps_worker():
    with TemporaryDirectory() as directory:
        provider = make_provider(directory)

        try:
            try:
                provider.synthesize("FAIL", "fr", PROFILE, Path(directory) / "x.mp3")
            except ProviderError as error:
                assert "fake failure" in str(error)
            else:
                raise AssertionError("A worker error was hidden.")

            assert provider._worker.running
            assert provider.health("fr").ok
            assert not (Path(directory) / "x.mp3").exists()

        finally:
            provider.close()


def check_timeout_kills_worker_and_cools_down():
    with TemporaryDirectory() as directory:
        provider = make_provider(directory, request_timeout_seconds=1)

        try:
            started = time.monotonic()

            try:
                provider.synthesize("HANG", "fr", PROFILE, Path(directory) / "x.mp3")
            except ProviderError as error:
                assert "did not answer" in str(error)
            else:
                raise AssertionError("A hung worker was not detected.")

            assert time.monotonic() - started < 10
            assert not provider._worker.running
            health = provider.health("fr")
            assert not health.ok and "recent failure" in health.detail

        finally:
            provider.close()


def check_worker_exit_is_reported():
    with TemporaryDirectory() as directory:
        provider = make_provider(directory)

        try:
            try:
                provider.synthesize("EXIT", "fr", PROFILE, Path(directory) / "x.mp3")
            except ProviderError as error:
                assert "exited" in str(error)
            else:
                raise AssertionError("A dead worker was not detected.")

            assert not provider.health("fr").ok

        finally:
            provider.close()


def check_start_failure_cools_down():
    with TemporaryDirectory() as directory:
        broken_script = Path(directory) / "broken.py"
        broken_script.write_text("import sys; sys.exit(2)\n", encoding="utf-8")
        provider = make_provider(directory, worker_script=str(broken_script))

        try:
            provider.synthesize("bonjour", "fr", PROFILE, Path(directory) / "x.mp3")
        except ProviderError as error:
            assert "could not start" in str(error)
        else:
            raise AssertionError("A broken worker started.")

        assert not provider.health("fr").ok


def check_idle_shutdown():
    if shutil.which("ffmpeg") is None:
        print("(ffmpeg not on PATH; skipped)", end=" ")
        return

    with TemporaryDirectory() as directory:
        provider = make_provider(directory, idle_shutdown_seconds=0.5)

        try:
            provider.synthesize("bonjour", "fr", PROFILE, Path(directory) / "a.mp3")
            process = provider._worker.process
            deadline = time.monotonic() + 10

            while provider._worker is not None and time.monotonic() < deadline:
                time.sleep(0.1)

            assert provider._worker is None
            assert process.poll() is not None

        finally:
            provider.close()


def talk_to_real_worker(lines):
    """Drive the real worker script without torch: protocol paths only."""

    completed = subprocess.run(
        [sys.executable, "-I", "-u", str(REAL_WORKER)],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def check_real_worker_protocol_errors():
    responses = talk_to_real_worker(
        [
            "this is not json",
            json.dumps({"id": 7, "op": "dance"}),
            json.dumps({"id": 8, "op": "hello", "protocol": 99}),
            json.dumps({"id": 9, "op": "shutdown"}),
            json.dumps({"id": 10, "op": "hello", "protocol": 1}),
        ]
    )

    assert [response["id"] for response in responses] == [None, 7, 8, 9]
    assert responses[0]["ok"] is False and "JSONDecodeError" in responses[0]["error"]
    assert "unknown op" in responses[1]["error"]
    assert "protocol 99" in responses[2]["error"]
    assert responses[3] == {"id": 9, "ok": True}


def run():
    checks = [
        check_capabilities_and_health,
        check_identity_hashes_clip_and_reads_version,
        check_worker_is_reused_and_writes_mp3,
        check_error_response_keeps_worker,
        check_timeout_kills_worker_and_cools_down,
        check_worker_exit_is_reported,
        check_start_failure_cools_down,
        check_idle_shutdown,
        check_real_worker_protocol_errors,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
