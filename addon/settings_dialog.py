from pathlib import Path

from aqt import mw
from aqt.qt import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    Qt,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import askUser, qconnect, showInfo

from cache import (
    clear_audio_cache,
    get_cache_statistics,
)

from earcons import default_earcon_directory
from settings import (
    DEFAULT_ROLE_VOICES,
    DEFAULT_TEMPO_PROFILES,
    PROVIDER_IDS,
    SETTINGS_VERSION,
    AppSettings,
)
from voice_manager import VoiceManager, role_voice_choices


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

SPEECH_PROFILE_OPTIONS = {
    "Automatic detection": "auto",
    "Front language": "front",
    "French": "fr",
    "English": "en",
    "Japanese": "ja",
}

ROLE_VOICE_SLOTS = (
    (
        "fr",
        "French",
        "content",
    ),
    (
        "fr",
        "French",
        "label",
    ),
    (
        "en",
        "English",
        "content",
    ),
    (
        "en",
        "English",
        "label",
    ),
)

EARCON_LABELS = (
    (
        "sectionBoundary",
        "Section boundary",
    ),
    (
        "answerStart",
        "Answer start",
    ),
    (
        "directionFlip",
        "Direction flip",
    ),
)

TEMPO_COLUMNS = (
    (
        "Profile",
        None,
        None,
    ),
    (
        "Rate",
        "rate",
        float,
    ),
    (
        "Pause factor",
        "pauseFactor",
        float,
    ),
    (
        "Min pause (ms)",
        "minPauseMs",
        int,
    ),
    (
        "Max pause (ms)",
        "maxPauseMs",
        int,
    ),
    (
        "Section pause (ms)",
        "boundaryPauseMs",
        int,
    ),
)

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

        self.resize(
            720,
            650,
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
        self.role_voice_controls = {}

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

        self.tab_widget = QTabWidget()

        self.create_general_tab()

        self.create_speech_profiles_tab(
            voices_available=voices_available
        )

        self.create_field_mappings_tab()

        self.create_providers_tab()

        self.create_speech_plan_tab(
            voices_available=voices_available
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
            self.tab_widget
        )

        main_layout.addWidget(
            self.button_box
        )

        self.setLayout(
            main_layout
        )

    def create_general_tab(
        self,
    ):
        """Create the general settings tab."""

        general_tab = QWidget()
        general_layout = QVBoxLayout()

        description = QLabel(
            "Choose the language used by mappings whose Speech "
            "Profile is set to Front language. Mappings configured "
            "for Automatic detection identify the language of each "
            "text segment automatically."
        )

        description.setWordWrap(
            True
        )

        general_form_layout = QFormLayout()

        general_form_layout.addRow(
            "Front language:",
            self.front_language_combo,
        )

        cache_heading = QLabel(
            "<b>Audio Cache</b>"
        )

        cache_description = QLabel(
            "Cached audio speeds up repeated generation. Clearing "
            "the cache does not remove audio already copied into "
            "Anki's media collection."
        )

        cache_description.setWordWrap(
            True
        )

        self.cache_statistics_label = QLabel()

        self.clear_cache_button = QPushButton(
            "Clear Entire Audio Cache"
        )

        qconnect(
            self.clear_cache_button.clicked,
            self.clear_entire_audio_cache,
        )

        self.update_cache_statistics()

        general_layout.addWidget(
            description
        )

        general_layout.addLayout(
            general_form_layout
        )

        general_layout.addSpacing(
            18
        )

        general_layout.addWidget(
            cache_heading
        )

        general_layout.addWidget(
            cache_description
        )

        general_layout.addWidget(
            self.cache_statistics_label
        )

        general_layout.addWidget(
            self.clear_cache_button
        )

        general_layout.addStretch()

        general_tab.setLayout(
            general_layout
        )

        self.tab_widget.addTab(
            general_tab,
            "General",
        )

    def create_providers_tab(
        self,
    ):
        """
        Create the minimal provider tab: chain order and paths.

        Keys are never entered here; Fish reads FISH_API_KEY from the
        environment.
        """

        providers_tab = QWidget()
        providers_layout = QVBoxLayout()

        description = QLabel(
            "Providers are tried in order for every segment; a provider "
            "that is not configured, not reachable or fails hands the "
            "segment to the next. Ids: pocket (local voice clone), fish "
            "(Fish Audio, paid, key from FISH_API_KEY), edge (Microsoft "
            "Edge voices). A provider left out of the order is off; its "
            "settings below are kept."
        )

        description.setWordWrap(
            True
        )

        pocket = self.settings.get_provider_settings(
            "pocket"
        )

        fish = self.settings.get_provider_settings(
            "fish"
        )

        self.provider_chain_edit = QLineEdit(
            ", ".join(
                self.settings.provider_chain
            )
        )

        self.pocket_python_edit = QLineEdit(
            str(
                pocket.get(
                    "engine_python",
                    "",
                )
            )
        )

        self.pocket_clip_edits = {}
        self.fish_reference_edits = {}

        form_layout = QFormLayout()

        form_layout.addRow(
            "Provider order:",
            self.provider_chain_edit,
        )

        form_layout.addRow(
            "Pocket engine Python:",
            self.pocket_python_edit,
        )

        for language_code, language_name in (
            (
                "fr",
                "French",
            ),
            (
                "en",
                "English",
            ),
        ):
            clip_edit = QLineEdit(
                str(
                    pocket.get(
                        "reference_clips",
                        {},
                    ).get(
                        language_code,
                        "",
                    )
                )
            )

            self.pocket_clip_edits[
                language_code
            ] = clip_edit

            form_layout.addRow(
                f"Pocket {language_name} reference clip:",
                clip_edit,
            )

        self.fish_model_edit = QLineEdit(
            str(
                fish.get(
                    "model",
                    "",
                )
            )
        )

        form_layout.addRow(
            "Fish model:",
            self.fish_model_edit,
        )

        for language_code, language_name in (
            (
                "fr",
                "French",
            ),
            (
                "en",
                "English",
            ),
        ):
            reference_edit = QLineEdit(
                str(
                    fish.get(
                        "reference_ids",
                        {},
                    ).get(
                        language_code,
                        "",
                    )
                )
            )

            self.fish_reference_edits[
                language_code
            ] = reference_edit

            form_layout.addRow(
                f"Fish {language_name} voice id:",
                reference_edit,
            )

        providers_layout.addWidget(
            description
        )

        providers_layout.addLayout(
            form_layout
        )

        providers_layout.addStretch()

        providers_tab.setLayout(
            providers_layout
        )

        self.tab_widget.addTab(
            providers_tab,
            "Providers",
        )

    def create_speech_plan_tab(
        self,
        voices_available,
    ):
        """Create the tab for what schema-version-2 speech plans resolve to."""

        self.voices_available = voices_available

        speech_plan_content = QWidget()
        self.speech_plan_layout = QVBoxLayout()

        description = QLabel(
            "<b>Role voices</b><br>Speech plans from RCE name a role, content "
            "or label, for each segment. Each language has one voice per "
            "role, chosen here. The language is the segment's: any Edge voice "
            "may be used, and the multilingual ones speak other languages "
            "well. Changing a voice regenerates that role's audio on the next "
            "run and nothing else. Plain notes and older plans keep using the "
            "Speech Profiles tab."
        )

        description.setWordWrap(
            True
        )

        self.speech_plan_layout.addWidget(
            description
        )

        role_voice_form = QFormLayout()

        for (
            language_code,
            language_name,
            voice_role,
        ) in ROLE_VOICE_SLOTS:
            self.add_role_voice_controls(
                role_voice_form,
                language_code,
                language_name,
                voice_role,
            )

        self.speech_plan_layout.addLayout(
            role_voice_form
        )

        qconnect(
            self.provider_chain_edit.editingFinished,
            self.refresh_role_voice_providers,
        )

        self.add_tempo_profile_controls()

        self.add_earcon_controls()

        self.speech_plan_layout.addStretch()

        speech_plan_content.setLayout(
            self.speech_plan_layout
        )

        scroll_area = QScrollArea()

        scroll_area.setWidgetResizable(
            True
        )

        scroll_area.setWidget(
            speech_plan_content
        )

        self.tab_widget.addTab(
            scroll_area,
            "Speech Plans",
        )

    def add_earcon_controls(
        self,
    ):
        """Add one sound-file path per earcon; blank is the generated tone."""

        description = QLabel(
            "<b>Earcons</b><br>Short sounds a plan can place before or after "
            "a segment. Leave a path blank for the generated default tone, "
            f"kept in {default_earcon_directory()}. A replaced sound rebuilds "
            "the tracks that use it, from the cached audio."
        )

        description.setWordWrap(
            True
        )

        self.earcon_edits = {}

        earcon_form = QFormLayout()

        for (
            role,
            label,
        ) in EARCON_LABELS:
            path_edit = QLineEdit(
                self.settings.earcons.get(
                    role,
                    "",
                )
            )

            path_edit.setPlaceholderText(
                "Generated default tone"
            )

            self.earcon_edits[
                role
            ] = path_edit

            earcon_form.addRow(
                f"{label}:",
                path_edit,
            )

        self.speech_plan_layout.addSpacing(
            18
        )

        self.speech_plan_layout.addWidget(
            description
        )

        self.speech_plan_layout.addLayout(
            earcon_form
        )

    def build_earcons(
        self,
    ):
        """Build earcons; a named file must exist when the settings are saved."""

        earcons = {}

        for (
            role,
            path_edit,
        ) in self.earcon_edits.items():
            path = path_edit.text().strip()

            if (
                path
                and not Path(
                    path
                ).is_file()
            ):
                raise ValueError(
                    f'The {role} earcon file was not found: "{path}".'
                )

            earcons[
                role
            ] = path

        return earcons

    def add_tempo_profile_controls(
        self,
    ):
        """Add the tempo table: one plain row per preset's profile."""

        description = QLabel(
            "<b>Tempo profiles</b><br>A plan names a profile; a name not "
            "listed here uses the default row. A proportional pause is scale "
            "x pause factor x the length of what was just said, kept between "
            "the minimum and the maximum. The section pause is used at section "
            "boundaries. A changed rate regenerates audio; every other column "
            "only rebuilds the track from the cached audio."
        )

        description.setWordWrap(
            True
        )

        self.tempo_table = QTableWidget(
            0,
            len(
                TEMPO_COLUMNS
            ),
        )

        self.tempo_table.setHorizontalHeaderLabels(
            [
                column[0]
                for column in TEMPO_COLUMNS
            ]
        )

        self.tempo_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        self.tempo_table.verticalHeader().setVisible(
            False
        )

        self.tempo_table.setMinimumHeight(
            260
        )

        self.fill_tempo_table(
            self.settings.tempo_profiles
        )

        add_button = QPushButton(
            "Add Profile"
        )

        qconnect(
            add_button.clicked,
            self.add_tempo_profile_row,
        )

        reset_button = QPushButton(
            "Reset Table to Defaults"
        )

        qconnect(
            reset_button.clicked,
            lambda _checked=False: self.fill_tempo_table(
                DEFAULT_TEMPO_PROFILES
            ),
        )

        button_layout = QHBoxLayout()

        button_layout.addWidget(
            add_button
        )

        button_layout.addWidget(
            reset_button
        )

        button_layout.addStretch()

        self.speech_plan_layout.addSpacing(
            18
        )

        self.speech_plan_layout.addWidget(
            description
        )

        self.speech_plan_layout.addWidget(
            self.tempo_table
        )

        self.speech_plan_layout.addLayout(
            button_layout
        )

    def fill_tempo_table(
        self,
        tempo_profiles,
    ):
        self.tempo_table.setRowCount(
            0
        )

        for (
            name,
            fields,
        ) in tempo_profiles.items():
            self.add_tempo_profile_row(
                name=name,
                fields=fields,
            )

    def add_tempo_profile_row(
        self,
        _checked=False,
        name="",
        fields=None,
    ):
        """Add one row; a new row starts from the default profile's numbers."""

        if fields is None:
            fields = DEFAULT_TEMPO_PROFILES[
                "default"
            ]

        row = self.tempo_table.rowCount()

        self.tempo_table.insertRow(
            row
        )

        for (
            column,
            (
                _heading,
                field_name,
                _convert,
            ),
        ) in enumerate(
            TEMPO_COLUMNS
        ):
            self.tempo_table.setItem(
                row,
                column,
                QTableWidgetItem(
                    name
                    if field_name is None
                    else str(
                        fields[
                            field_name
                        ]
                    )
                ),
            )

    def build_tempo_profiles(
        self,
    ):
        """Build tempo_profiles from the table; a row with no name is dropped."""

        tempo_profiles = {}

        for row in range(
            self.tempo_table.rowCount()
        ):
            name = self.tempo_table.item(
                row,
                0,
            ).text().strip()

            if not name:
                continue

            fields = {}

            for (
                column,
                (
                    heading,
                    field_name,
                    convert,
                ),
            ) in enumerate(
                TEMPO_COLUMNS
            ):
                if field_name is None:
                    continue

                text = self.tempo_table.item(
                    row,
                    column,
                ).text().strip()

                try:
                    fields[
                        field_name
                    ] = convert(
                        text
                    )

                except ValueError:
                    raise ValueError(
                        f'Tempo profile "{name}": {heading} is not a '
                        f'number ("{text}").'
                    ) from None

            tempo_profiles[
                name
            ] = fields

        return tempo_profiles

    def add_role_voice_controls(
        self,
        form_layout,
        language_code,
        language_name,
        voice_role,
    ):
        """Add the provider and voice pickers for one role-voice slot."""

        slot = self.settings.get_role_voice(
            language_code,
            voice_role,
        )

        provider_combo = QComboBox()
        voice_combo = QComboBox()

        controls = {
            "provider": provider_combo,
            "voice": voice_combo,
            "edge_voice": (
                slot[
                    "voice"
                ]
                if slot[
                    "provider"
                ]
                == "edge"
                else DEFAULT_ROLE_VOICES[
                    language_code
                ][
                    voice_role
                ][
                    "voice"
                ]
            ),
        }

        self.role_voice_controls[
            (
                language_code,
                voice_role,
            )
        ] = controls

        self.populate_role_voice_providers(
            controls,
            slot[
                "provider"
            ],
        )

        self.populate_role_voice_combo(
            controls
        )

        qconnect(
            provider_combo.currentIndexChanged,
            lambda _index, slot_controls=controls: (
                self.populate_role_voice_combo(
                    slot_controls
                )
            ),
        )

        slot_layout = QHBoxLayout()

        slot_layout.addWidget(
            provider_combo
        )

        slot_layout.addWidget(
            voice_combo,
            1,
        )

        form_layout.addRow(
            f"{language_name} {voice_role}:",
            slot_layout,
        )

    def current_provider_chain(
        self,
    ):
        """The provider ids currently typed in the Providers tab."""

        return [
            provider_id.strip().lower()
            for provider_id in self.provider_chain_edit.text().split(
                ","
            )
            if provider_id.strip().lower()
            in PROVIDER_IDS
        ]

    def populate_role_voice_providers(
        self,
        controls,
        current_provider,
    ):
        """
        Offer the enabled providers. A slot already on a provider that is not
        enabled keeps it, marked; such a slot uses the chain instead.
        """

        combo = controls[
            "provider"
        ]

        enabled = self.current_provider_chain()

        combo.blockSignals(
            True
        )

        combo.clear()

        for provider_id in enabled:
            combo.addItem(
                provider_id,
                provider_id,
            )

        if current_provider not in enabled:
            combo.addItem(
                f"{current_provider} (not enabled)",
                current_provider,
            )

        combo.setCurrentIndex(
            combo.findData(
                current_provider
            )
        )

        combo.blockSignals(
            False
        )

    def refresh_role_voice_providers(
        self,
    ):
        """Follow edits to the provider order."""

        for controls in self.role_voice_controls.values():
            self.populate_role_voice_providers(
                controls,
                controls[
                    "provider"
                ].currentData(),
            )

    def populate_role_voice_combo(
        self,
        controls,
    ):
        """Fill one slot's voice picker for the provider it is on."""

        combo = controls[
            "voice"
        ]

        previous_voice = combo.currentData()

        if previous_voice:
            controls[
                "edge_voice"
            ] = previous_voice

        combo.clear()

        if controls[
            "provider"
        ].currentData() != "edge":
            combo.addItem(
                "(the voice set on the Providers tab)",
                "",
            )

            combo.setEnabled(
                False
            )

            return

        combo.setEnabled(
            True
        )

        catalogue = (
            self.voice_manager.get_all_voices()
            if self.voices_available
            else []
        )

        self.fill_voice_combo(
            combo,
            role_voice_choices(
                catalogue,
                controls[
                    "edge_voice"
                ],
            ),
            controls[
                "edge_voice"
            ],
        )

    def build_role_voices(
        self,
    ):
        """Build role_voices from the dialog's four slots."""

        role_voices = {}

        for (
            (
                language_code,
                voice_role,
            ),
            controls,
        ) in self.role_voice_controls.items():
            role_voices.setdefault(
                language_code,
                {},
            )[
                voice_role
            ] = {
                "provider": controls[
                    "provider"
                ].currentData(),
                "voice": controls[
                    "voice"
                ].currentData()
                or "",
            }

        return role_voices

    def build_provider_settings(
        self,
    ):
        """Return (provider_chain, providers) from the provider tab."""

        provider_chain = [
            provider_id.strip().lower()
            for provider_id in self.provider_chain_edit.text().split(
                ","
            )
            if provider_id.strip()
        ]

        unknown = [
            provider_id
            for provider_id in provider_chain
            if provider_id not in PROVIDER_IDS
        ]

        if unknown or not provider_chain:
            raise ValueError(
                "Provider order must list pocket, fish and/or edge, "
                f"separated by commas (not understood: {', '.join(unknown) or 'empty'})."
            )

        providers = {
            provider_id: self.settings.get_provider_settings(
                provider_id
            )
            for provider_id in PROVIDER_IDS
        }

        providers[
            "pocket"
        ][
            "engine_python"
        ] = self.pocket_python_edit.text().strip()

        for (
            language_code,
            clip_edit,
        ) in self.pocket_clip_edits.items():
            providers[
                "pocket"
            ][
                "reference_clips"
            ][
                language_code
            ] = clip_edit.text().strip()

        providers[
            "fish"
        ][
            "model"
        ] = self.fish_model_edit.text().strip()

        for (
            language_code,
            reference_edit,
        ) in self.fish_reference_edits.items():
            providers[
                "fish"
            ][
                "reference_ids"
            ][
                language_code
            ] = reference_edit.text().strip()

        return (
            provider_chain,
            providers,
        )

    def format_file_size(
        self,
        size_bytes,
    ):
        """Format a byte count for display."""

        size = float(
            size_bytes
        )

        for unit in (
            "bytes",
            "KB",
            "MB",
            "GB",
        ):
            if (
                size < 1024
                or unit == "GB"
            ):
                if unit == "bytes":
                    return (
                        f"{int(size):,} {unit}"
                    )

                return (
                    f"{size:,.1f} {unit}"
                )

            size /= 1024

    def update_cache_statistics(
        self,
    ):
        """Refresh the displayed audio-cache statistics."""

        statistics = get_cache_statistics()

        file_count = statistics[
            "file_count"
        ]

        total_size = self.format_file_size(
            statistics[
                "total_size"
            ]
        )

        file_word = (
            "file"
            if file_count == 1
            else "files"
        )

        self.cache_statistics_label.setText(
            f"{file_count:,} cached {file_word} "
            f"({total_size})"
        )

        self.clear_cache_button.setEnabled(
            file_count > 0
        )

    def clear_entire_audio_cache(
        self,
    ):
        """Confirm and clear every cached audio file."""

        statistics = get_cache_statistics()

        if statistics[
            "file_count"
        ] == 0:
            showInfo(
                "The AnkiTTS audio cache is already empty."
            )

            self.update_cache_statistics()

            return

        file_count = statistics[
            "file_count"
        ]

        total_size = self.format_file_size(
            statistics[
                "total_size"
            ]
        )

        confirmed = askUser(
            "Delete the entire AnkiTTS audio cache?\n\n"
            f"This will remove {file_count:,} cached "
            f"files ({total_size}).\n\n"
            "Audio already copied into Anki's media "
            "collection will not be affected."
        )

        if not confirmed:
            return

        removed = clear_audio_cache()

        removed_count = removed[
            "file_count"
        ]

        removed_size = self.format_file_size(
            removed[
                "total_size"
            ]
        )

        self.update_cache_statistics()

        showInfo(
            "The AnkiTTS audio cache was cleared.\n\n"
            f"Removed {removed_count:,} files "
            f"({removed_size})."
        )

    def create_speech_profiles_tab(
        self,
        voices_available,
    ):
        """Create the scrollable speech-profile settings tab."""

        speech_profiles_content = QWidget()

        self.speech_profiles_layout = QFormLayout()

        description = QLabel(
            "Configure the voice, speech rate, pitch, and volume "
            "used for each supported language. Reset buttons "
            "restore only the three modifiers and do not change "
            "the selected voice."
        )

        description.setWordWrap(
            True
        )

        self.speech_profiles_layout.addRow(
            description
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
            "Reset All Modifiers"
        )

        qconnect(
            self.reset_all_profiles_button.clicked,
            self.reset_all_speech_profile_modifiers,
        )

        self.speech_profiles_layout.addRow(
            "",
            self.reset_all_profiles_button,
        )

        speech_profiles_content.setLayout(
            self.speech_profiles_layout
        )

        scroll_area = QScrollArea()

        scroll_area.setWidgetResizable(
            True
        )

        scroll_area.setWidget(
            speech_profiles_content
        )

        self.tab_widget.addTab(
            scroll_area,
            "Speech Profiles",
        )

    def create_field_mappings_tab(
        self,
    ):
        """Create the scrollable field-mapping settings tab."""

        field_mappings_content = QWidget()

        field_mappings_outer_layout = QVBoxLayout()

        description = QLabel(
            "Each mapping connects one Anki text field to one "
            "Anki audio field. Mapping names may be customized "
            "and are used internally to identify generated audio."
        )

        description.setWordWrap(
            True
        )

        self.field_mapping_layout = QFormLayout()

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

        field_mappings_outer_layout.addWidget(
            description
        )

        field_mappings_outer_layout.addLayout(
            self.field_mapping_layout
        )

        field_mappings_outer_layout.addWidget(
            self.add_mapping_button
        )

        field_mappings_outer_layout.addStretch()

        field_mappings_content.setLayout(
            field_mappings_outer_layout
        )

        scroll_area = QScrollArea()

        scroll_area.setWidgetResizable(
            True
        )

        scroll_area.setWidget(
            field_mappings_content
        )

        self.tab_widget.addTab(
            scroll_area,
            "Field Mappings",
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
        choices = []

        if voices_available:
            matching_voices = (
                self.voice_manager.get_voices(
                    language_code
                )
            )

            for voice in matching_voices:
                choices.append(
                    (
                        self.voice_manager.get_display_name(
                            voice
                        ),
                        voice[
                            "ShortName"
                        ],
                    )
                )

        self.fill_voice_combo(
            combo,
            choices,
            current_voice,
        )

    def fill_voice_combo(
        self,
        combo,
        choices,
        current_voice,
    ):
        """The one voice picker: (label, voice) rows, current voice selected."""

        for (
            display_name,
            voice_name,
        ) in choices:
            combo.addItem(
                display_name,
                voice_name,
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

    def populate_speech_profile_combo(
        self,
        combo,
        current_speech_profile,
    ):
        """Populate a field mapping's speech profile selector."""

        for (
            display_name,
            speech_profile,
        ) in SPEECH_PROFILE_OPTIONS.items():
            combo.addItem(
                display_name,
                speech_profile,
            )

        current_index = combo.findData(
            current_speech_profile
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

        self.speech_profiles_layout.addRow(
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

        self.speech_profiles_layout.addRow(
            "Voice:",
            voice_combo,
        )

        self.speech_profiles_layout.addRow(
            "Rate:",
            rate_layout,
        )

        self.speech_profiles_layout.addRow(
            "Pitch:",
            pitch_layout,
        )

        self.speech_profiles_layout.addRow(
            "Volume:",
            volume_layout,
        )

        self.speech_profiles_layout.addRow(
            "",
            reset_button,
        )

        self.speech_profiles_layout.addRow(
            QLabel("")
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

        mapping_heading = QLabel(
            f"<b>{display_name}</b>"
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

        speech_profile_combo = QComboBox()

        self.populate_speech_profile_combo(
            combo=speech_profile_combo,
            current_speech_profile=mapping_definition[
                "speech_profile"
            ],
        )

        mapping_spacer = QLabel("")

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
            "heading": mapping_heading,
            "name": mapping_name_edit,
            "text": text_field_edit,
            "audio": audio_field_edit,
            "speech_profile": speech_profile_combo,
            "remove": remove_button,
            "spacer": mapping_spacer,
        }

        self.field_mapping_layout.addRow(
            mapping_heading
        )

        self.field_mapping_layout.addRow(
            "Mapping name:",
            mapping_name_edit,
        )

        self.field_mapping_layout.addRow(
            "Text field:",
            text_field_edit,
        )

        self.field_mapping_layout.addRow(
            "Audio field:",
            audio_field_edit,
        )

        self.field_mapping_layout.addRow(
            "Speech Profile:",
            speech_profile_combo,
        )

        self.field_mapping_layout.addRow(
            "",
            remove_button,
        )

        self.field_mapping_layout.addRow(
            mapping_spacer
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
                "speech_profile": "auto",
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
            "heading",
            "name",
            "text",
            "audio",
            "speech_profile",
            "remove",
            "spacer",
        ):
            self.field_mapping_layout.removeRow(
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
                "speech_profile": controls[
                    "speech_profile"
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

            (
                config[
                    "provider_chain"
                ],
                config[
                    "providers"
                ],
            ) = self.build_provider_settings()

            config[
                "role_voices"
            ] = self.build_role_voices()

            config[
                "tempo_profiles"
            ] = self.build_tempo_profiles()

            config[
                "earcons"
            ] = self.build_earcons()

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
                "provider_chain": (
                    validated_settings.provider_chain
                ),
                "providers": (
                    validated_settings.providers
                ),
                "role_voices": (
                    validated_settings.role_voices
                ),
                "tempo_profiles": (
                    validated_settings.tempo_profiles
                ),
                "earcons": (
                    validated_settings.earcons
                ),
                "settings_version": SETTINGS_VERSION,
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