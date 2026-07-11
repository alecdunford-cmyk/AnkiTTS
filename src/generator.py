import asyncio

import edge_tts


async def generate_audio(
    text,
    voice,
    output_file,
    rate="+0%",
    volume="+0%",
    pitch="+0Hz",
):
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        volume=volume,
        pitch=pitch,
    )

    await communicate.save(output_file)


def create_audio(
    text,
    voice,
    output_file,
    rate="+0%",
    volume="+0%",
    pitch="+0Hz",
):
    asyncio.run(
        generate_audio(
            text=text,
            voice=voice,
            output_file=output_file,
            rate=rate,
            volume=volume,
            pitch=pitch,
        )
    )