import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import ankitts_log
from settings import AppSettings, SettingsManager, read_addon_config


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


def test_addon_config_overlays_meta_on_defaults():
    with TemporaryDirectory() as directory:
        addon_dir = Path(directory)

        (addon_dir / "config.json").write_text(
            json.dumps(
                {
                    "front_language": "fr",
                    "rate": "+0%",
                    "voices": {"fr": "fr-FR-DeniseNeural"},
                }
            ),
            encoding="utf-8",
        )

        (addon_dir / "meta.json").write_text(
            json.dumps(
                {
                    "disabled": False,
                    "config": {
                        "front_language": "en",
                        "field_mapping": {
                            "expression": {
                                "text": "Front",
                                "audio": "Front Audio",
                                "speech_profile": "auto",
                            }
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        config = read_addon_config(addon_dir)

        assert config["front_language"] == "en"
        assert config["rate"] == "+0%"
        assert "disabled" not in config

        settings = SettingsManager.load_addon_config(addon_dir)

        assert settings.front_language == "en"
        assert list(settings.field_mapping) == ["expression"]


def test_addon_config_without_meta_uses_defaults():
    with TemporaryDirectory() as directory:
        addon_dir = Path(directory)

        (addon_dir / "config.json").write_text(
            json.dumps({"front_language": "ja"}),
            encoding="utf-8",
        )

        assert read_addon_config(addon_dir) == {"front_language": "ja"}


def test_log_directory_override():
    original = os.environ.get("ANKITTS_LOG_DIR")

    try:
        os.environ["ANKITTS_LOG_DIR"] = "C:/somewhere/logs"

        assert ankitts_log.default_log_directory() == Path(
            "C:/somewhere/logs"
        )

        del os.environ["ANKITTS_LOG_DIR"]

        assert ankitts_log.default_log_directory().parts[-3:] == (
            "addon",
            "user_files",
            "logs",
        )

    finally:
        if original is None:
            os.environ.pop("ANKITTS_LOG_DIR", None)
        else:
            os.environ["ANKITTS_LOG_DIR"] = original


def run():
    checks = [
        test_default_settings,
        test_legacy_voice_mode_migration,
        test_invalid_speech_profile,
        test_addon_config_overlays_meta_on_defaults,
        test_addon_config_without_meta_uses_defaults,
        test_log_directory_override,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")