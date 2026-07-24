import shutil
from pathlib import Path

from aqt.utils import showWarning

from batch_processor import process_notes
from card_processor import OUTPUT_DIR
from note_mapper import (
    create_job_from_note,
    iter_processed_audio_outputs,
    write_audio_fields,
)
from settings import AppSettings
from stitcher import hide_subprocess_windows


def copy_generated_audio_to_media(
    audio_files,
    media_folder,
    settings,
):
    """Copy generated audio files into Anki media."""

    for (
        _field_name,
        _audio_field,
        filename,
    ) in iter_processed_audio_outputs(
        audio_files,
        settings,
    ):
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

    This processes every configured field mapping.
    """

    note = editor.note

    if note.id:
        note = mw.col.get_note(
            note.id
        )

    try:
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

    except Exception as error:
        showWarning(
            "AnkiTTS could not generate audio for this note:\n\n"
            f"{error}\n\n"
            "The note was not changed."
        )

        return None

    try:
        media_folder = Path(
            mw.col.media.dir()
        )

        copy_generated_audio_to_media(
            audio_files,
            media_folder,
            settings,
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

    except Exception as error:
        showWarning(
            "AnkiTTS generated audio but could not publish it "
            f"to this note:\n\n{error}"
        )

        return None

    return audio_files
