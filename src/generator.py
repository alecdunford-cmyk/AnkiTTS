import asyncio
import edge_tts

from config import VOICES


async def generate_audio(text, language, output_file):
    voice = VOICES[language]

    communicate = edge_tts.Communicate(
        text,
        voice
    )

    await communicate.save(output_file)


def create_audio(text, language, output_file):
    asyncio.run(
        generate_audio(text, language, output_file)
    )