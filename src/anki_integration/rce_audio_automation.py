from anki.errors import InvalidInput

from aqt.utils import (
    showInfo,
    showWarning,
)

from anki_integration.browser import (
    process_note_ids,
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
from structured_audio import (
    cleanup_orphaned_temporary_audio_files,
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


class RceAudioPollingLifecycle:
    """Keep the polling timer aligned with Anki's collection lifecycle."""

    def __init__(
        self,
        controller,
        timer,
    ):
        self.controller = controller
        self.timer = timer

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


class RceAudioAutomationController:
    """
    Execute RCE audio requests through the established AnkiTTS batch path.

    The controller is called only from Anki's main thread. Its busy guard
    prevents timer polling and a manual queued run from overlapping.
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

    def suspend_polling(
        self,
    ):
        self.polling_suspended = True

    def resume_polling(
        self,
    ):
        self.polling_suspended = (
            self.mw.col is None
        )

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
        if self.busy:
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
        self.busy = True

        try:
            mark_processing(
                self.mw,
                note_ids,
            )

            outcome = process_note_ids(
                note_ids,
                self.mw,
                self.addon_name,
                show_messages=False,
            )

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

                    outcome = {
                        "success": False,
                        "message": (
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
                        ),
                    }

                    if show_completion:
                        showWarning(
                            "RCE audio generation was incomplete:\n\n"
                            f"{outcome['message']}\n\n"
                            "The affected cards can be retried with "
                            "Tools > Generate Pending RCE Audio."
                        )

                    return outcome

                if show_completion:
                    showInfo(
                        outcome.get(
                            "message",
                            "RCE audio generation completed.",
                        )
                    )

                return outcome

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

            return outcome

        except Exception as error:
            if is_collection_not_open_error(
                error
            ):
                if show_completion:
                    showWarning(
                        COLLECTION_UNAVAILABLE_MESSAGE
                    )

                return {
                    "success": False,
                    "message": (
                        COLLECTION_UNAVAILABLE_MESSAGE
                    ),
                }

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

            return {
                "success": False,
                "message": str(
                    error
                ),
            }

        finally:
            self.busy = False


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
