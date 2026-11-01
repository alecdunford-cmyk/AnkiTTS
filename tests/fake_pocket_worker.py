"""
A stand-in for providers/pocket_worker.py speaking the same protocol, for
the regression tests. Needs only the standard library. Behaviour by text:
"FAIL" -> error response, "HANG" -> never answers, "EXIT" -> process exits,
"QUIETTAIL" -> a loud tone, then 60 ms of quiet speech-level tone (about
-50 dBFS), then 400 ms of digital silence.
"""

import json
import math
import os
import struct
import sys
import wave


def write_tone(path, seconds=0.5, rate=24000):
    frames = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
        for i in range(int(seconds * rate))
    )

    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames)


QUIET_TAIL_BODY_SECONDS = 0.5
QUIET_TAIL_SPEECH_SECONDS = 0.06
QUIET_TAIL_SILENCE_SECONDS = 0.4


def write_quiet_tail(path, rate=24000):
    def tone(seconds, amplitude):
        return b"".join(
            struct.pack("<h", int(amplitude * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(int(seconds * rate))
        )

    frames = (
        tone(QUIET_TAIL_BODY_SECONDS, 8000)
        + tone(QUIET_TAIL_SPEECH_SECONDS, 147)
        + b"\x00\x00" * int(QUIET_TAIL_SILENCE_SECONDS * rate)
    )

    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames)


def main():
    out = sys.stdout

    for line in sys.stdin:
        request = json.loads(line)
        request_id = request.get("id")
        op = request.get("op")

        if op == "hello":
            response = {
                "id": request_id,
                "ok": True,
                "protocol": 1,
                "worker_version": "fake",
                "pocket_tts_version": "0.0-fake",
                "torch_version": "none",
                "python": sys.version.split()[0],
                "pid": os.getpid(),
            }

        elif op == "synthesize":
            text = request["text"]

            if text == "HANG":
                continue

            if text == "EXIT":
                return 3

            if text == "FAIL":
                response = {"id": request_id, "ok": False, "error": "ValueError: fake failure"}

            else:
                if text == "QUIETTAIL":
                    write_quiet_tail(request["output"])
                    audio_seconds = (
                        QUIET_TAIL_BODY_SECONDS
                        + QUIET_TAIL_SPEECH_SECONDS
                        + QUIET_TAIL_SILENCE_SECONDS
                    )

                else:
                    write_tone(request["output"])
                    audio_seconds = 0.5

                response = {
                    "id": request_id,
                    "ok": True,
                    "sample_rate": 24000,
                    "audio_seconds": audio_seconds,
                    "load_seconds": 0.0,
                    "voice_seconds": 0.0,
                    "synth_seconds": 0.01,
                    "pid": os.getpid(),
                    "model": request["model"],
                }

        elif op == "shutdown":
            out.write(json.dumps({"id": request_id, "ok": True}) + "\n")
            out.flush()
            return 0

        else:
            response = {"id": request_id, "ok": False, "error": f"ValueError: unknown op {op!r}"}

        out.write(json.dumps(response) + "\n")
        out.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
