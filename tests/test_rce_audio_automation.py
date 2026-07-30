from __future__ import annotations

from types import ModuleType
import sys


def install_aqt_stubs():
    if "aqt" in sys.modules:
        return

    aqt_module = ModuleType(
        "aqt"
    )

    qt_module = ModuleType(
        "aqt.qt"
    )

    utils_module = ModuleType(
        "aqt.utils"
    )

    class QAction:
        pass

    qt_module.QAction = QAction
    utils_module.qconnect = (
        lambda *args, **kwargs: None
    )
    utils_module.showInfo = (
        lambda *args, **kwargs: None
    )
    utils_module.showWarning = (
        lambda *args, **kwargs: None
    )

    sys.modules[
        "aqt"
    ] = aqt_module

    sys.modules[
        "aqt.qt"
    ] = qt_module

    sys.modules[
        "aqt.utils"
    ] = utils_module


def install_anki_stubs():
    try:
        __import__(
            "anki.errors"
        )

    except ImportError:
        pass

    else:
        return

    anki_module = sys.modules.get(
        "anki",
        ModuleType(
            "anki"
        ),
    )

    errors_module = ModuleType(
        "anki.errors"
    )

    class InvalidInput(
        Exception
    ):
        pass

    errors_module.InvalidInput = (
        InvalidInput
    )

    sys.modules[
        "anki"
    ] = anki_module

    sys.modules[
        "anki.errors"
    ] = errors_module


install_aqt_stubs()
install_anki_stubs()

from anki_integration import (
    rce_audio_automation as automation,
)
from anki_integration.rce_audio_status import (
    RCE_AUDIO_FAILED_TAG,
    RCE_AUDIO_IMMEDIATE_TAG,
    RCE_AUDIO_PENDING_TAG,
    RCE_AUDIO_PROCESSING_TAG,
    RCE_AUDIO_READY_TAG,
    mark_ready_if_managed,
    set_audio_status,
)


class FakeNote(
    dict
):
    def __init__(
        self,
        note_id,
        tags,
    ):
        super().__init__()
        self.id = note_id
        self.tags = list(
            tags
        )


class FakeCollection:
    def __init__(
        self,
        notes,
    ):
        self.notes = {
            note.id: note
            for note in notes
        }

        self.updated = []

    def get_note(
        self,
        note_id,
    ):
        return self.notes[
            note_id
        ]

    def update_note(
        self,
        note,
    ):
        self.updated.append(
            (
                note.id,
                tuple(
                    note.tags
                ),
            )
        )

    def find_notes(
        self,
        query,
    ):
        required = [
            token[
                len("tag:"):
            ]
            for token in query.split()
            if token.startswith(
                "tag:"
            )
        ]

        return [
            note.id
            for note in self.notes.values()
            if all(
                tag in note.tags
                for tag in required
            )
        ]


class CountingCollection(
    FakeCollection
):
    def __init__(
        self,
        notes,
    ):
        super().__init__(
            notes
        )

        self.find_calls = 0

    def find_notes(
        self,
        query,
    ):
        self.find_calls += 1

        return super().find_notes(
            query
        )


class RecoveringCollection(
    CountingCollection
):
    def __init__(
        self,
        notes,
    ):
        super().__init__(
            notes
        )

        self.collection_available = False

    def find_notes(
        self,
        query,
    ):
        self.find_calls += 1

        if not self.collection_available:
            raise automation.InvalidInput(
                "CollectionNotOpen"
            )

        return FakeCollection.find_notes(
            self,
            query,
        )


class FailingCollection(
    CountingCollection
):
    def __init__(
        self,
        error,
    ):
        super().__init__(
            []
        )

        self.error = error

    def find_notes(
        self,
        query,
    ):
        self.find_calls += 1

        raise self.error


class FakeMainWindow:
    def __init__(
        self,
        notes,
    ):
        self.col = FakeCollection(
            notes
        )


