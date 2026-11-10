import shutil
from pathlib import Path

from aqt.qt import QAction
from aqt.utils import (
    qconnect,
    showInfo,
    showWarning,
)

from ankitts_log import get_logger
from audio_audit import (
    REASON_COPY_FAILED,
    REASON_SYNTHESIS_FAILED,
    AudioAudit,
    audit_job,
    audit_published,
    audit_rejected,
    audit_unfinished,
)
from batch_processor import process_notes
from card_processor import OUTPUT_DIR
from note_mapper import (
    create_job_from_note,
    get_audio_field_destinations,
    get_mapped_field_names,
    is_processable_note,
    iter_processed_audio_outputs,
    write_audio_fields,
)
from rce_contract import (
    RCE_JOB_TYPE,
    RceSpeechPlanRejected,
)
from anki_integration.rce_audio_status import (
    mark_ready_if_managed,
)
from settings import AppSettings
from stitcher import hide_subprocess_windows

logger = get_logger(
    "browser"
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


def format_elapsed_time(
    elapsed_seconds,
):
    """Format measured batch duration for the completion message."""

    if (
        isinstance(
            elapsed_seconds,
            bool,
        )
        or not isinstance(
            elapsed_seconds,
            (
                int,
                float,
            ),
        )
        or elapsed_seconds < 0
    ):
        return None

    if elapsed_seconds < 60:
        return (
            f"{elapsed_seconds:.1f} seconds"
        )

    rounded_seconds = int(
        round(
            elapsed_seconds
        )
    )

    minutes, seconds = divmod(
        rounded_seconds,
        60,
    )

    return (
        f"{minutes}m {seconds}s"
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

    # Item C: every refused plan in the selection is counted, not only the
    # first one the run stops at.
    audit = AudioAudit()

    first_failure = None

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
            if isinstance(
                error,
                RceSpeechPlanRejected,
            ):
                audit_rejected(
                    audit,
                    note_id,
                    error.sides,
                )

            if first_failure is None:
                first_failure = (
                    note_id,
                    error,
                )

            continue

        compatible_notes.append(
            note
        )

        jobs.append(
            job
        )

        audit_job(
            audit,
            note_id,
            job,
        )

    if first_failure is not None:
        failed_note_id, error = first_failure

        # Nothing ran, so only the refused plans are reported.
        refused = AudioAudit(
            rejected=audit.rejected
        )

        return _failure(
            "AnkiTTS cannot process selected note "
            f"{failed_note_id}:\n\n{error}\n\n"
            "No selected notes were changed."
            + _audit_suffix(
                refused
            ),
            show_messages,
            refused,
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
        # The run is all-or-nothing: the note that failed, and every note
        # after it, got no audio. Only the note that failed is named.
        failed_index = getattr(
            error,
            "job_index",
            None,
        )

        if failed_index is not None:
            audit_unfinished(
                audit,
                compatible_notes[
                    failed_index
                ].id,
                jobs[
                    failed_index
                ],
                REASON_SYNTHESIS_FAILED,
            )

        return _failure(
            "AnkiTTS audio generation failed:\n\n"
            f"{error}\n\n"
            "No selected notes were changed."
            + _audit_suffix(
                audit
            ),
            show_messages,
            audit,
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
        for note, job in zip(
            compatible_notes,
            jobs,
        ):
            audit_unfinished(
                audit,
                note.id,
                job,
                REASON_COPY_FAILED,
            )

        return _failure(
            "AnkiTTS generated audio but could not copy it "
            f"into Anki media:\n\n{error}\n\n"
            "No selected note fields were changed."
            + _audit_suffix(
                audit
            ),
            show_messages,
            audit,
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

    # Item C, the net under "never silent": what each audited side ended with,
    # read back from the result, Anki's media folder and the note itself.
    try:
        for note, job, audio_files in zip(
            compatible_notes,
            jobs,
            batch_result[
                "results"
            ],
        ):
            if job.get(
                "job_type"
            ) != RCE_JOB_TYPE:
                continue

            audit_published(
                audit,
                note.id,
                job,
                audio_files,
                note,
                media_folder,
                get_audio_field_destinations(
                    audio_files,
                    settings,
                ),
            )

    except Exception as error:
        # The audit is a check on the run, never a reason to fail it.
        logger.warning(
            "The audio audit could not be completed: %s",
            type(
                error
            ).__name__,
        )

    if not audit.is_clean:
        logger.warning(
            audit.log_line()
        )

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

    elapsed_time = format_elapsed_time(
        batch_result.get(
            "elapsed_seconds"
        )
    )

    if elapsed_time is not None:
        message_lines.append(
            f"Elapsed time: {elapsed_time}"
        )

    if skipped_segments:
        message_lines.append(
            f"Skipped segments: {skipped_segments}"
        )

    if skipped_note_types:
        message_lines.append(
            f"Incompatible notes skipped: {skipped_note_types}"
        )

    # The audit's line is never left out: quiet when nothing is silent, a
    # banner when anything is.
    message_lines.append(
        ""
    )

    message_lines.extend(
        audit.lines()
    )

    message = "\n".join(
        message_lines
    )

    if show_messages:
        # A nonzero audit is a warning, not an information box.
        (
            showWarning
            if not audit.is_clean
            else showInfo
        )(
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
        "audit": audit.counts(),
        "audit_alarm": not audit.is_clean,
        "audit_message": audit.message(),
    }


def _audit_suffix(
    audit,
):
    """The audit's lines for the end of a failure message; none if clean."""

    if audit is None or audit.is_clean:
        return ""

    return (
        "\n\n"
        + audit.message()
    )


def _failure(
    message,
    show_messages,
    audit=None,
):
    if show_messages:
        showWarning(
            message
        )

    result = {
        "success": False,
        "message": message,
    }

    if audit is not None and not audit.is_clean:
        logger.warning(
            audit.log_line()
        )

        result[
            "audit"
        ] = audit.counts()

        result[
            "audit_alarm"
        ] = True

        result[
            "audit_message"
        ] = audit.message()

    return result


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
