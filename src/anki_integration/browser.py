import shutil
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from aqt.qt import QAction
from aqt.utils import (
    qconnect,
    showInfo,
    showWarning,
)

from ankitts_log import get_logger
from anki_integration.ui import call_on_main
from audio_audit import (
    REASON_COPY_FAILED,
    REASON_SYNTHESIS_FAILED,
    AudioAudit,
    audit_job,
    audit_published,
    audit_rejected,
    audit_unfinished,
)
from batch_processor import (
    RunCancelled,
    process_notes,
)
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

# Where a background run stopped, for the failure message.
STAGE_SYNTHESIS = "synthesis"
STAGE_COPY = "copy"

ALREADY_RUNNING_MESSAGE = (
    "AnkiTTS is already generating audio. Wait for that run to finish, "
    "then try again."
)

CANCELLED_MESSAGE = (
    "The audio run was stopped because the Anki collection was closing. "
    "The notes stay queued."
)

COLLECTION_CHANGED_MESSAGE = (
    "The Anki collection changed while the audio was generated, so it was "
    "not published. The notes stay queued."
)

# One generation run at a time, whoever started it (the browser menu, the
# automation's poll, Tools > Generate Pending RCE Audio). Read and written on
# the main thread only.
_run_in_flight = False


def run_in_flight():
    """Whether a generation run is between its start and its publication."""

    return _run_in_flight


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
    """
    The browser menu's action: a run Alec starts by hand. The long work is
    done off the main thread (CA-82); the result box he gets when it ends
    carries the audit's lines, and there is no second box.
    """

    note_ids = get_selected_note_ids(
        browser
    )

    if not note_ids:
        _warn(
            mw,
            "Select one or more notes in the Browse window first.",
        )
        return {
            "success": False,
            "message": (
                "No notes were selected."
            ),
        }

    start_note_run(
        note_ids,
        mw,
        addon_name,
        on_finished=lambda outcome: None,
        reset_callback=(
            browser.model.reset
        ),
        show_messages=True,
    )


@dataclass
class PreparedRun:
    """What the main thread worked out before the long part starts."""

    settings: object
    media_folder: Path
    compatible_notes: list
    jobs: list
    audit: AudioAudit
    skipped_note_types: int


@dataclass
class GeneratedRun:
    """What the long part came back with: a batch result, or why not."""

    batch_result: dict | None = None
    error: BaseException | None = None
    stage: str | None = None


def prepare_run(
    note_ids,
    mw,
    addon_name,
    show_messages=True,
):
    """
    The first part of a run, on the main thread: settings, the notes, their
    jobs, the audit's first counts. Returns a PreparedRun, or the failure
    outcome (a dict) when the run cannot start.
    """

    if not note_ids:
        return _failure(
            "No notes were supplied for AnkiTTS processing.",
            show_messages,
            mw=mw,
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
            mw=mw,
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
            mw=mw,
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
            mw=mw,
        )

    return PreparedRun(
        settings=settings,
        media_folder=media_folder,
        compatible_notes=compatible_notes,
        jobs=jobs,
        audit=audit,
        skipped_note_types=skipped_note_types,
    )


def generate_run(
    prepared,
    should_cancel=None,
):
    """
    The long part of a run: synthesis, stitching, copying into Anki's media.

    It touches no Anki collection and no Qt object, so it may run on a
    background thread, and it never raises: a failure comes back in the
    GeneratedRun, for the main thread to report.
    """

    try:
        arguments = {}

        if should_cancel is not None:
            arguments[
                "should_cancel"
            ] = should_cancel

        with hide_subprocess_windows():
            batch_result = process_notes(
                prepared.jobs,
                settings=prepared.settings,
                # A note whose audio step timed out fails alone and the run
                # goes on (CA-93).
                continue_after_timeout=True,
                **arguments,
            )

    except Exception as error:
        return GeneratedRun(
            error=error,
            stage=STAGE_SYNTHESIS,
        )

    try:
        for audio_files in batch_result[
            "results"
        ]:
            if audio_files is None:
                # A note that timed out: nothing to copy.
                continue

            copy_generated_audio_to_media(
                audio_files,
                prepared.media_folder,
                prepared.settings,
            )

    except Exception as error:
        return GeneratedRun(
            error=error,
            stage=STAGE_COPY,
        )

    return GeneratedRun(
        batch_result=batch_result,
    )


