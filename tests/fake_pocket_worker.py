"""
A stand-in for providers/pocket_worker.py speaking the same protocol, for
the regression tests. Needs only the standard library. Behaviour by text:
"FAIL" -> error response, "HANG" -> never answers, "EXIT" -> process exits.
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
                write_tone(request["output"])
                response = {
                    "id": request_id,
                    "ok": True,
                    "sample_rate": 24000,
                    "audio_seconds": 0.5,
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
