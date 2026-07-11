from pathlib import Path

from parser import parse_text
from generator import create_audio
from stitcher import stitch_audio
from cache import get_audio_path
from filename import create_filename


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


def process_chunks(chunks, filename):
    output_file = OUTPUT_DIR / filename

    audio_segments = []

    for chunk in chunks:
        language = chunk["language"]

        if language is None:
            continue

        audio_path = get_audio_path(
            chunk["text"],
            language
        )

        if not audio_path.exists():
            print(
                f"Generating: {chunk['text']}"
            )

            create_audio(
                chunk["text"],
                language,
                str(audio_path)
            )

        else:
            print(
                f"Using cache: {chunk['text']}"
            )

        audio_segments.append(
            {
                "file": str(audio_path),
                "text": chunk["text"],
                "parenthetical": chunk["parenthetical"]
            }
        )

    print("DEBUG OUTPUT FILE:", output_file)

    stitch_audio(
        audio_segments,
        str(output_file)
    )

    print("Card audio created!")

    return filename


def process_front(text, language):
    if not text.strip():
        return None

    chunks = [
        {
            "text": text,
            "language": language,
            "parenthetical": False
        }
    ]

    filename = create_filename(text).replace(
        ".mp3",
        "_front.mp3"
    )

    return process_chunks(
        chunks,
        filename
    )


def process_back(text):
    if not text.strip():
        return None

    chunks = parse_text(text)

    filename = create_filename(text).replace(
        ".mp3",
        "_back.mp3"
    )

    return process_chunks(
        chunks,
        filename
    )


def process_card(front, back, front_language):
    front_audio = process_front(
        front,
        front_language
    )

    back_audio = process_back(
        back
    )

    return {
        "front": front_audio,
        "back": back_audio
    }


if __name__ == "__main__":

    with open(
        "cards/test_card.txt",
        "r",
        encoding="utf-8"
    ) as file:
        sample = file.read()

    result = process_card(sample)

    print(
        "Generated:",
        result
    )