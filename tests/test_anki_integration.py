from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
import json
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


install_aqt_stubs()

from anki_integration import browser as browser_integration
from anki_integration import editor as editor_integration
from rce_contract import RCE_JOB_TYPE


class FakeNote(
    dict
):
    def __init__(
        self,
        note_id,
        fields,
    ):
        super().__init__(
            fields
        )

        self.id = note_id


class FakeAddonManager:
    def __init__(
        self,
        config,
    ):
        self.config = config

    def getConfig(
        self,
        addon_name,
    ):
        return self.config


class FakeMedia:
    def __init__(
        self,
        directory,
    ):
        self.directory = directory

    def dir(
        self,
    ):
        return str(
            self.directory
        )


class FakeCollection:
    def __init__(
        self,
        notes,
        media_directory,
    ):
        self.notes = {
            note.id: note
            for note in notes
        }

        self.media = FakeMedia(
            media_directory
        )

        self.updated_notes = []

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
        self.updated_notes.append(
            note
        )


class FakeMainWindow:
    def __init__(
        self,
        notes,
        media_directory,
        config=None,
    ):
        self.addonManager = FakeAddonManager(
            config
            or {}
        )

        self.col = FakeCollection(
            notes,
            media_directory,
        )


class FakeTable:
    def __init__(
        self,
        note_ids,
    ):
        self.note_ids = note_ids

    def get_selected_note_ids(
        self,
    ):
        return list(
            self.note_ids
        )


class FakeModel:
    def __init__(
        self,
    ):
        self.reset_count = 0

    def reset(
        self,
    ):
        self.reset_count += 1


class FakeBrowser:
    def __init__(
        self,
        note_ids,
    ):
        self.table = FakeTable(
            note_ids
        )

        self.model = FakeModel()


class FakeEditor:
    def __init__(
        self,
        note,
    ):
        self.note = note
        self.load_count = 0

    def loadNoteKeepingFocus(
        self,
    ):
        self.load_count += 1


def create_segment(
    side,
):
    return {
        "sequence": 1,
        "segmentId": f"{side}-segment",
        "cueId": f"{side}-cue",
        "contentNodeId": f"{side}-content",
        "repetitionNumber": 1,
        "repetitionCount": 1,
        "text": (
            "faire"
            if side == "front"
            else "to make"
        ),
        "language": (
            "fr-FR"
            if side == "front"
            else "en-US"
        ),
        "voiceProfileId": "",
        "speakingRate": 1.0,
        "pauseBeforeMilliseconds": 0,
        "pauseAfterMilliseconds": 500,
    }


def create_plan(
    side,
):
    return json.dumps(
        {
            "schemaVersion": 1,
            "side": side,
            "segments": [
                create_segment(
                    side
                )
            ],
        }
    )


def create_rce_note(
    note_id=1,
):
    return FakeNote(
        note_id,
        {
            "Front": "faire",
            "Back": "to make",
            "Front Speech Plan": create_plan(
                "front"
            ),
            "Back Speech Plan": create_plan(
                "back"
            ),
            "Front Audio": (
                "[sound:old-front.mp3]"
            ),
            "Back Audio": (
                "[sound:old-back.mp3]"
            ),
            "Playback Plan": (
                '{"schemaVersion":1}'
            ),
            "Blueprint": "test@1",
            "Theme": "test",
            "RCE Card ID": (
                f"rce-card-{note_id}"
            ),
        },
    )


def create_custom_mapping():
    return {
        "field_mapping": {
            "question": {
                "text": "Question",
                "audio": "Question Audio",
                "speech_profile": "fr",
            }
        }
    }


def create_structured_result(
    front_filename="rce-front.mp3",
    back_filename=None,
):
    return {
        "job_type": RCE_JOB_TYPE,
        "rce_card_id": "rce-card-1",
        "audio_fields": {
            "front": "Front Audio",
            "back": "Back Audio",
        },
        "front": front_filename,
        "front_processed": True,
        "back": back_filename,
        "back_processed": True,
        "statistics": {
            "generated": 1,
            "cached": 0,
            "skipped": 0,
        },
    }


