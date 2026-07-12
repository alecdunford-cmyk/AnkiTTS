from pathlib import Path

from parser import parse_text
from generator import create_audio
from stitcher import stitch_audio
from cache import get_audio_path
from filename import create_filename
from settings import SettingsManager
from text_normalizer import normalize_text


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


def empty_statistics():
    return {
        "generated": 0,
        "cached": 0,
        "skipped": 0,
    }


def combine_statistics(*statistics):
    combined = empty_statistics()

    for current in statistics:
        for key in combined:
            combined[key] += current.get(key, 0)

    return combined


def process_chunks(chunks, filename, settings):
    output_file = OUTPUT_DIR / filename

    audio_segments = []
    statistics = empty_statistics()

    for chunk in chunks:
        language = chunk["language"]

        if language is None:
            statistics["skipped"] += 1
            continue

        voice = settings.voices.get(language)

        if voice is None:
            print(
                f"No voice configured for language: {language}"
            )

            statistics["skipped"] += 1
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

            statistics["generated"] += 1

        else:
            print(
                f"Using cache: {chunk['text']}"
            )

            statistics["cached"] += 1

        audio_segments.append(
            {
                "file": str(audio_path),
                "text": chunk["text"],
                "parenthetical": chunk["parenthetical"],
            }
        )

    if not audio_segments:
        print("No playable audio segments were found.")

        return None, statistics

    print("DEBUG OUTPUT FILE:", output_file)

    stitch_audio(
        audio_segments,
        str(output_file),
    )

    print("Card audio created!")

    return filename, statistics


def process_front(text, language, settings):
    text = normalize_text(text)

    if not text:
        return None, empty_statistics()

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
    text = normalize_text(text)

    if not text:
        return None, empty_statistics()

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

    front_audio, front_statistics = process_front(
        front,
        front_language,
        settings,
    )

    back_audio, back_statistics = process_back(
        back,
        settings,
    )

    return {
        "front": front_audio,
        "back": back_audio,
        "statistics": combine_statistics(
            front_statistics,
            back_statistics,
        ),
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