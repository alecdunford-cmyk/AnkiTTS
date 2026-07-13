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

VOICE_MODES = {
    "Fixed language": "front",
    "Automatic detection": "auto",
}


class SettingsDialog(QDialog):
    """Graphical settings window for AnkiTTS."""

    def __init__(
        self,
        parent=None,
    ):
        super().__init__(
            parent
        )

        self.setWindowTitle(
            "AnkiTTS Settings"
        )

        self.setMinimumWidth(
            480
        )

        config = (
            mw.addonManager.getConfig(
                __package__
            )
            or {}
        )

        self.settings = AppSettings.from_dict(
            config
        )

        self.voice_manager = VoiceManager()

        self.front_language_combo = QComboBox()
        self.voice_combos = {}
        self.mapping_controls = {}

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
            "Choose the fixed language used by configured "
            "target-language fields, the preferred voice for "
            "each supported language, and the Anki note fields "
            "AnkiTTS should use."
        )

        description.setWordWrap(
            True
        )

        form_layout = QFormLayout()

        form_layout.addRow(
            "Fixed language:",
            self.front_language_combo,
        )

        for (
            language_code,
            display_name,
        ) in VOICE_LANGUAGES.items():
            combo = QComboBox()

            self.populate_voice_combo(
                combo=combo,
                language_code=language_code,
                voices_available=voices_available,
            )

            self.voice_combos[
                language_code
            ] = combo

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

        for (
            mapping_name,
            mapping_definition,
        ) in self.settings.field_mapping.items():
            display_name = (
                mapping_name
                .replace(
                    "_",
                    " ",
                )
                .title()
            )

            text_field_edit = QLineEdit(
                mapping_definition[
                    "text"
                ]
            )

            audio_field_edit = QLineEdit(
                mapping_definition[
                    "audio"
                ]
            )

            voice_mode_combo = QComboBox()

            self.populate_voice_mode_combo(
                combo=voice_mode_combo,
                current_voice_mode=mapping_definition[
                    "voice_mode"
                ],
            )

            self.mapping_controls[
                mapping_name
            ] = {
                "text": text_field_edit,
                "audio": audio_field_edit,
                "voice_mode": voice_mode_combo,
            }

            form_layout.addRow(
                f"{display_name} text field:",
                text_field_edit,
            )

            form_layout.addRow(
                f"{display_name} audio field:",
                audio_field_edit,
            )

            form_layout.addRow(
                f"{display_name} voice strategy:",
                voice_mode_combo,
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

        main_layout.addWidget(
            description
        )

        main_layout.addLayout(
            form_layout
        )

        main_layout.addWidget(
            self.button_box
        )

        self.setLayout(
            main_layout
        )

    def populate_language_combo(
        self,
    ):
        for (
            display_name,
            language_code,
        ) in LANGUAGES.items():
            self.front_language_combo.addItem(
                display_name,
                language_code,
            )

        current_index = (
            self.front_language_combo.findData(
                self.settings.front_language
            )
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
        current_voice = (
            self.settings.voices.get(
                language_code,
                DEFAULT_VOICES[
                    language_code
                ],
            )
        )

        if voices_available:
            matching_voices = (
                self.voice_manager.get_voices(
                    language_code
                )
            )

            for voice in matching_voices:
                combo.addItem(
                    self.voice_manager.get_display_name(
                        voice
                    ),
                    voice[
                        "ShortName"
                    ],
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

    def populate_voice_mode_combo(
        self,
        combo,
        current_voice_mode,
    ):
        """Populate a field mapping's voice strategy selector."""

        for (
            display_name,
            voice_mode,
        ) in VOICE_MODES.items():
            combo.addItem(
                display_name,
                voice_mode,
            )

        current_index = combo.findData(
            current_voice_mode
        )

        if current_index >= 0:
            combo.setCurrentIndex(
                current_index
            )

    def build_field_mapping(
        self,
    ):
        """Build field_mapping from the current dialog controls."""

        field_mapping = {}

        for (
            mapping_name,
            controls,
        ) in self.mapping_controls.items():
            field_mapping[
                mapping_name
            ] = {
                "text": controls[
                    "text"
                ].text().strip(),
                "audio": controls[
                    "audio"
                ].text().strip(),
                "voice_mode": controls[
                    "voice_mode"
                ].currentData(),
            }

        return field_mapping

    def save_settings(
        self,
    ):
        config = (
            mw.addonManager.getConfig(
                __package__
            )
            or {}
        )

        voices = dict(
            config.get(
                "voices",
                self.settings.voices,
            )
        )

        for (
            language_code,
            combo,
        ) in self.voice_combos.items():
            voices[
                language_code
            ] = combo.currentData()

        config[
            "front_language"
        ] = self.front_language_combo.currentData()

        config[
            "voices"
        ] = voices

        config[
            "field_mapping"
        ] = self.build_field_mapping()

        try:
            validated_settings = (
                AppSettings.from_dict(
                    config
                )
            )

        except ValueError as error:
            showInfo(
                "Could not save AnkiTTS settings:"
                f"\n\n{error}"
            )

            return

        config.update(
            {
                "front_language": (
                    validated_settings.front_language
                ),
                "voices": (
                    validated_settings.voices
                ),
                "field_mapping": (
                    validated_settings.field_mapping
                ),
                "rate": (
                    validated_settings.rate
                ),
                "volume": (
                    validated_settings.volume
                ),
                "pitch": (
                    validated_settings.pitch
                ),
            }
        )

        mw.addonManager.writeConfig(
            __package__,
            config,
        )

        showInfo(
            "AnkiTTS settings saved."
        )

        self.accept()


def show_settings_dialog():
    dialog = SettingsDialog(
        mw
    )

    dialog.exec()