def check_browser_mixed_batch_publication():
    original_process_notes = (
        browser_integration.process_notes
    )

    original_output_dir = (
        browser_integration.OUTPUT_DIR
    )

    original_show_info = (
        browser_integration.showInfo
    )

    original_show_warning = (
        browser_integration.showWarning
    )

    jobs_received = []
    information = []
    warnings = []

    def fake_process_notes(
        jobs,
        settings,
    ):
        jobs_received.extend(
            jobs
        )

        return {
            "processed": 2,
            "statistics": {
                "generated": 2,
                "cached": 0,
                "skipped": 0,
            },
            "results": [
                create_structured_result(),
                {
                    "question": "question.mp3",
                    "question_processed": True,
                    "statistics": {
                        "generated": 1,
                        "cached": 0,
                        "skipped": 0,
                    },
                },
            ],
        }

    try:
        with TemporaryDirectory() as directory:
            root = Path(
                directory
            )

            output_directory = (
                root
                / "output"
            )

            media_directory = (
                root
                / "media"
            )

            output_directory.mkdir()
            media_directory.mkdir()

            (
                output_directory
                / "rce-front.mp3"
            ).write_bytes(
                b"rce"
            )

            (
                output_directory
                / "question.mp3"
            ).write_bytes(
                b"generic"
            )

            rce_note = create_rce_note(
                1
            )

            generic_note = FakeNote(
                2,
                {
                    "Question": "bonjour",
                    "Question Audio": "",
                },
            )

            mw = FakeMainWindow(
                [
                    rce_note,
                    generic_note,
                ],
                media_directory,
                create_custom_mapping(),
            )

            browser = FakeBrowser(
                [
                    1,
                    2,
                ]
            )

            browser_integration.process_notes = (
                fake_process_notes
            )

            browser_integration.OUTPUT_DIR = (
                output_directory
            )

            browser_integration.showInfo = (
                information.append
            )

            browser_integration.showWarning = (
                warnings.append
            )

            browser_integration.process_selected_notes(
                browser,
                mw,
                "AnkiTTS",
            )

            assert len(
                jobs_received
            ) == 2

            assert jobs_received[
                0
            ][
                "job_type"
            ] == RCE_JOB_TYPE

            assert "job_type" not in jobs_received[
                1
            ]

            assert rce_note[
                "Front Audio"
            ] == "[sound:rce-front.mp3]"

            assert rce_note[
                "Back Audio"
            ] == ""

            assert generic_note[
                "Question Audio"
            ] == "[sound:question.mp3]"

            assert (
                media_directory
                / "rce-front.mp3"
            ).read_bytes() == b"rce"

            assert (
                media_directory
                / "question.mp3"
            ).read_bytes() == b"generic"

            assert mw.col.updated_notes == [
                rce_note,
                generic_note,
            ]

            assert browser.model.reset_count == 1
            assert len(
                information
            ) == 1
            assert not warnings

    finally:
        browser_integration.process_notes = (
            original_process_notes
        )

        browser_integration.OUTPUT_DIR = (
            original_output_dir
        )

        browser_integration.showInfo = (
            original_show_info
        )

        browser_integration.showWarning = (
            original_show_warning
        )


def check_browser_invalid_rce_aborts_safely():
    original_process_notes = (
        browser_integration.process_notes
    )

    original_show_warning = (
        browser_integration.showWarning
    )

    warnings = []

    def forbidden_process_notes(
        jobs,
        settings,
    ):
        raise AssertionError(
            "The engine ran for an invalid RCE note."
        )

    try:
        with TemporaryDirectory() as directory:
            root = Path(
                directory
            )

            media_directory = (
                root
                / "media"
            )

            media_directory.mkdir()

            note = create_rce_note()

            del note[
                "Back Speech Plan"
            ]

            original_note = dict(
                note
            )

            mw = FakeMainWindow(
                [
                    note
                ],
                media_directory,
                create_custom_mapping(),
            )

            browser = FakeBrowser(
                [
                    note.id
                ]
            )

            browser_integration.process_notes = (
                forbidden_process_notes
            )

            browser_integration.showWarning = (
                warnings.append
            )

            browser_integration.process_selected_notes(
                browser,
                mw,
                "AnkiTTS",
            )

            assert dict(
                note
            ) == original_note

            assert not mw.col.updated_notes
            assert browser.model.reset_count == 0
            assert len(
                warnings
            ) == 1

            assert (
                "Back Speech Plan"
                in warnings[0]
            )

            assert (
                "No selected notes were changed."
                in warnings[0]
            )

    finally:
        browser_integration.process_notes = (
            original_process_notes
        )

        browser_integration.showWarning = (
            original_show_warning
        )