def publish_run(
    prepared,
    generated,
    mw,
    reset_callback=None,
    show_messages=True,
):
    """
    The last part of a run, on the main thread: write the audio fields, tag
    the notes ready, audit what each side ended with, report.
    """

    settings = prepared.settings
    media_folder = prepared.media_folder
    compatible_notes = prepared.compatible_notes
    jobs = prepared.jobs
    audit = prepared.audit
    skipped_note_types = prepared.skipped_note_types

    if generated.error is not None:
        error = generated.error

        if isinstance(
            error,
            RunCancelled,
        ):
            # Stopped on purpose, between notes, because the collection is
            # closing: not a failure, nothing was written, no box (CA-85).
            return {
                "success": False,
                "cancelled": True,
                "message": CANCELLED_MESSAGE,
            }

        if generated.stage == STAGE_COPY:
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
                mw=mw,
            )

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
            mw=mw,
        )

    batch_result = generated.batch_result

    # Notes whose audio step timed out (CA-93): not written, not tagged ready,
    # reported; the automation leaves them pending without the immediate
    # request (mark_failed), so only the menu command retries them.
    timed_out = list(
        batch_result.get(
            "timed_out",
        )
        or ()
    )

    timed_out_indexes = {
        index
        for index, _step in timed_out
    }

    try:
        # The notes are read again here: the run took minutes, and a note
        # Alec edited meanwhile is written back as he left it, plus audio.
        notes = [
            mw.col.get_note(
                note.id
            )
            for note in compatible_notes
        ]

        for index, (note, audio_files) in enumerate(
            zip(
                notes,
                batch_result["results"],
            )
        ):
            if index in timed_out_indexes:
                continue

            write_audio_fields(
                note,
                audio_files,
                settings,
            )

        for index, note in enumerate(
            notes
        ):
            if index in timed_out_indexes:
                continue

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
            mw=mw,
        )

    compatible_notes = notes

    if reset_callback is not None:
        # The Browse window can be gone by now (the run took minutes): the
        # notes are published either way, so a refresh that fails is only
        # logged.
        try:
            reset_callback()

        except Exception as error:
            logger.warning(
                "The Browse window could not be refreshed: %s",
                type(
                    error
                ).__name__,
            )

    # Item C, the net under "never silent": what each audited side ended with,
    # read back from the result, Anki's media folder and the note itself.
    try:
        for index, (note, job, audio_files) in enumerate(
            zip(
                compatible_notes,
                jobs,
                batch_result[
                    "results"
                ],
            )
        ):
            if job.get(
                "job_type"
            ) != RCE_JOB_TYPE:
                continue

            if index in timed_out_indexes:
                # Its spoken sides got no audio: silent, counted (CA-71 (3)).
                audit_unfinished(
                    audit,
                    note.id,
                    job,
                    REASON_SYNTHESIS_FAILED,
                )

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
        f"Notes processed: {len(compatible_notes) - len(timed_out)}",
        f"Generated segments: {generated_count}",
        f"Reused from cache: {cached_count}",
    ]

    if timed_out:
        # The step only: no card text, no path, no process output.
        steps = sorted(
            {
                step
                for _index, step in timed_out
            }
        )

        message_lines.append(
            f"Notes not generated: {len(timed_out)} (an audio step did not "
            f"finish in time: {', '.join(steps)}). They stay queued."
        )

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
        # A nonzero audit is a warning, not an information box. This is the
        # one box of a run Alec started by hand; it carries the audit.
        (
            _warn
            if not audit.is_clean
            else _info
        )(
            mw,
            message,
        )

    return {
        "success": True,
        "message": message,
        "processed": len(
            compatible_notes
        )
        - len(
            timed_out
        ),
        "timed_out": len(
            timed_out
        ),
        "skipped_note_types": (
            skipped_note_types
        ),
        "statistics": statistics,
        "audit": audit.counts(),
        "audit_alarm": not audit.is_clean,
        "audit_message": audit.message(),
        "audit_notice": audit.notice(),
    }


def process_note_ids(
    note_ids,
    mw,
    addon_name,
    reset_callback=None,
    show_messages=True,
):
    """
    Process an explicit ordered set of Anki note IDs, start to finish, on the
    calling thread.

    The same three parts as start_note_run, one after another: the editor's
    button and the checks use this; the browser action and the RCE automation
    use start_note_run, which does the long part off the main thread.
    """

    prepared = prepare_run(
        note_ids,
        mw,
        addon_name,
        show_messages,
    )

    if isinstance(
        prepared,
        dict,
    ):
        return prepared

    return publish_run(
        prepared,
        generate_run(
            prepared
        ),
        mw,
        reset_callback,
        show_messages,
    )


