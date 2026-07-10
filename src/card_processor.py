from parser import parse_text
from generator import create_audio
from stitcher import stitch_audio
from cache import get_audio_path


def process_card(text):
    chunks = parse_text(text)

    audio_files = []

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

        audio_files.append(
            str(audio_path)
        )

    stitch_audio(
        audio_files,
        "output/card_audio.mp3"
    )

    print("Card audio created!")


if __name__ == "__main__":

    sample = """
rundown, spiel; Ex. faire un topo sur (give a rundown on), c'est toujours le même topo (it's always the same old story), Tu vois un peu le topo? (Get the picture?)
"""

    process_card(sample)