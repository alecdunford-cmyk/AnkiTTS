import shutil
from pathlib import Path

from batch_processor import process_notes
from card_processor import OUTPUT_DIR
from note_mapper import (
    create_job_from_note,
    write_audio_fields,
)
from settings import AppSettings
from stitcher import hide_subprocess_windows


def copy_generated_audio_to_media(
    audio_files,
    media_folder,
):
    """Copy generated front and back audio files into Anki media."""

    for side in (
        "front",
        "back",
    ):
        filename = audio_files.get(
            side
        )

        if not filename:
            continue

        shutil.copy(
            OUTPUT_DIR / filename,
            media_folder / filename,
        )


def process_editor_note(
    editor,
    mw,
    addon_name,
):
    """
    Explicitly regenerate audio for the current editor note.

    Unlike batch generation, this always processes both configured sides.
    """

    note = editor.note

    if note.id:
        note = mw.col.get_note(
            note.id
        )

    config = (
        mw.addonManager.getConfig(
            addon_name
        )
        or {}
    )

    settings = AppSettings.from_dict(
        config
    )

    job = create_job_from_note(
        note,
        settings,
        generate_front=True,
        generate_back=True,
    )

    with hide_subprocess_windows():
        batch_result = process_notes(
            [
                job
            ],
            settings=settings,
        )

    audio_files = batch_result[
        "results"
    ][0]

    media_folder = Path(
        mw.col.media.dir()
    )

    copy_generated_audio_to_media(
        audio_files,
        media_folder,
    )

    write_audio_fields(
        note,
        audio_files,
        settings,
    )

    if note.id:
        mw.col.update_note(
            note
        )

    editor.note = note
    editor.loadNoteKeepingFocus()

    return audio_files