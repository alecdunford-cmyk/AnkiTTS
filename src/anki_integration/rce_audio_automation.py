from anki.errors import InvalidInput

from aqt.utils import (
    showInfo,
    showWarning,
)

from ankitts_log import get_logger
from anki_integration.browser import (
    run_in_flight,
    start_note_run,
)
from anki_integration.rce_audio_status import (
    RCE_AUDIO_FAILED_TAG,
    RCE_AUDIO_IMMEDIATE_TAG,
    RCE_AUDIO_PENDING_TAG,
    RCE_AUDIO_PROCESSING_TAG,
    RCE_AUDIO_READY_TAG,
    get_note_tags,
    set_audio_status,
)
from anki_integration.ui import (
    show_notice,
)
from structured_audio import (
    cleanup_orphaned_temporary_audio_files,
)

logger = get_logger(
    "automation"
)


IMMEDIATE_AUDIO_QUERY = (
    f"tag:{RCE_AUDIO_PENDING_TAG} "
    f"tag:{RCE_AUDIO_IMMEDIATE_TAG}"
)

PENDING_AUDIO_QUERY = (
    f"tag:{RCE_AUDIO_PENDING_TAG}"
)

PROCESSING_AUDIO_QUERY = (
    f"tag:{RCE_AUDIO_PROCESSING_TAG}"
)

COLLECTION_NOT_OPEN_ERROR = (
    "CollectionNotOpen"
)

COLLECTION_UNAVAILABLE_MESSAGE = (
    "The Anki collection became temporarily unavailable. "
    "The affected cards remain queued and can be retried after "
    "the collection is open again."
)

# How long after a collection opens before the add-on resumes pending audio.
# Nothing the add-on does may happen inside the hook that announces the
# collection: the main window has not finished opening (CA-84).
RESUME_DELAY_MS = 3000


class RceAudioPollingLifecycle:
    """Keep the polling timer aligned with Anki's collection lifecycle."""

    def __init__(
        self,
        controller,
        timer,
        schedule=None,
    ):
        self.controller = controller
        self.timer = timer
        # schedule(delay_milliseconds, callable): Qt's QTimer.singleShot in
        # Anki. Without one, the resume runs at once (the checks that do not
        # test deferral).
        self.schedule = schedule

    def suspend(
        self,
        *_args,
    ):
        self.controller.suspend_polling()
        self.timer.stop()

    def resume(
        self,
        *_args,
    ):
        if not self.controller.resume_polling():
            self.timer.stop()
            return False

        if not self.controller.recover_after_restart():
            self.timer.stop()
            return False

        is_active = getattr(
            self.timer,
            "isActive",
            None,
        )

        if (
            is_active is None
            or not is_active()
        ):
            self.timer.start()

        return True

    def resume_later(
        self,
        *_args,
    ):
        """
        What the Anki hooks call. It only schedules the resume: the work (a
        search, tag writes, a file clean-up) never runs inside the hook, where
        a profile is still opening.
        """

        if self.schedule is None:
            return self.resume_safely()

        try:
            self.schedule(
                RESUME_DELAY_MS,
                self.resume_safely,
            )

        except Exception as error:
            logger.warning(
                "Scheduling the RCE audio resume failed: %s",
                type(
                    error
                ).__name__,
            )

        return None

    def resume_safely(
        self,
    ):
        """Resume, and log a failure instead of raising it into Anki."""

        try:
            return self.resume()

        except Exception as error:
            logger.warning(
                "Resuming the RCE audio polling failed: %s",
                type(
                    error
                ).__name__,
            )

            return False


