from aqt import mw
from aqt.qt import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    Qt,
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

RATE_MINIMUM = -50
RATE_MAXIMUM = 100

PITCH_MINIMUM = -50
PITCH_MAXIMUM = 50

VOLUME_MINIMUM = -50
VOLUME_MAXIMUM = 50


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
            620
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
        self.speech_profile_controls = {}
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
            "target-language fields, customize the speech "
            "profile for each supported language, and select "
            "the Anki note fields AnkiTTS should use."
        )

        description.setWordWrap(
            True
        )

        self.form_layout = QFormLayout()

        self.form_layout.addRow(
            "Fixed language:",
            self.front_language_combo,
        )

        speech_profiles_label = QLabel(
            "<b>Speech profiles</b>"
        )

        self.form_layout.addRow(
            speech_profiles_label
        )

        for (
            language_code,
            display_name,
        ) in VOICE_LANGUAGES.items():
            self.add_speech_profile_controls(
                language_code=language_code,
                display_name=display_name,
                voices_available=voices_available,
            )

        self.reset_all_profiles_button = QPushButton(
            "Reset All Speech Modifiers"
        )

        qconnect(
            self.reset_all_profiles_button.clicked,
            self.reset_all_speech_profile_modifiers,
        )

        self.form_layout.addRow(
            "",
            self.reset_all_profiles_button,
        )

        field_mapping_label = QLabel(
            "<b>Field mapping</b>"
        )

        self.form_layout.addRow(
            field_mapping_label
        )

        for (
            mapping_name,
            mapping_definition,
        ) in self.settings.field_mapping.items():
            self.add_mapping_controls(
                mapping_name=mapping_name,
                mapping_definition=mapping_definition,
            )

        self.add_mapping_button = QPushButton(
            "Add Mapping"
        )

        qconnect(
            self.add_mapping_button.clicked,
            self.add_mapping,
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
            self.form_layout
        )

        main_layout.addWidget(
            self.add_mapping_button
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
        current_voice,
        voices_available,
    ):
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

    def parse_adjustment_value(
        self,
        value,
        suffix,
    ):
        """Convert a stored Edge TTS adjustment string to an integer."""

        if not isinstance(
            value,
            str,
        ):
            return 0

        normalized_value = value.strip()

        if normalized_value.endswith(
            suffix
        ):
            normalized_value = normalized_value[
                :-len(
                    suffix
                )
            ]

        try:
            return int(
                normalized_value
            )

        except ValueError:
            return 0

    def format_adjustment_value(
        self,
        value,
        suffix,
    ):
        """Format an integer as an Edge TTS adjustment string."""

        return f"{value:+d}{suffix}"

    def create_adjustment_slider(
        self,
        minimum,
        maximum,
        current_value,
        suffix,
    ):
        """Create a horizontal slider with a live value label."""

        slider = QSlider(
            Qt.Orientation.Horizontal
        )

        slider.setRange(
            minimum,
            maximum,
        )

        slider.setValue(
            max(
                minimum,
                min(
                    maximum,
                    current_value,
                ),
            )
        )

        slider.setTickPosition(
            QSlider.TickPosition.TicksBelow
        )

        slider.setTickInterval(
            10
        )

        value_label = QLabel(
            self.format_adjustment_value(
                slider.value(),
                suffix,
            )
        )

        value_label.setMinimumWidth(
            55
        )

        qconnect(
            slider.valueChanged,
            lambda value, label=value_label, unit=suffix: (
                label.setText(
                    self.format_adjustment_value(
                        value,
                        unit,
                    )
                )
            ),
        )

        slider_layout = QHBoxLayout()

        slider_layout.addWidget(
            slider
        )

        slider_layout.addWidget(
            value_label
        )

        return (
            slider,
            value_label,
            slider_layout,
        )

    def add_speech_profile_controls(
        self,
        language_code,
        display_name,
        voices_available,
    ):
        """Add controls for one language-specific speech profile."""

        speech_profile = (
            self.settings.get_speech_profile(
                language_code
            )
        )

        if speech_profile is None:
            current_voice = DEFAULT_VOICES[
                language_code
            ]

            current_rate = self.settings.rate
            current_volume = self.settings.volume
            current_pitch = self.settings.pitch

        else:
            current_voice = speech_profile.voice
            current_rate = speech_profile.rate
            current_volume = speech_profile.volume
            current_pitch = speech_profile.pitch

        profile_label = QLabel(
            f"<b>{display_name}</b>"
        )

        self.form_layout.addRow(
            profile_label
        )

        voice_combo = QComboBox()

        self.populate_voice_combo(
            combo=voice_combo,
            language_code=language_code,
            current_voice=current_voice,
            voices_available=voices_available,
        )

        (
            rate_slider,
            rate_value_label,
            rate_layout,
        ) = self.create_adjustment_slider(
            minimum=RATE_MINIMUM,
            maximum=RATE_MAXIMUM,
            current_value=self.parse_adjustment_value(
                current_rate,
                suffix="%",
            ),
            suffix="%",
        )

        (
            pitch_slider,
            pitch_value_label,
            pitch_layout,
        ) = self.create_adjustment_slider(
            minimum=PITCH_MINIMUM,
            maximum=PITCH_MAXIMUM,
            current_value=self.parse_adjustment_value(
                current_pitch,
                suffix="Hz",
            ),
            suffix="Hz",
        )

        (
            volume_slider,
            volume_value_label,
            volume_layout,
        ) = self.create_adjustment_slider(
            minimum=VOLUME_MINIMUM,
            maximum=VOLUME_MAXIMUM,
            current_value=self.parse_adjustment_value(
                current_volume,
                suffix="%",
            ),
            suffix="%",
        )

        reset_button = QPushButton(
            f"Reset {display_name} Modifiers"
        )

        qconnect(
            reset_button.clicked,
            lambda _checked=False, code=language_code: (
                self.reset_speech_profile_modifiers(
                    code
                )
            ),
        )

        self.speech_profile_controls[
            language_code
        ] = {
            "voice": voice_combo,
            "rate": rate_slider,
            "rate_label": rate_value_label,
            "pitch": pitch_slider,
            "pitch_label": pitch_value_label,
            "volume": volume_slider,
            "volume_label": volume_value_label,
            "reset": reset_button,
        }

        self.form_layout.addRow(
            f"{display_name} voice:",
            voice_combo,
        )

        self.form_layout.addRow(
            f"{display_name} rate:",
            rate_layout,
        )

        self.form_layout.addRow(
            f"{display_name} pitch:",
            pitch_layout,
        )

        self.form_layout.addRow(
            f"{display_name} volume:",
            volume_layout,
        )

        self.form_layout.addRow(
            "",
            reset_button,
        )

    def reset_speech_profile_modifiers(
        self,
        language_code,
    ):
        """Reset one language's rate, pitch, and volume."""

        controls = self.speech_profile_controls[
            language_code
        ]

        controls[
            "rate"
        ].setValue(
            0
        )

        controls[
            "pitch"
        ].setValue(
            0
        )

        controls[
            "volume"
        ].setValue(
            0
        )

    def reset_all_speech_profile_modifiers(
        self,
    ):
        """Reset rate, pitch, and volume for every language."""

        for language_code in self.speech_profile_controls:
            self.reset_speech_profile_modifiers(
                language_code
            )

    def add_mapping_controls(
        self,
        mapping_name,
        mapping_definition,
    ):
        """Add controls for one configured field mapping."""

        display_name = (
            mapping_name
            .replace(
                "_",
                " ",
            )
            .title()
        )

        mapping_name_edit = QLineEdit(
            mapping_name
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

        remove_button = QPushButton(
            f"Remove {display_name}"
        )

        qconnect(
            remove_button.clicked,
            lambda _checked=False, identifier=mapping_name: (
                self.remove_mapping(
                    identifier
                )
            ),
        )

        self.mapping_controls[
            mapping_name
        ] = {
            "name": mapping_name_edit,
            "text": text_field_edit,
            "audio": audio_field_edit,
            "voice_mode": voice_mode_combo,
            "remove": remove_button,
        }

        self.form_layout.addRow(
            f"{display_name} mapping name:",
            mapping_name_edit,
        )

        self.form_layout.addRow(
            f"{display_name} text field:",
            text_field_edit,
        )

        self.form_layout.addRow(
            f"{display_name} audio field:",
            audio_field_edit,
        )

        self.form_layout.addRow(
            f"{display_name} voice strategy:",
            voice_mode_combo,
        )

        self.form_layout.addRow(
            "",
            remove_button,
        )

    def create_unique_mapping_name(
        self,
    ):
        """Create an unused temporary name for a new mapping."""

        existing_names = {
            controls[
                "name"
            ].text().strip()
            for controls in self.mapping_controls.values()
        }

        mapping_number = (
            len(
                self.mapping_controls
            )
            + 1
        )

        while True:
            mapping_name = (
                f"mapping_{mapping_number}"
            )

            if mapping_name not in existing_names:
                return mapping_name

            mapping_number += 1

    def add_mapping(
        self,
    ):
        """Add a new empty field mapping to the dialog."""

        mapping_name = (
            self.create_unique_mapping_name()
        )

        self.add_mapping_controls(
            mapping_name=mapping_name,
            mapping_definition={
                "text": "",
                "audio": "",
                "voice_mode": "auto",
            },
        )

    def remove_mapping(
        self,
        mapping_identifier,
    ):
        """Remove one field mapping from the dialog."""

        if (
            len(
                self.mapping_controls
            )
            <= 1
        ):
            showInfo(
                "AnkiTTS must contain at least one "
                "field mapping."
            )

            return

        controls = self.mapping_controls.pop(
            mapping_identifier
        )

        for control_name in (
            "name",
            "text",
            "audio",
            "voice_mode",
            "remove",
        ):
            self.form_layout.removeRow(
                controls[
                    control_name
                ]
            )

    def build_speech_profiles(
        self,
    ):
        """Build serializable language-specific speech profiles."""

        speech_profiles = {}

        for (
            language_code,
            controls,
        ) in self.speech_profile_controls.items():
            speech_profiles[
                language_code
            ] = {
                "voice": controls[
                    "voice"
                ].currentData(),
                "rate": self.format_adjustment_value(
                    controls[
                        "rate"
                    ].value(),
                    "%",
                ),
                "volume": self.format_adjustment_value(
                    controls[
                        "volume"
                    ].value(),
                    "%",
                ),
                "pitch": self.format_adjustment_value(
                    controls[
                        "pitch"
                    ].value(),
                    "Hz",
                ),
            }

        return speech_profiles

    def build_field_mapping(
        self,
    ):
        """Build field_mapping from the current dialog controls."""

        field_mapping = {}

        for controls in self.mapping_controls.values():
            mapping_name = (
                controls[
                    "name"
                ].text().strip()
            )

            if not mapping_name:
                raise ValueError(
                    "Every mapping name must be "
                    "a non-empty string."
                )

            if mapping_name in field_mapping:
                raise ValueError(
                    f'The mapping name "{mapping_name}" '
                    "is used more than once."
                )

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

        config[
            "front_language"
        ] = self.front_language_combo.currentData()

        speech_profiles = (
            self.build_speech_profiles()
        )

        config[
            "speech_profiles"
        ] = speech_profiles

        config[
            "voices"
        ] = {
            language_code: profile[
                "voice"
            ]
            for (
                language_code,
                profile,
            ) in speech_profiles.items()
        }

        try:
            config[
                "field_mapping"
            ] = self.build_field_mapping()

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
                "speech_profiles": {
                    language_code: {
                        "voice": profile.voice,
                        "rate": profile.rate,
                        "volume": profile.volume,
                        "pitch": profile.pitch,
                    }
                    for (
                        language_code,
                        profile,
                    ) in (
                        validated_settings
                        .speech_profiles
                        .items()
                    )
                },
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