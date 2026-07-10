from parser import parse_text
from generator import create_audio
from stitcher import stitch_audio
from cache import get_audio_path
from filename import create_filename


def process_card(text, output_dir="output"):
    chunks = parse_text(text)

    filename = create_filename(text)

    output_file = (
        f"{output_dir}/{filename}"
    )

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
        output_file
    )

    print("Card audio created!")

    return filename


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