from parser import parse_text
from generator import create_audio
from stitcher import stitch_audio
from cache import get_audio_path


def process_card(text):
    chunks = parse_text(text)

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

    stitch_audio(
        audio_segments,
        "output/card_audio.mp3"
    )

    print("Card audio created!")


if __name__ == "__main__":

    with open(
        "cards/test_card.txt",
        "r",
        encoding="utf-8"
    ) as file:
        sample = file.read()

    process_card(sample)