def start_note_run(
    note_ids,
    mw,
    addon_name,
    on_finished,
    reset_callback=None,
    show_messages=True,
    should_cancel=None,
):
    """
    Process note IDs without holding Anki's main thread (CA-82).

    The notes are read and the jobs built here, on the main thread; synthesis,
    stitching and copying run on a background thread (`mw.taskman`); the audio
    fields are written, the notes tagged ready and the result shown back on the
    main thread. on_finished(outcome) is called once, on the main thread, with
    the same outcome dict process_note_ids returns. One run at a time: a run
    asked for while another is in flight is refused with a failure outcome
    marked "busy".
    """

    global _run_in_flight

    if _run_in_flight:
        outcome = _failure(
            ALREADY_RUNNING_MESSAGE,
            show_messages,
            mw=mw,
        )

        outcome[
            "busy"
        ] = True

        on_finished(
            outcome
        )

        return

    prepared = prepare_run(
        note_ids,
        mw,
        addon_name,
        show_messages,
    )

    if isinstance(
        prepared,
        dict,
    ):
        on_finished(
            prepared
        )

        return

    _run_in_flight = True

    collection = getattr(
        mw,
        "col",
        None,
    )

    started_at = perf_counter()

    logger.info(
        "Audio run started: %d note(s).",
        len(
            prepared.jobs
        ),
    )

    def task():
        return generate_run(
            prepared,
            should_cancel,
        )

    def done(
        future,
    ):
        """On the main thread, whatever the task did."""

        global _run_in_flight

        try:
            try:
                generated = future.result()

            except BaseException as error:
                generated = GeneratedRun(
                    error=error,
                    stage=STAGE_SYNTHESIS,
                )

            try:
                if (
                    getattr(
                        mw,
                        "col",
                        None,
                    )
                    is not collection
                ):
                    # Another profile, or none: writing now could land in the
                    # wrong collection (note ids repeat across profiles).
                    outcome = {
                        "success": False,
                        "cancelled": True,
                        "message": COLLECTION_CHANGED_MESSAGE,
                    }

                else:
                    outcome = publish_run(
                        prepared,
                        generated,
                        mw,
                        reset_callback,
                        show_messages,
                    )

            except Exception as error:
                logger.warning(
                    "The audio run could not be published: %s",
                    type(
                        error
                    ).__name__,
                )

                outcome = _failure(
                    "AnkiTTS could not publish the audio run: "
                    f"{type(error).__name__}.",
                    show_messages,
                    mw=mw,
                )

        finally:
            _run_in_flight = False

        counts = outcome.get(
            "audit"
        ) or {}

        logger.info(
            "Audio run finished: %s in %.1f s; audit %s silent, "
            "%s empty, %s rejected.",
            "success"
            if outcome.get(
                "success"
            )
            else "failure",
            perf_counter()
            - started_at,
            counts.get(
                "silent",
                0,
            ),
            counts.get(
                "empty",
                0,
            ),
            counts.get(
                "rejected",
                0,
            ),
        )

        on_finished(
            outcome
        )

    try:
        _run_in_background(
            mw,
            task,
            done,
        )

    except Exception as error:
        _run_in_flight = False

        on_finished(
            _failure(
                "AnkiTTS could not start the audio run: "
                f"{type(error).__name__}.",
                show_messages,
                mw=mw,
            )
        )


def _run_in_background(
    mw,
    task,
    done,
):
    """
    Hand the task to Anki's task manager; done(future) is called back on the
    main thread. The task uses no collection, so Anki is not told it does.
    Without a task manager the task runs here, with a warning in the log.
    """

    taskman = getattr(
        mw,
        "taskman",
        None,
    )

    if taskman is None:
        logger.warning(
            "Anki's task manager is not available; the audio run executes "
            "on the calling thread."
        )

        future = Future()

        try:
            future.set_result(
                task()
            )

        except BaseException as error:
            future.set_exception(
                error
            )

        done(
            future
        )

        return

    taskman.run_in_background(
        task,
        done,
        uses_collection=False,
    )


def _info(
    mw,
    text,
):
    call_on_main(
        mw,
        lambda: showInfo(
            text
        ),
    )


def _warn(
    mw,
    text,
):
    call_on_main(
        mw,
        lambda: showWarning(
            text
        ),
    )


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
    mw=None,
):
    if show_messages:
        _warn(
            mw,
            message,
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

        result[
            "audit_notice"
        ] = audit.notice()

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
