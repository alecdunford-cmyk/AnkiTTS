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
    has_mapped_fields,
    write_audio_fields,
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

    for field_name in settings.field_mapping:
        processed_key = (
            f"{field_name}_processed"
        )

        if not audio_files.get(
            processed_key,
            True,
        ):
            continue

        filename = audio_files.get(
            field_name
        )

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
        return

    config = (
        mw.addonManager.getConfig(
            addon_name
        )
        or {}
    )

    settings = AppSettings.from_dict(
        config
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

        if not has_mapped_fields(
            note,
            settings,
        ):
            skipped_note_types += 1
            continue

        compatible_notes.append(
            note
        )

        jobs.append(
            create_job_from_note(
                note,
                settings,
            )
        )

    if not jobs:
        required_fields = (
            format_required_fields_message(
                settings
            )
        )

        showWarning(
            "None of the selected notes contain all "
            "configured AnkiTTS fields:\n\n"
            f"{required_fields}"
        )

        return

    with hide_subprocess_windows():
        batch_result = process_notes(
            jobs,
            settings=settings,
        )

    for note, audio_files in zip(
        compatible_notes,
        batch_result["results"],
    ):
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

        mw.col.update_note(
            note
        )

    browser.model.reset()

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

    showInfo(
        "\n".join(
            message_lines
        )
    )


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