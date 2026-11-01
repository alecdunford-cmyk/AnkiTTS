from cache import get_audio_path
from generator import create_audio
from settings import SettingsManager


text = "Bonjour, je m'appelle Alec. J'étudie le français."

settings = SettingsManager.load_addon_config()
profile = settings.get_speech_profile(
    "fr"
)

result = create_audio(
    text,
    "fr",
    profile,
    lambda identity, fields: get_audio_path(
        text=text,
        language="fr",
        provider_identity=identity,
        **fields,
    ),
    settings=settings,
)

print("Done!", result.provider_id, result.path)