def check_browser_engine_failure_writes_nothing():
    original_process_notes = (
        browser_integration.process_notes
    )

    original_show_warning = (
        browser_integration.showWarning
    )

    warnings = []

    def failing_process_notes(
        jobs,
        settings,
    ):
        raise RuntimeError(
            "simulated synthesis failure"
        )

    try:
        with TemporaryDirectory() as directory:
            root = Path(
                directory
            )

            media_directory = (
                root
                / "media"
            )

            media_directory.mkdir()

            note = create_rce_note()
            original_note = dict(
                note
            )

            mw = FakeMainWindow(
                [
                    note
                ],
                media_directory,
            )

            browser = FakeBrowser(
                [
                    note.id
                ]
            )

            browser_integration.process_notes = (
                failing_process_notes
            )

            browser_integration.showWarning = (
                warnings.append
            )

            browser_integration.process_selected_notes(
                browser,
                mw,
                "AnkiTTS",
            )

            assert dict(
                note
            ) == original_note

            assert not mw.col.updated_notes
            assert list(
                media_directory.iterdir()
            ) == []

            assert len(
                warnings
            ) == 1

            assert (
                "simulated synthesis failure"
                in warnings[0]
            )

            assert (
                "No selected notes were changed."
                in warnings[0]
            )

    finally:
        browser_integration.process_notes = (
            original_process_notes
        )

        browser_integration.showWarning = (
            original_show_warning
        )


def check_browser_media_failure_writes_no_fields():
    original_process_notes = (
        browser_integration.process_notes
    )

    original_output_dir = (
        browser_integration.OUTPUT_DIR
    )

    original_show_warning = (
        browser_integration.showWarning
    )

    warnings = []

    def fake_process_notes(
        jobs,
        settings,
    ):
        return {
            "processed": 1,
            "statistics": {
                "generated": 1,
                "cached": 0,
                "skipped": 0,
            },
            "results": [
                create_structured_result(
                    front_filename=(
                        "missing-track.mp3"
                    )
                )
            ],
        }

    try:
        with TemporaryDirectory() as directory:
            root = Path(
                directory
            )

            output_directory = (
                root
                / "output"
            )

            media_directory = (
                root
                / "media"
            )

            output_directory.mkdir()
            media_directory.mkdir()

            note = create_rce_note()
            original_note = dict(
                note
            )

            mw = FakeMainWindow(
                [
                    note
                ],
                media_directory,
            )

            browser = FakeBrowser(
                [
                    note.id
                ]
            )

            browser_integration.process_notes = (
                fake_process_notes
            )

            browser_integration.OUTPUT_DIR = (
                output_directory
            )

            browser_integration.showWarning = (
                warnings.append
            )

            browser_integration.process_selected_notes(
                browser,
                mw,
                "AnkiTTS",
            )

            assert dict(
                note
            ) == original_note

            assert not mw.col.updated_notes
            assert len(
                warnings
            ) == 1

            assert (
                "could not copy it into Anki media"
                in warnings[0]
            )

            assert (
                "No selected note fields were changed."
                in warnings[0]
            )

    finally:
        browser_integration.process_notes = (
            original_process_notes
        )

        browser_integration.OUTPUT_DIR = (
            original_output_dir
        )

        browser_integration.showWarning = (
            original_show_warning
        )


