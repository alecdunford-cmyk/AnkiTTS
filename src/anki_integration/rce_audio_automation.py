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


IMMEDIATE_AUDIO_QUERY = (
    f"tag:{RCE_AUDIO_PENDING_TAG} "
    f"tag:{RCE_AUDIO_IMMEDIATE_TAG}"
)

PENDING_AUDIO_QUERY = (
    f"tag:{RCE_AUDIO_PENDING_TAG}"
)

COLLECTION_NOT_OPEN_ERROR = (
    "CollectionNotOpen"
)


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

    def suspend_polling(
        self,
    ):
        self.polling_suspended = True

    def resume_polling(
        self,
    ):
        self.polling_suspended = False

    def poll_immediate_requests(
        self,
    ):
        if (
            self.busy
            or self.polling_suspended
            or self.mw.col is None
        ):
            return

        try:
            note_ids = find_note_ids(
                self.mw.col,
                IMMEDIATE_AUDIO_QUERY,
            )

        except InvalidInput as error:
            if not is_collection_not_open_error(
                error
            ):
                raise

            return

        if not note_ids:
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

        if (
            self.polling_suspended
            or self.mw.col is None
        ):
            showWarning(
                "Open an Anki collection before generating queued "
                "RCE audio."
            )
            return

        note_ids = find_note_ids(
            self.mw.col,
            PENDING_AUDIO_QUERY,
        )

        if not note_ids:
            showInfo(
                "No RCE cards are currently queued for AnkiTTS."
            )
            return

        self._process(
            note_ids,
            show_completion=True,
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
    _set_status(
        mw,
        note_ids,
        [
            RCE_AUDIO_PENDING_TAG,
            RCE_AUDIO_PROCESSING_TAG,
        ],
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
