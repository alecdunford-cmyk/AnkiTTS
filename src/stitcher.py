from pydub import AudioSegment


def get_pause(segment):
    """
    Determine pause length based on context.
    """

    if segment["parenthetical"]:
        return 350

    if segment["text"].endswith((".", "!", "?")):
        return 700

    return 300


def stitch_audio(segments, output_file):

    combined = AudioSegment.empty()

    for segment in segments:
        audio = AudioSegment.from_file(
            segment["file"]
        )

        combined += audio

        combined += AudioSegment.silent(
            duration=get_pause(segment)
        )

    combined.export(
        output_file,
        format="mp3"
    )