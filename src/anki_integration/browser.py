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
from note_mapper import create_note_job
from settings import AppSettings
from stitcher import hide_subprocess_windows


REQUIRED_FIELDS = (
    "Front",
    "Back",
    "Front Audio",
    "Back Audio",
)


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


def has_required_fields(note):
    return all(
        field_name in note
        for field_name in REQUIRED_FIELDS
    )


def field_has_audio(
    note,
    field_name,
):
    return bool(
        note[field_name].strip()
    )


def copy_audio_to_media(
    note,
    audio_files,
    media_folder,
):
    if audio_files.get(
        "front_processed",
        True,
    ):
        front_filename = audio_files[
            "front"
        ]

        if front_filename:
            shutil.copy(
                OUTPUT_DIR / front_filename,
                media_folder / front_filename,
            )

            note["Front Audio"] = (
                f"[sound:{front_filename}]"
            )
        else:
            note["Front Audio"] = ""

    if audio_files.get(
        "back_processed",
        True,
    ):
        back_filename = audio_files[
            "back"
        ]

        if back_filename:
            shutil.copy(
                OUTPUT_DIR / back_filename,
                media_folder / back_filename,
            )

            note["Back Audio"] = (
                f"[sound:{back_filename}]"
            )
        else:
            note["Back Audio"] = ""


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
    already_complete = 0

    for note_id in note_ids:
        note = mw.col.get_note(
            note_id
        )

        if not has_required_fields(
            note
        ):
            skipped_note_types += 1
            continue

        generate_front = not field_has_audio(
            note,
            "Front Audio",
        )

        generate_back = not field_has_audio(
            note,
            "Back Audio",
        )

        if not (
            generate_front
            or generate_back
        ):
            already_complete += 1
            continue

        compatible_notes.append(
            note
        )

        jobs.append(
            create_note_job(
                front=note["Front"],
                back=note["Back"],
                generate_front=generate_front,
                generate_back=generate_back,
            )
        )

    if not jobs:
        if already_complete:
            showInfo(
                "All selected compatible notes already have audio."
            )
        else:
            showWarning(
                "None of the selected notes contain all four required fields:\n\n"
                "Front\n"
                "Back\n"
                "Front Audio\n"
                "Back Audio"
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
        copy_audio_to_media(
            note,
            audio_files,
            media_folder,
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

    if already_complete:
        message_lines.append(
            f"Already complete: {already_complete}"
        )

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