from settings import AppSettings


def test_default_settings():
    settings = AppSettings()

    settings.validate()

    assert settings.front_language == "fr"

    assert settings.field_mapping["front"]["speech_profile"] == "front"
    assert settings.field_mapping["back"]["speech_profile"] == "auto"


def test_legacy_voice_mode_migration():
    settings = AppSettings.from_dict(
        {
            "field_mapping": {
                "expression": {
                    "text": "Front",
                    "audio": "Front Audio",
                    "voice_mode": "front",
                },
                "definition": {
                    "text": "Back",
                    "audio": "Back Audio",
                    "voice_mode": "auto",
                },
            }
        }
    )

    assert (
        settings.field_mapping["expression"]["speech_profile"]
        == "front"
    )

    assert (
        settings.field_mapping["definition"]["speech_profile"]
        == "auto"
    )


def test_invalid_speech_profile():
    try:
        AppSettings.from_dict(
            {
                "field_mapping": {
                    "front": {
                        "text": "Front",
                        "audio": "Front Audio",
                        "speech_profile": "banana",
                    }
                }
            }
        )

    except ValueError:
        return

    raise AssertionError(
        "Invalid speech profile was accepted."
    )


def run():
    test_default_settings()
    test_legacy_voice_mode_migration()
    test_invalid_speech_profile()