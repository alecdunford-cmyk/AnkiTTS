from stitcher import stitch_audio


files = [
    "output/french_test.mp3",
    "output/french_test2.mp3",
]


stitch_audio(
    files,
    "output/combined_test.mp3"
)

print("Combined audio created!")