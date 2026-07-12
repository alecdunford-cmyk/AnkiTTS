import shutil
from pathlib import Path

from batch_processor import process_notes
from card_processor import OUTPUT_DIR
from note_mapper import create_note_job
from settings import AppSettings
from stitcher import hide_subprocess_windows


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


def process_editor_note(
    editor,
    mw,
    addon_name,
):
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

    config = mw.addonManager.getConfig(
        addon_name
    ) or {}

    settings = AppSettings.from_dict(
        config
    )

    with hide_subprocess_windows():
        batch_result = process_notes(
            [
                create_note_job(
                    front,
                    back,
                )
            ],
            settings=settings,
        )

    audio_files = batch_result["results"][0]

    media_folder = Path(
        mw.col.media.dir()
    )

    front_filename = audio_files["front"]
    back_filename = audio_files["back"]

    if front_filename:
        shutil.copy(
            OUTPUT_DIR / front_filename,
            media_folder / front_filename,
        )

        note.fields[front_audio_index] = (
            f"[sound:{front_filename}]"
        )
    else:
        note.fields[front_audio_index] = ""

    if back_filename:
        shutil.copy(
            OUTPUT_DIR / back_filename,
            media_folder / back_filename,
        )

        note.fields[back_audio_index] = (
            f"[sound:{back_filename}]"
        )
    else:
        note.fields[back_audio_index] = ""

    editor.loadNoteKeepingFocus()

    return audio_files