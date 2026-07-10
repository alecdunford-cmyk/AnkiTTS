from generator import create_audio


text = "Bonjour, je m'appelle Alec. J'étudie le français."

create_audio(
    text,
    "fr",
    "output/french_test2.mp3"
)

print("Done!")