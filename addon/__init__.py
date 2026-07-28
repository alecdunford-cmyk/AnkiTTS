import sys
from pathlib import Path

from aqt import gui_hooks, mw
from aqt.qt import (
    QAction,
    QTimer,
)
from aqt.utils import qconnect, showInfo


ADDON_DIR = Path(__file__).resolve().parent

if (ADDON_DIR / "src").is_dir():
    ENGINE_PATH = ADDON_DIR / "src"
else:
    ENGINE_PATH = ADDON_DIR.parent / "src"

LIB_PATH = ADDON_DIR / "libs"

if str(LIB_PATH) not in sys.path:
    sys.path.insert(
        0,
        str(LIB_PATH),
    )

if str(ENGINE_PATH) not in sys.path:
    sys.path.insert(
        0,
        str(ENGINE_PATH),
    )

from anki_integration.browser import add_browser_menu_action
from anki_integration.editor import process_editor_note
from anki_integration.rce_audio_automation import (
    RceAudioAutomationController,
)
from .settings_dialog import show_settings_dialog


def tts_button(editor):
    audio_files = process_editor_note(
        editor,
        mw,
        __name__,
    )

    if audio_files is None:
        return

    statistics = audio_files.get(
        "statistics",
        {},
    )

    generated_count = statistics.get(
        "generated",
        0,
    )

    cached_count = statistics.get(
        "cached",
        0,
    )

    skipped_count = statistics.get(
        "skipped",
        0,
    )

    message_lines = [
        "TTS audio added!",
        "",
        f"Generated segments: {generated_count}",
        f"Reused from cache: {cached_count}",
    ]

    if skipped_count:
        message_lines.append(
            f"Skipped segments: {skipped_count}"
        )

    showInfo(
        "\n".join(
            message_lines
        )
    )


def add_tts_button(
    buttons,
    editor,
):
    button = editor.addButton(
        None,
        "generate_tts_audio",
        tts_button,
        tip="Generate TTS Audio",
        label="TTS",
    )

    buttons.append(
        button
    )


def initialize_browser_menu(
    browser,
):
    add_browser_menu_action(
        browser,
        mw,
        __name__,
    )


gui_hooks.editor_did_init_buttons.append(
    add_tts_button
)

gui_hooks.browser_menus_did_init.append(
    initialize_browser_menu
)


settings_action = QAction(
    "AnkiTTS Settings...",
    mw,
)

qconnect(
    settings_action.triggered,
    show_settings_dialog,
)

mw.form.menuTools.addAction(
    settings_action
)


rce_audio_automation = (
    RceAudioAutomationController(
        mw,
        __name__,
    )
)

pending_audio_action = QAction(
    "Generate Pending RCE Audio",
    mw,
)

qconnect(
    pending_audio_action.triggered,
    rce_audio_automation.process_pending_requests,
)

mw.form.menuTools.addAction(
    pending_audio_action
)

rce_audio_timer = QTimer(
    mw
)

rce_audio_timer.setInterval(
    1000
)

qconnect(
    rce_audio_timer.timeout,
    rce_audio_automation.poll_immediate_requests,
)

rce_audio_timer.start()
