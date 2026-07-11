from pathlib import Path

from parser import parse_text
from generator import create_audio
from stitcher import stitch_audio
from cache import get_audio_path
from filename import create_filename
from settings import SettingsManager


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


def process_chunks(chunks, filename, settings):
    output_file = OUTPUT_DIR / filename

    audio_segments = []

    for chunk in chunks:
        language = chunk["language"]

        if language is None:
            continue

        voice = settings.voices.get(language)

        if voice is None:
            print(
                f"No voice configured for language: {language}"
            )
            continue

        audio_path = get_audio_path(
            text=chunk["text"],
            language=language,
            voice=voice,
            rate=settings.rate,
            volume=settings.volume,
            pitch=settings.pitch,
        )

        if not audio_path.exists():
            print(
                f"Generating: {chunk['text']}"
            )

            create_audio(
                text=chunk["text"],
                voice=voice,
                output_file=str(audio_path),
                rate=settings.rate,
                volume=settings.volume,
                pitch=settings.pitch,
            )

        else:
            print(
                f"Using cache: {chunk['text']}"
            )

        audio_segments.append(
            {
                "file": str(audio_path),
                "text": chunk["text"],
                "parenthetical": chunk["parenthetical"],
            }
        )

    print("DEBUG OUTPUT FILE:", output_file)

    stitch_audio(
        audio_segments,
        str(output_file),
    )

    print("Card audio created!")

    return filename


def process_front(text, language, settings):
    if not text.strip():
        return None

    chunks = [
        {
            "text": text,
            "language": language,
            "parenthetical": False,
        }
    ]

    filename = create_filename(text).replace(
        ".mp3",
        "_front.mp3",
    )

    return process_chunks(
        chunks,
        filename,
        settings,
    )


def process_back(text, settings):
    if not text.strip():
        return None

    chunks = parse_text(text)

    filename = create_filename(text).replace(
        ".mp3",
        "_back.mp3",
    )

    return process_chunks(
        chunks,
        filename,
        settings,
    )


def process_card(
    front,
    back,
    front_language=None,
    settings=None,
):
    if settings is None:
        settings = SettingsManager().load()

    if front_language is None:
        front_language = settings.front_language

    front_audio = process_front(
        front,
        front_language,
        settings,
    )

    back_audio = process_back(
        back,
        settings,
    )

    return {
        "front": front_audio,
        "back": back_audio,
    }


if __name__ == "__main__":
    settings = SettingsManager().load()

    with open(
        BASE_DIR / "cards" / "test_card.txt",
        "r",
        encoding="utf-8",
    ) as file:
        sample = file.read()

    result = process_card(
        front=sample,
        back="",
        settings=settings,
    )

    print(
        "Generated:",
        result,
    )