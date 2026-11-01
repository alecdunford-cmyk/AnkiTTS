"""
Pocket TTS worker for AnkiTTS (protocol 1; docs/DESIGN-providers.md, section 6).

Runs in the engine venv (Python 3.12, torch CPU, pocket-tts), never inside
Anki, and imports no AnkiTTS code. One JSON object per line in each
direction, strictly request -> response, with the request id echoed:

    {"id": 1, "op": "hello", "protocol": 1}
    {"id": 2, "op": "synthesize", "model": "french", "reference": "C:/clip.wav",
     "reference_sha256": "<hex>", "text": "...", "output": "C:/out.wav"}
    {"id": 3, "op": "shutdown"}

Success: {"id": n, "ok": true, ...}; failure: {"id": n, "ok": false,
"error": "<Type>: <message>"}. stdout carries only protocol lines;
everything else goes to stderr.
"""

import gc
import hashlib
import json
import os
import platform
import sys
import time
import traceback
import wave


PROTOCOL = 1
WORKER_VERSION = "1"


def _redirect_stdout_to_stderr():
    """Keep fd 1 for protocol lines; library prints (Python or C) go to stderr."""

    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    return os.fdopen(protocol_fd, "wb", buffering=0)


def _log(message):
    sys.stderr.write(f"pocket-worker: {message}\n")
    sys.stderr.flush()


def _sha256(path):
    digest = hashlib.sha256()

    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)

    return digest.hexdigest()


class Engine:
    def __init__(self):
        import torch

        threads = int(os.environ.get("ANKITTS_TORCH_THREADS", "4"))
        torch.set_num_threads(threads)

        self.torch = torch
        self.model_name = None
        self.model = None
        self.voice_states = {}
        self.reference_hashes = {}

    def _verified_reference(self, path, expected_sha256):
        stat = os.stat(path)
        key = (os.path.abspath(path), stat.st_size, stat.st_mtime_ns)

        if key not in self.reference_hashes:
            self.reference_hashes[key] = _sha256(path)

        actual = self.reference_hashes[key]

        if expected_sha256 and actual != expected_sha256:
            raise ValueError(
                "reference clip hash mismatch: expected "
                f"{expected_sha256[:12]}..., found {actual[:12]}..."
            )

        return actual

    def _load(self, model_name):
        if self.model_name == model_name:
            return 0.0

        from pocket_tts import TTSModel

        if self.model is not None:
            _log(f"unloading {self.model_name}")
            self.model = None
            self.model_name = None
            self.voice_states.clear()
            gc.collect()

        started = time.perf_counter()
        model = TTSModel.load_model(language=model_name)

        if not getattr(model, "has_voice_cloning", True):
            raise RuntimeError(f"model {model_name} has no voice cloning")

        self.model = model
        self.model_name = model_name
        elapsed = time.perf_counter() - started
        _log(f"loaded {model_name} in {elapsed:.1f} s")

        return elapsed

    def synthesize(self, request):
        model_name = request["model"]
        reference = request["reference"]
        text = request["text"]
        output = request["output"]

        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")

        reference_sha256 = self._verified_reference(
            reference, request.get("reference_sha256")
        )
        load_seconds = self._load(model_name)

        voice_seconds = 0.0
        state_key = (model_name, os.path.abspath(reference), reference_sha256)
        state = self.voice_states.get(state_key)

        if state is None:
            started = time.perf_counter()
            state = self.model.get_state_for_audio_prompt(reference)
            voice_seconds = time.perf_counter() - started
            self.voice_states[state_key] = state

        started = time.perf_counter()
        audio = self.model.generate_audio(state, text)
        synth_seconds = time.perf_counter() - started

        samples = audio.detach().cpu().float().numpy()

        if samples.ndim == 2:
            if samples.shape[0] <= 2 and samples.shape[1] > samples.shape[0]:
                samples = samples.T

            channels = samples.shape[1]
        else:
            channels = 1

        sample_rate = int(self.model.sample_rate)
        pcm = (samples.clip(-1.0, 1.0) * 32767.0).round().astype("<i2")
        frame_count = pcm.shape[0]

        if frame_count == 0:
            raise RuntimeError("the model produced no samples")

        temporary = f"{output}.partial"

        with wave.open(temporary, "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm.tobytes())

        os.replace(temporary, output)

        return {
            "sample_rate": sample_rate,
            "audio_seconds": round(frame_count / sample_rate, 3),
            "load_seconds": round(load_seconds, 3),
            "voice_seconds": round(voice_seconds, 3),
            "synth_seconds": round(synth_seconds, 3),
        }


def _versions():
    from importlib.metadata import version

    return {
        "pocket_tts_version": version("pocket-tts"),
        "torch_version": version("torch"),
        "python": platform.python_version(),
    }


def main():
    protocol_out = _redirect_stdout_to_stderr()
    stdin = open(sys.stdin.fileno(), "r", encoding="utf-8", closefd=False)
    engine = None

    def reply(payload):
        protocol_out.write(
            (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        )

    for line in stdin:
        line = line.strip()

        if not line:
            continue

        request_id = None

        try:
            request = json.loads(line)

            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")

            request_id = request.get("id")
            op = request.get("op")

            if op == "hello":
                if request.get("protocol") != PROTOCOL:
                    raise ValueError(
                        f"protocol {request.get('protocol')!r} is not {PROTOCOL}"
                    )

                reply(
                    {
                        "id": request_id,
                        "ok": True,
                        "protocol": PROTOCOL,
                        "worker_version": WORKER_VERSION,
                        **_versions(),
                    }
                )

            elif op == "synthesize":
                if engine is None:
                    engine = Engine()

                reply({"id": request_id, "ok": True, **engine.synthesize(request)})

            elif op == "shutdown":
                reply({"id": request_id, "ok": True})
                return 0

            else:
                raise ValueError(f"unknown op {op!r}")

        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            reply(
                {
                    "id": request_id,
                    "ok": False,
                    "error": f"{type(error).__name__}: {error}",
                }
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
