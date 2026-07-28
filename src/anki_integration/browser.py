import shutil
from pathlib import Path

from aqt.qt import QAction
from aqt.utils import (
    qconnect,
    showInfo,
    showWarning,
)

from batch_processor import process_notes
from card_processor import OUTPUT_DIR
from note_mapper import (
    create_job_from_note,
    get_mapped_field_names,
    is_processable_note,
    iter_processed_audio_outputs,
    write_audio_fields,
)
from anki_integration.rce_audio_status import (
    mark_ready_if_managed,
)
from settings import AppSettings
from stitcher import hide_subprocess_windows


def get_selected_note_ids(browser):
    table = getattr(
        browser,
        "table",
        None,
    )

    if (
        table is not None
        and hasattr(
            table,
            "get_selected_note_ids",
        )
    ):
        return list(
            table.get_selected_note_ids()
        )

    if hasattr(
        browser,
        "selectedNotes",
    ):
        return list(
            browser.selectedNotes()
        )

    return []


def copy_generated_audio_to_media(
    audio_files,
    media_folder,
    settings,
):
    """Copy processed audio files into Anki media."""

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


def format_required_fields_message(
    settings,
):
    """Format the configured field names for user-facing warnings."""

    field_names = get_mapped_field_names(
        settings
    )

    return "\n".join(
        field_names.values()
    )


def process_selected_notes(
    browser,
    mw,
    addon_name,
):
    note_ids = get_selected_note_ids(
        browser
    )

    if not note_ids:
        showWarning(
            "Select one or more notes in the Browse window first."
        )
        return {
            "success": False,
            "message": (
                "No notes were selected."
            ),
        }

    return process_note_ids(
        note_ids,
        mw,
        addon_name,
        reset_callback=(
            browser.model.reset
        ),
        show_messages=True,
    )


def process_note_ids(
    note_ids,
    mw,
    addon_name,
    reset_callback=None,
    show_messages=True,
):
    """
    Process an explicit ordered set of Anki note IDs.

    Browser selection, queued RCE generation, and immediate RCE automation
    all enter this single transactional publication path.
    """

    if not note_ids:
        return _failure(
            "No notes were supplied for AnkiTTS processing.",
            show_messages,
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

    except Exception as error:
        return _failure(
            "AnkiTTS settings are invalid:\n\n"
            f"{error}",
            show_messages,
        )

    media_folder = Path(
        mw.col.media.dir()
    )

    compatible_notes = []
    jobs = []

    skipped_note_types = 0

    for note_id in note_ids:
        note = mw.col.get_note(
            note_id
        )

        if not is_processable_note(
            note,
            settings,
        ):
            skipped_note_types += 1
            continue

        try:
            job = create_job_from_note(
                note,
                settings,
            )

        except Exception as error:
            return _failure(
                "AnkiTTS cannot process selected note "
                f"{note_id}:\n\n{error}\n\n"
                "No selected notes were changed.",
                show_messages,
            )

        compatible_notes.append(
            note
        )

        jobs.append(
            job
        )

    if not jobs:
        required_fields = (
            format_required_fields_message(
                settings
            )
        )

        return _failure(
            "None of the selected notes contain all "
            "configured AnkiTTS fields:\n\n"
            f"{required_fields}",
            show_messages,
        )

    try:
        with hide_subprocess_windows():
            batch_result = process_notes(
                jobs,
                settings=settings,
            )

    except Exception as error:
        return _failure(
            "AnkiTTS audio generation failed:\n\n"
            f"{error}\n\n"
            "No selected notes were changed.",
            show_messages,
        )

    try:
        for audio_files in batch_result[
            "results"
        ]:
            copy_generated_audio_to_media(
                audio_files,
                media_folder,
                settings,
            )

    except Exception as error:
        return _failure(
            "AnkiTTS generated audio but could not copy it "
            f"into Anki media:\n\n{error}\n\n"
            "No selected note fields were changed.",
            show_messages,
        )

    try:
        for note, audio_files in zip(
            compatible_notes,
            batch_result["results"],
        ):
            write_audio_fields(
                note,
                audio_files,
                settings,
            )

        for note in compatible_notes:
            mark_ready_if_managed(
                note
            )

            mw.col.update_note(
                note
            )

    except Exception as error:
        return _failure(
            "AnkiTTS could not update all selected notes:\n\n"
            f"{error}",
            show_messages,
        )

    if reset_callback is not None:
        reset_callback()

    statistics = batch_result.get(
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

    skipped_segments = statistics.get(
        "skipped",
        0,
    )

    message_lines = [
        "Batch TTS complete!",
        "",
        f"Notes processed: {len(compatible_notes)}",
        f"Generated segments: {generated_count}",
        f"Reused from cache: {cached_count}",
    ]

    if skipped_segments:
        message_lines.append(
            f"Skipped segments: {skipped_segments}"
        )

    if skipped_note_types:
        message_lines.append(
            f"Incompatible notes skipped: {skipped_note_types}"
        )

    message = "\n".join(
        message_lines
    )

    if show_messages:
        showInfo(
            message
        )

    return {
        "success": True,
        "message": message,
        "processed": len(
            compatible_notes
        ),
        "skipped_note_types": (
            skipped_note_types
        ),
        "statistics": statistics,
    }


def _failure(
    message,
    show_messages,
):
    if show_messages:
        showWarning(
            message
        )

    return {
        "success": False,
        "message": message,
    }


def add_browser_menu_action(
    browser,
    mw,
    addon_name,
):
    action = QAction(
        "Generate AnkiTTS Audio for Selected Notes",
        browser,
    )

    qconnect(
        action.triggered,
        lambda: process_selected_notes(
            browser,
            mw,
            addon_name,
        ),
    )

    browser.form.menu_Notes.addAction(
        action
    )

    browser.ankitts_generate_action = action
