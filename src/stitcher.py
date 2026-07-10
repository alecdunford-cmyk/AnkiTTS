from pydub import AudioSegment


def stitch_audio(files, output_file):
    combined = AudioSegment.empty()

    for file in files:
        audio = AudioSegment.from_file(file)
        combined += audio

        # Half-second pause between language segments
        combined += AudioSegment.silent(duration=500)

    combined.export(
        output_file,
        format="mp3"
    )