def check_poll_does_nothing_without_a_collection():
    mw = FakeMainWindow(
        []
    )

    mw.col = None

    controller = (
        automation.RceAudioAutomationController(
            mw,
            "AnkiTTS",
        )
    )

    controller.poll_immediate_requests()

    assert controller.polling_suspended
    assert not controller.busy


def check_lifecycle_suspends_and_resumes_polling():
    mw = FakeMainWindow(
        []
    )

    mw.col = CountingCollection(
        []
    )

    controller = (
        automation.RceAudioAutomationController(
            mw,
            "AnkiTTS",
        )
    )

    controller.suspend_polling()
    controller.poll_immediate_requests()

    assert mw.col.find_calls == 0

    controller.resume_polling()
    controller.poll_immediate_requests()

    assert mw.col.find_calls == 1
    assert not controller.polling_suspended


def check_collection_not_open_is_ignored_and_polling_recovers():
    mw = FakeMainWindow(
        []
    )

    mw.col = RecoveringCollection(
        []
    )

    controller = (
        automation.RceAudioAutomationController(
            mw,
            "AnkiTTS",
        )
    )

    controller.poll_immediate_requests()

    assert mw.col.find_calls == 1
    assert not controller.busy
    assert not controller.polling_suspended

    mw.col.collection_available = True

    controller.poll_immediate_requests()

    assert mw.col.find_calls == 2
    assert not controller.busy


def check_unrelated_search_errors_remain_visible():
    errors = [
        automation.InvalidInput(
            "DifferentInvalidInput"
        ),
        RuntimeError(
            "simulated search failure"
        ),
    ]

    for expected_error in errors:
        mw = FakeMainWindow(
            []
        )

        mw.col = FailingCollection(
            expected_error
        )

        controller = (
            automation.RceAudioAutomationController(
                mw,
                "AnkiTTS",
            )
        )

        try:
            controller.poll_immediate_requests()

        except Exception as error:
            assert error is expected_error

        else:
            raise AssertionError(
                "An unrelated search error was hidden."
            )


def check_status_replacement_preserves_unrelated_tags():
    note = FakeNote(
        1,
        [
            "personal",
            "rce-workflow::contextual-acquisition",
            RCE_AUDIO_PENDING_TAG,
            RCE_AUDIO_FAILED_TAG,
        ],
    )

    set_audio_status(
        note,
        [
            RCE_AUDIO_PENDING_TAG,
            RCE_AUDIO_PROCESSING_TAG,
        ],
    )

    assert note.tags == [
        "personal",
        "rce-workflow::contextual-acquisition",
        RCE_AUDIO_PENDING_TAG,
        RCE_AUDIO_PROCESSING_TAG,
    ]

    mark_ready_if_managed(
        note
    )

    assert note.tags == [
        "personal",
        "rce-workflow::contextual-acquisition",
        RCE_AUDIO_READY_TAG,
    ]


def check_immediate_request_reuses_batch_path_and_becomes_ready():
    note = FakeNote(
        1,
        [
            "personal",
            RCE_AUDIO_PENDING_TAG,
            RCE_AUDIO_IMMEDIATE_TAG,
        ],
    )

    mw = FakeMainWindow(
        [
            note,
        ]
    )

    original_process_note_ids = (
        automation.process_note_ids
    )

    original_show_info = (
        automation.showInfo
    )

    original_show_warning = (
        automation.showWarning
    )

    processed = []
    information = []
    warnings = []

    def fake_process_note_ids(
        note_ids,
        passed_mw,
        addon_name,
        reset_callback=None,
        show_messages=True,
    ):
        assert passed_mw is mw
        assert addon_name == "AnkiTTS"
        assert note.tags == [
            "personal",
            RCE_AUDIO_PENDING_TAG,
            RCE_AUDIO_PROCESSING_TAG,
        ]

        processed.extend(
            note_ids
        )

        mark_ready_if_managed(
            note
        )

        passed_mw.col.update_note(
            note
        )

        return {
            "success": True,
            "message": "complete",
        }

    try:
        automation.process_note_ids = (
            fake_process_note_ids
        )

        automation.showInfo = (
            information.append
        )

        automation.showWarning = (
            warnings.append
        )

        controller = (
            automation.RceAudioAutomationController(
                mw,
                "AnkiTTS",
            )
        )

        controller.poll_immediate_requests()

        assert processed == [
            1,
        ]

        assert note.tags == [
            "personal",
            RCE_AUDIO_READY_TAG,
        ]

        assert not information
        assert not warnings
        assert not controller.busy

    finally:
        automation.process_note_ids = (
            original_process_note_ids
        )

        automation.showInfo = (
            original_show_info
        )

        automation.showWarning = (
            original_show_warning
        )