class RceAudioAutomationController:
    """
    Execute RCE audio requests through the established AnkiTTS batch path.

    The controller is called only from Anki's main thread, and so is every
    callback it is given. The long part of a run executes on a background
    thread (CA-82); `busy` stays set from the start of a run until its result
    has been handled, so timer polling and a manual queued run cannot overlap.
    """

    def __init__(
        self,
        mw,
        addon_name,
    ):
        self.mw = mw
        self.addon_name = addon_name
        self.busy = False
        self.polling_suspended = (
            self.mw.col is None
        )
        self.recovered_collection = None
        # Set when the collection closes: a run in flight stops between notes
        # instead of holding Anki open (CA-85).
        self.cancel_requested = False

    def suspend_polling(
        self,
    ):
        self.polling_suspended = True
        self.cancel_requested = True

    def resume_polling(
        self,
    ):
        self.polling_suspended = (
            self.mw.col is None
        )

        if not self.polling_suspended:
            self.cancel_requested = False

        return not self.polling_suspended

    def recover_after_restart(
        self,
    ):
        collection = self._available_collection()

        if collection is None:
            return False

        if self.recovered_collection is collection:
            return True

        try:
            processing_note_ids = find_note_ids(
                collection,
                PROCESSING_AUDIO_QUERY,
            )

        except Exception as error:
            if not is_collection_not_open_error(
                error
            ):
                raise

            return False

        if not self._collection_is_current(
            collection
        ):
            return False

        if processing_note_ids:
            mark_interrupted_processing(
                self.mw,
                processing_note_ids,
            )

        cleanup_orphaned_temporary_audio_files()
        self.recovered_collection = collection
        return True

    def poll_immediate_requests(
        self,
    ):
        if run_in_flight():
            return

        collection = self._available_collection()

        if collection is None:
            return

        try:
            note_ids = find_note_ids(
                collection,
                IMMEDIATE_AUDIO_QUERY,
            )

        except Exception as error:
            if not is_collection_not_open_error(
                error
            ):
                raise

            return

        if (
            not note_ids
            or not self._collection_is_current(
                collection
            )
        ):
            return

        self._process(
            note_ids,
            show_completion=False,
        )

    def process_pending_requests(
        self,
    ):
        if self.busy or run_in_flight():
            showInfo(
                "AnkiTTS is already processing an RCE audio request."
            )
            return

        collection = self._available_collection()

        if collection is None:
            showWarning(
                "Open an Anki collection before generating queued "
                "RCE audio."
            )
            return

        try:
            note_ids = find_note_ids(
                collection,
                PENDING_AUDIO_QUERY,
            )

        except Exception as error:
            if not is_collection_not_open_error(
                error
            ):
                raise

            showWarning(
                COLLECTION_UNAVAILABLE_MESSAGE
            )
            return

        if not self._collection_is_current(
            collection
        ):
            showWarning(
                COLLECTION_UNAVAILABLE_MESSAGE
            )
            return

        if not note_ids:
            showInfo(
                "No RCE cards are currently queued for AnkiTTS."
            )
            return

        self._process(
            note_ids,
            show_completion=True,
        )

    def _available_collection(
        self,
    ):
        if (
            self.busy
            or self.polling_suspended
        ):
            return None

        return self.mw.col

    def _collection_is_current(
        self,
        collection,
    ):
        return (
            not self.polling_suspended
            and collection is not None
            and self.mw.col is collection
        )

    def _process(
        self,
        note_ids,
        show_completion,
    ):
        """
        Start a run. It returns as soon as the long part is handed to a
        background thread; _finish handles the result on the main thread.
        """

        self.busy = True

        collection = self.mw.col

        logger.info(
            "RCE audio run requested for %d note(s) (%s).",
            len(
                note_ids
            ),
            "by hand"
            if show_completion
            else "unattended",
        )

        try:
            mark_processing(
                self.mw,
                note_ids,
            )

            start_note_run(
                note_ids,
                self.mw,
                self.addon_name,
                on_finished=(
                    lambda outcome: self._finish(
                        note_ids,
                        show_completion,
                        outcome,
                        collection,
                    )
                ),
                show_messages=False,
                should_cancel=(
                    lambda: self.cancel_requested
                ),
            )

        except Exception as error:
            self._finish_with_error(
                note_ids,
                show_completion,
                error,
            )

    def _finish(
        self,
        note_ids,
        show_completion,
        outcome,
        collection,
    ):
        """On the main thread, once per run: the outcome of the long part."""

        try:
            self._conclude(
                note_ids,
                show_completion,
                outcome,
                collection,
            )

        except Exception as error:
            self._finish_with_error(
                note_ids,
                show_completion,
                error,
            )

        finally:
            self.busy = False

    def _conclude(
        self,
        note_ids,
        show_completion,
        outcome,
        collection,
    ):
        # Never silent (CA-71 (3)), and never a box nobody is watching
        # (CA-83): a run Alec did not start tells him with a notice that
        # closes itself, once, whatever the audit found. A run he started
        # shows the audit in the result box it already has.
        if (
            outcome.get(
                "audit_alarm"
            )
            and not show_completion
        ):
            show_notice(
                self.mw,
                outcome.get(
                    "audit_notice",
                    "AnkiTTS audio audit: a side has no audio. "
                    "See the AnkiTTS log.",
                ),
            )

        if not self._collection_is_current(
            collection
        ):
            # The collection closed or changed while the run was away. The
            # notes keep the tags they had; the next start recovers them.
            return

        if outcome.get(
            "cancelled"
        ) or outcome.get(
            "busy"
        ):
            # Stopped, not failed: the notes stay queued for the next run.
            mark_interrupted_processing(
                self.mw,
                note_ids,
            )

            return

        if outcome.get(
            "success"
        ):
            incomplete_note_ids = [
                note_id
                for note_id in note_ids
                if RCE_AUDIO_READY_TAG not in get_note_tags(
                    self.mw.col.get_note(
                        note_id
                    )
                )
            ]

            if incomplete_note_ids:
                mark_failed(
                    self.mw,
                    incomplete_note_ids,
                )

                if show_completion:
                    message = (
                        outcome.get(
                            "message",
                            "RCE audio generation completed partially.",
                        )
                        + "\n\n"
                        + str(
                            len(
                                incomplete_note_ids
                            )
                        )
                        + " requested RCE note(s) were not "
                        "published and remain pending."
                    )

                    showWarning(
                        "RCE audio generation was incomplete:\n\n"
                        f"{message}\n\n"
                        "The affected cards can be retried with "
                        "Tools > Generate Pending RCE Audio."
                    )

                return

            if show_completion:
                showInfo(
                    outcome.get(
                        "message",
                        "RCE audio generation completed.",
                    )
                )

            return

        mark_failed(
            self.mw,
            note_ids,
        )

        if show_completion:
            showWarning(
                "RCE audio generation failed:\n\n"
                f"{outcome.get('message', 'Unknown failure')}\n\n"
                "The affected cards remain tagged as pending and can "
                "be retried with Tools > Generate Pending RCE Audio."
            )

    def _finish_with_error(
        self,
        note_ids,
        show_completion,
        error,
    ):
        """An exception in starting or concluding a run; busy is released."""

        self.busy = False

        if is_collection_not_open_error(
            error
        ):
            if show_completion:
                showWarning(
                    COLLECTION_UNAVAILABLE_MESSAGE
                )

            return

        # The type only: an exception's text can hold card text.
        logger.warning(
            "RCE audio automation failed: %s",
            type(
                error
            ).__name__,
        )

        try:
            mark_failed(
                self.mw,
                note_ids,
            )
        except Exception:
            pass

        if show_completion:
            showWarning(
                "RCE audio automation failed:\n\n"
                f"{error}\n\n"
                "The cards remain recoverable through the "
                "pending-audio batch workflow."
            )


