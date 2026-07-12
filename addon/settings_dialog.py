from aqt import mw
from aqt.qt import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)
from aqt.utils import qconnect, showInfo

from settings import AppSettings
from voice_manager import VoiceManager


LANGUAGES = {
    "French": "fr",
    "English": "en",
    "Japanese": "ja",
}

VOICE_LANGUAGES = {
    "fr": "French",
    "en": "English",
    "ja": "Japanese",
}

DEFAULT_VOICES = {
    "fr": "fr-FR-DeniseNeural",
    "en": "en-US-JennyNeural",
    "ja": "ja-JP-NanamiNeural",
}


class SettingsDialog(QDialog):
    """Graphical settings window for AnkiTTS."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("AnkiTTS Settings")
        self.setMinimumWidth(480)

        config = mw.addonManager.getConfig(__package__) or {}
        self.settings = AppSettings.from_dict(config)

        self.voice_manager = VoiceManager()

        self.front_language_combo = QComboBox()
        self.voice_combos = {}

        self.front_text_field_edit = QLineEdit(
            self.settings.front_text_field
        )

        self.back_text_field_edit = QLineEdit(
            self.settings.back_text_field
        )

        self.front_audio_field_edit = QLineEdit(
            self.settings.front_audio_field
        )

        self.back_audio_field_edit = QLineEdit(
            self.settings.back_audio_field
        )

        self.populate_language_combo()

        try:
            self.voice_manager.get_all_voices()
            voices_available = True

        except Exception as error:
            print(
                "Could not retrieve Edge TTS voices:",
                error,
            )

            voices_available = False

        description = QLabel(
            "Choose the language used for the front of each card, "
            "the preferred voice for each supported language, and "
            "the note fields AnkiTTS should use."
        )
        description.setWordWrap(True)

        form_layout = QFormLayout()

        form_layout.addRow(
            "Front language:",
            self.front_language_combo,
        )

        for language_code, display_name in VOICE_LANGUAGES.items():
            combo = QComboBox()

            self.populate_voice_combo(
                combo=combo,
                language_code=language_code,
                voices_available=voices_available,
            )

            self.voice_combos[language_code] = combo

            form_layout.addRow(
                f"{display_name} voice:",
                combo,
            )

        field_mapping_label = QLabel(
            "<b>Field mapping</b>"
        )

        form_layout.addRow(
            field_mapping_label
        )

        form_layout.addRow(
            "Front text field:",
            self.front_text_field_edit,
        )

        form_layout.addRow(
            "Back text field:",
            self.back_text_field_edit,
        )

        form_layout.addRow(
            "Front audio field:",
            self.front_audio_field_edit,
        )

        form_layout.addRow(
            "Back audio field:",
            self.back_audio_field_edit,
        )

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )

        qconnect(
            self.button_box.accepted,
            self.save_settings,
        )

        qconnect(
            self.button_box.rejected,
            self.reject,
        )

        main_layout = QVBoxLayout()
        main_layout.addWidget(description)
        main_layout.addLayout(form_layout)
        main_layout.addWidget(self.button_box)

        self.setLayout(main_layout)

    def populate_language_combo(self):
        for display_name, language_code in LANGUAGES.items():
            self.front_language_combo.addItem(
                display_name,
                language_code,
            )

        current_index = self.front_language_combo.findData(
            self.settings.front_language
        )

        if current_index >= 0:
            self.front_language_combo.setCurrentIndex(
                current_index
            )

    def populate_voice_combo(
        self,
        combo,
        language_code,
        voices_available,
    ):
        current_voice = self.settings.voices.get(
            language_code,
            DEFAULT_VOICES[language_code],
        )

        if voices_available:
            matching_voices = self.voice_manager.get_voices(
                language_code
            )

            for voice in matching_voices:
                combo.addItem(
                    self.voice_manager.get_display_name(
                        voice
                    ),
                    voice["ShortName"],
                )

        current_index = combo.findData(
            current_voice
        )

        if current_index < 0:
            combo.addItem(
                current_voice,
                current_voice,
            )

            current_index = combo.findData(
                current_voice
            )

        combo.setCurrentIndex(
            current_index
        )

    def save_settings(self):
        config = mw.addonManager.getConfig(__package__) or {}

        voices = dict(
            config.get(
                "voices",
                self.settings.voices,
            )
        )

        for language_code, combo in self.voice_combos.items():
            voices[language_code] = combo.currentData()

        config["front_language"] = (
            self.front_language_combo.currentData()
        )

        config["voices"] = voices

        config["front_text_field"] = (
            self.front_text_field_edit.text().strip()
        )

        config["back_text_field"] = (
            self.back_text_field_edit.text().strip()
        )

        config["front_audio_field"] = (
            self.front_audio_field_edit.text().strip()
        )

        config["back_audio_field"] = (
            self.back_audio_field_edit.text().strip()
        )

        try:
            validated_settings = AppSettings.from_dict(
                config
            )

        except ValueError as error:
            showInfo(
                f"Could not save AnkiTTS settings:\n\n{error}"
            )
            return

        config.update(
            {
                "front_language": (
                    validated_settings.front_language
                ),
                "voices": validated_settings.voices,
                "front_text_field": (
                    validated_settings.front_text_field
                ),
                "back_text_field": (
                    validated_settings.back_text_field
                ),
                "front_audio_field": (
                    validated_settings.front_audio_field
                ),
                "back_audio_field": (
                    validated_settings.back_audio_field
                ),
                "rate": validated_settings.rate,
                "volume": validated_settings.volume,
                "pitch": validated_settings.pitch,
            }
        )

        mw.addonManager.writeConfig(
            __package__,
            config,
        )

        showInfo("AnkiTTS settings saved.")
        self.accept()


def show_settings_dialog():
    dialog = SettingsDialog(mw)
    dialog.exec()