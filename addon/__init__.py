import shutil
import sys
from pathlib import Path

from aqt import gui_hooks, mw
from aqt.qt import QAction
from aqt.utils import qconnect, showInfo


ADDON_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ADDON_DIR.parent

LIB_PATH = ADDON_DIR / "libs"
ENGINE_PATH = PROJECT_DIR / "src"

sys.path.append(
    str(LIB_PATH)
)

sys.path.append(
    str(ENGINE_PATH)
)

from .settings_dialog import show_settings_dialog


def get_field_index(note, field_name):
    field_names = [
        field["name"]
        for field in note.note_type()["flds"]
    ]

    if field_name not in field_names:
        raise ValueError(
            f'Required field "{field_name}" was not found.'
        )

    return field_names.index(field_name)


def tts_button(editor):
    from card_processor import OUTPUT_DIR, process_card
    from settings import AppSettings
    from stitcher import hide_subprocess_windows

    note = editor.note

    front_index = get_field_index(
        note,
        "Front"
    )

    back_index = get_field_index(
        note,
        "Back"
    )

    front_audio_index = get_field_index(
        note,
        "Front Audio"
    )

    back_audio_index = get_field_index(
        note,
        "Back Audio"
    )

    front = note.fields[front_index]
    back = note.fields[back_index]

    config = mw.addonManager.getConfig(__name__) or {}

    settings = AppSettings.from_dict(config)

    print("DEBUG FRONT:")
    print(repr(front))

    print("DEBUG BACK:")
    print(repr(back))

    with hide_subprocess_windows():
        audio_files = process_card(
            front=front,
            back=back,
            settings=settings,
        )

    media_folder = Path(
        mw.col.media.dir()
    )

    front_filename = audio_files["front"]
    back_filename = audio_files["back"]

    if front_filename:
        front_audio_path = (
            OUTPUT_DIR / front_filename
        )

        shutil.copy(
            front_audio_path,
            media_folder / front_filename
        )

        note.fields[front_audio_index] = (
            f"[sound:{front_filename}]"
        )
    else:
        note.fields[front_audio_index] = ""

    if back_filename:
        back_audio_path = (
            OUTPUT_DIR / back_filename
        )

        shutil.copy(
            back_audio_path,
            media_folder / back_filename
        )

        note.fields[back_audio_index] = (
            f"[sound:{back_filename}]"
        )
    else:
        note.fields[back_audio_index] = ""

    editor.loadNoteKeepingFocus()

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
        "\n".join(message_lines)
    )


def add_tts_button(buttons, editor):
    button = editor.addButton(
        None,
        "generate_tts_audio",
        tts_button,
        tip="Generate TTS Audio",
        label="TTS",
    )

    buttons.append(button)


gui_hooks.editor_did_init_buttons.append(
    add_tts_button
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