def is_collection_not_open_error(
    error,
):
    return (
        isinstance(
            error,
            InvalidInput,
        )
        and str(
            error
        ) == COLLECTION_NOT_OPEN_ERROR
    )


def find_note_ids(
    collection,
    query,
):
    """Use the current Anki search API with a compatibility fallback."""

    finder = getattr(
        collection,
        "find_notes",
        None,
    )

    if finder is None:
        finder = getattr(
            collection,
            "findNotes",
            None,
        )

    if finder is None:
        raise RuntimeError(
            "This Anki version does not expose note search to AnkiTTS."
        )

    return list(
        finder(
            query
        )
    )


def mark_processing(
    mw,
    note_ids,
):
    for note_id in note_ids:
        note = mw.col.get_note(
            note_id
        )

        status_tags = [
            RCE_AUDIO_PENDING_TAG,
        ]

        if RCE_AUDIO_IMMEDIATE_TAG in get_note_tags(
            note
        ):
            status_tags.append(
                RCE_AUDIO_IMMEDIATE_TAG
            )

        status_tags.append(
            RCE_AUDIO_PROCESSING_TAG
        )

        set_audio_status(
            note,
            status_tags,
        )

        mw.col.update_note(
            note
        )


def mark_failed(
    mw,
    note_ids,
):
    _set_status(
        mw,
        note_ids,
        [
            RCE_AUDIO_PENDING_TAG,
            RCE_AUDIO_FAILED_TAG,
        ],
    )


def mark_interrupted_processing(
    mw,
    note_ids,
):
    for note_id in note_ids:
        note = mw.col.get_note(
            note_id
        )

        status_tags = [
            RCE_AUDIO_PENDING_TAG,
            RCE_AUDIO_FAILED_TAG,
        ]

        if RCE_AUDIO_IMMEDIATE_TAG in get_note_tags(
            note
        ):
            status_tags.insert(
                1,
                RCE_AUDIO_IMMEDIATE_TAG,
            )

        set_audio_status(
            note,
            status_tags,
        )

        mw.col.update_note(
            note
        )


def _set_status(
    mw,
    note_ids,
    status_tags,
):
    for note_id in note_ids:
        note = mw.col.get_note(
            note_id
        )

        set_audio_status(
            note,
            status_tags,
        )

        mw.col.update_note(
            note
        )