def check_failed_immediate_request_remains_pending():
    note = FakeNote(
        1,
        [
            "personal",
            RCE_AUDIO_PENDING_TAG,
            RCE_AUDIO_IMMEDIATE_TAG,
        ],
    )

    mw = FakeMainWindow(
        [
            note,
        ]
    )

    original_process_note_ids = (
        automation.process_note_ids
    )

    original_show_warning = (
        automation.showWarning
    )

    warnings = []

    try:
        automation.process_note_ids = (
            lambda *args, **kwargs: {
                "success": False,
                "message": "simulated failure",
            }
        )

        automation.showWarning = (
            warnings.append
        )

        controller = (
            automation.RceAudioAutomationController(
                mw,
                "AnkiTTS",
            )
        )

        controller.poll_immediate_requests()

        assert note.tags == [
            "personal",
            RCE_AUDIO_PENDING_TAG,
            RCE_AUDIO_FAILED_TAG,
        ]

        assert not warnings

    finally:
        automation.process_note_ids = (
            original_process_note_ids
        )

        automation.showWarning = (
            original_show_warning
        )


def check_unpublished_success_is_converted_to_recoverable_failure():
    note = FakeNote(
        1,
        [
            "personal",
            RCE_AUDIO_PENDING_TAG,
            RCE_AUDIO_IMMEDIATE_TAG,
        ],
    )

    mw = FakeMainWindow(
        [
            note,
        ]
    )

    original_process_note_ids = (
        automation.process_note_ids
    )

    try:
        automation.process_note_ids = (
            lambda *args, **kwargs: {
                "success": True,
                "message": "completed with one incompatible note",
            }
        )

        controller = (
            automation.RceAudioAutomationController(
                mw,
                "AnkiTTS",
            )
        )

        controller.poll_immediate_requests()

        assert note.tags == [
            "personal",
            RCE_AUDIO_PENDING_TAG,
            RCE_AUDIO_FAILED_TAG,
        ]

    finally:
        automation.process_note_ids = (
            original_process_note_ids
        )


def check_manual_pending_action_handles_empty_queue():
    mw = FakeMainWindow(
        []
    )

    original_show_info = (
        automation.showInfo
    )

    information = []

    try:
        automation.showInfo = (
            information.append
        )

        controller = (
            automation.RceAudioAutomationController(
                mw,
                "AnkiTTS",
            )
        )

        controller.process_pending_requests()

        assert information == [
            "No RCE cards are currently queued for AnkiTTS.",
        ]

    finally:
        automation.showInfo = (
            original_show_info
        )


def run():
    checks = [
        check_poll_does_nothing_without_a_collection,
        check_lifecycle_suspends_and_resumes_polling,
        check_collection_not_open_is_ignored_and_polling_recovers,
        check_unrelated_search_errors_remain_visible,
        check_status_replacement_preserves_unrelated_tags,
        check_immediate_request_reuses_batch_path_and_becomes_ready,
        check_failed_immediate_request_remains_pending,
        check_unpublished_success_is_converted_to_recoverable_failure,
        check_manual_pending_action_handles_empty_queue,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
