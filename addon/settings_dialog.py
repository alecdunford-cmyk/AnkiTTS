from aqt import mw
from aqt.qt import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)
from aqt.utils import qconnect, showInfo

from settings import AppSettings


LANGUAGES = {
    "French": "fr",
    "English": "en",
    "Japanese": "ja",
}


class SettingsDialog(QDialog):
    """Graphical settings window for AnkiTTS."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("AnkiTTS Settings")
        self.setMinimumWidth(360)

        config = mw.addonManager.getConfig(__package__) or {}
        self.settings = AppSettings.from_dict(config)

        self.front_language_combo = QComboBox()

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

        description = QLabel(
            "Choose the language used to pronounce the front "
            "of each card."
        )
        description.setWordWrap(True)

        form_layout = QFormLayout()
        form_layout.addRow(
            "Front language:",
            self.front_language_combo,
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

    def save_settings(self):
        language_code = self.front_language_combo.currentData()

        config = mw.addonManager.getConfig(__package__) or {}

        config["front_language"] = language_code

        try:
            validated_settings = AppSettings.from_dict(config)
        except ValueError as error:
            showInfo(
                f"Could not save AnkiTTS settings:\n\n{error}"
            )
            return

        config.update(
            {
                "front_language": validated_settings.front_language,
                "voices": validated_settings.voices,
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