def check_editor_structured_publication():
    original_process_notes = (
        editor_integration.process_notes
    )

    original_output_dir = (
        editor_integration.OUTPUT_DIR
    )

    original_show_warning = (
        editor_integration.showWarning
    )

    warnings = []
    jobs_received = []

    def fake_process_notes(
        jobs,
        settings,
    ):
        jobs_received.extend(
            jobs
        )

        return {
            "processed": 1,
            "statistics": {
                "generated": 2,
                "cached": 0,
                "skipped": 0,
            },
            "results": [
                create_structured_result(
                    back_filename=(
                        "rce-back.mp3"
                    )
                )
            ],
        }

    try:
        with TemporaryDirectory() as directory:
            root = Path(
                directory
            )

            output_directory = (
                root
                / "output"
            )

            media_directory = (
                root
                / "media"
            )

            output_directory.mkdir()
            media_directory.mkdir()

            (
                output_directory
                / "rce-front.mp3"
            ).write_bytes(
                b"front"
            )

            (
                output_directory
                / "rce-back.mp3"
            ).write_bytes(
                b"back"
            )

            note = create_rce_note()

            mw = FakeMainWindow(
                [
                    note
                ],
                media_directory,
                create_custom_mapping(),
            )

            editor = FakeEditor(
                note
            )

            editor_integration.process_notes = (
                fake_process_notes
            )

            editor_integration.OUTPUT_DIR = (
                output_directory
            )

            editor_integration.showWarning = (
                warnings.append
            )

            result = (
                editor_integration.process_editor_note(
                    editor,
                    mw,
                    "AnkiTTS",
                )
            )

            assert result is not None

            assert jobs_received[
                0
            ][
                "job_type"
            ] == RCE_JOB_TYPE

            assert note[
                "Front Audio"
            ] == "[sound:rce-front.mp3]"

            assert note[
                "Back Audio"
            ] == "[sound:rce-back.mp3]"

            assert (
                media_directory
                / "rce-front.mp3"
            ).read_bytes() == b"front"

            assert (
                media_directory
                / "rce-back.mp3"
            ).read_bytes() == b"back"

            assert mw.col.updated_notes == [
                note
            ]

            assert editor.note is note
            assert editor.load_count == 1
            assert not warnings

    finally:
        editor_integration.process_notes = (
            original_process_notes
        )

        editor_integration.OUTPUT_DIR = (
            original_output_dir
        )

        editor_integration.showWarning = (
            original_show_warning
        )


def check_editor_failure_is_reported():
    original_process_notes = (
        editor_integration.process_notes
    )

    original_show_warning = (
        editor_integration.showWarning
    )

    warnings = []

    def failing_process_notes(
        jobs,
        settings,
    ):
        raise RuntimeError(
            "simulated editor failure"
        )

    try:
        with TemporaryDirectory() as directory:
            root = Path(
                directory
            )

            media_directory = (
                root
                / "media"
            )

            media_directory.mkdir()

            note = create_rce_note()
            original_note = dict(
                note
            )

            mw = FakeMainWindow(
                [
                    note
                ],
                media_directory,
            )

            editor = FakeEditor(
                note
            )

            editor_integration.process_notes = (
                failing_process_notes
            )

            editor_integration.showWarning = (
                warnings.append
            )

            result = (
                editor_integration.process_editor_note(
                    editor,
                    mw,
                    "AnkiTTS",
                )
            )

            assert result is None

            assert dict(
                note
            ) == original_note

            assert not mw.col.updated_notes
            assert editor.load_count == 0
            assert len(
                warnings
            ) == 1

            assert (
                "simulated editor failure"
                in warnings[0]
            )

            assert (
                "The note was not changed."
                in warnings[0]
            )

    finally:
        editor_integration.process_notes = (
            original_process_notes
        )

        editor_integration.showWarning = (
            original_show_warning
        )


def run():
    checks = [
        check_browser_mixed_batch_publication,
        check_browser_invalid_rce_aborts_safely,
        check_browser_engine_failure_writes_nothing,
        check_browser_media_failure_writes_no_fields,
        check_editor_structured_publication,
        check_editor_failure_is_reported,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
