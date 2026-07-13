from pathlib import Path

from cache import get_audio_path
from filename import create_filename
from generator import create_audio
from parser import parse_text
from settings import SettingsManager
from stitcher import stitch_audio
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
            combined[key] += current.get(
                key,
                0,
            )

    return combined


def process_chunks(
    chunks,
    filename,
    settings,
):
    output_file = OUTPUT_DIR / filename

    audio_segments = []
    statistics = empty_statistics()

    for chunk in chunks:
        language = chunk["language"]

        if language is None:
            statistics["skipped"] += 1
            continue

        speech_profile = (
            settings.get_speech_profile(
                language
            )
        )

        if speech_profile is None:
            print(
                f"No speech profile configured for language: "
                f"{language}"
            )

            statistics["skipped"] += 1
            continue

        audio_path = get_audio_path(
            text=chunk["text"],
            language=speech_profile.language,
            voice=speech_profile.voice,
            rate=speech_profile.rate,
            volume=speech_profile.volume,
            pitch=speech_profile.pitch,
        )

        if not audio_path.exists():
            print(
                f"Generating: {chunk['text']}"
            )

            create_audio(
                text=chunk["text"],
                voice=speech_profile.voice,
                output_file=str(
                    audio_path
                ),
                rate=speech_profile.rate,
                volume=speech_profile.volume,
                pitch=speech_profile.pitch,
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
                "parenthetical": chunk[
                    "parenthetical"
                ],
            }
        )

    if not audio_segments:
        print(
            "No playable audio segments were found."
        )

        return None, statistics

    print(
        "DEBUG OUTPUT FILE:",
        output_file,
    )

    stitch_audio(
        audio_segments,
        str(output_file),
    )

    print(
        "Card audio created!"
    )

    return filename, statistics

def process_field(
    text,
    filename_suffix,
    settings,
    language=None,
):
    """
    Generate audio for one text field.

    When language is provided, the entire field uses that language.
    Otherwise, the text is parsed and its language is detected
    chunk by chunk.
    """

    text = normalize_text(
        text
    )

    if not text:
        return None, empty_statistics()

    if language is None:
        chunks = parse_text(
            text
        )
    else:
        chunks = [
            {
                "text": text,
                "language": language,
                "parenthetical": False,
            }
        ]

    filename = create_filename(
        text
    ).replace(
        ".mp3",
        f"_{filename_suffix}.mp3",
    )

    return process_chunks(
        chunks,
        filename,
        settings,
    )


def resolve_field_language(
    field_definition,
    settings,
):
    """
    Resolve a field definition to a concrete language.

    Existing language-based definitions remain supported while
    voice-mode definitions are introduced.
    """

    if "voice_mode" not in field_definition:
        return field_definition.get(
            "language"
        )

    voice_mode = field_definition[
        "voice_mode"
    ]

    if voice_mode == "auto":
        return None

    if voice_mode == "front":
        return settings.front_language

    raise ValueError(
        f'Unsupported voice mode: "{voice_mode}".'
    )


def process_field_definitions(
    field_definitions,
    settings,
):
    """
    Process configured field definitions without assuming
    any particular field names.
    """

    result = {}
    statistics = empty_statistics()

    for (
        field_name,
        field_definition,
    ) in field_definitions.items():
        enabled = field_definition.get(
            "enabled",
            True,
        )

        if enabled:
            audio_file, field_statistics = process_field(
                text=field_definition[
                    "text"
                ],
                filename_suffix=field_name,
                language=resolve_field_language(
                    field_definition,
                    settings,
                ),
                settings=settings,
            )
        else:
            audio_file = None
            field_statistics = empty_statistics()

        result[field_name] = audio_file
        result[
            f"{field_name}_processed"
        ] = enabled

        statistics = combine_statistics(
            statistics,
            field_statistics,
        )

    result["statistics"] = statistics

    return result


if __name__ == "__main__":
    settings = SettingsManager().load()

    with open(
        BASE_DIR / "cards" / "test_card.txt",
        "r",
        encoding="utf-8",
    ) as file:
        sample = file.read()

    result = process_field_definitions(
        {
            "front": {
                "text": sample,
                "voice_mode": "front",
                "enabled": True,
            },
            "back": {
                "text": "",
                "voice_mode": "auto",
                "enabled": True,
            },
        },
        settings,
    )

    print(
        "Generated:",
        result,
    )