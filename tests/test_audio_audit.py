"""
The audio audit (review batch 2, item C; CA-71 (3), "never silent").

After a run, every note whose v2 plan has spoken segments but ended without
audio is reported, with the side and the reason, as counts and note ids and
never a segment's text; a plan with nothing to speak and a plan the validator
refused are counted apart. Notes and ids here are invented; the fake provider
stands where the speech service stands, and no service is called.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.test_anki_integration import (
    FakeMainWindow,
    FakeNote,
    browser_integration,
)
from tests.test_rce_audio_automation import (
    FakeMainWindow as AutomationWindow,
    FakeNote as AutomationNote,
    automation,
    synchronous_run,
)

from anki_integration import ui as ui_module
from anki_integration.rce_audio_status import mark_ready_if_managed

import batch_processor
from audio_audit import (
    EMPTY,
    SPOKEN,
    AudioAudit,
    audit_published,
    side_status,
)
from providers import registry
from speech_plan import parse_speech_plan
import structured_audio
from tests.test_role_voices import (
    RecordingEdge,
    v2_note,
    v2_plan,
    v2_segment,
    with_directories,
)


# Invented sentences; the checks assert none of them reaches a report.
FRONT_TEXT = "le phare du port"
BACK_TEXT = "the harbour light"

SENTENCES = (
    FRONT_TEXT,
    BACK_TEXT,
)


def good_front():
    return [
        v2_segment(
            1,
            FRONT_TEXT,
            "fr-FR",
            "content",
            role="headword",
        )
    ]


def good_back():
    return [
        v2_segment(
            1,
            BACK_TEXT,
            "en-US",
            "content",
            role="gloss",
        )
    ]


def unspoken_back():
    return [
        v2_segment(
            1,
            BACK_TEXT,
            "en-US",
            "content",
            role="gloss",
            spoken=False,
        )
    ]


def make_note(
    note_id,
    front=None,
    back=None,
):
    fields = v2_note(
        good_front()
        if front is None
        else front,
        good_back()
        if back is None
        else back,
    )

    fields[
        "RCE Card ID"
    ] = f"audit-card-{note_id}"

    return FakeNote(
        note_id,
        fields,
    )


def refused_plan(
    side,
):
    """A plan the validator refuses: a role the contract does not have."""

    return v2_plan(
        side,
        [
            v2_segment(
                1,
                FRONT_TEXT
                if side == "front"
                else BACK_TEXT,
                "fr-FR"
                if side == "front"
                else "en-US",
                "content",
                role="nonsense",
            )
        ],
    )


def run_notes(
    notes,
    show_messages=False,
    process_notes=None,
    copy=None,
):
    """
    Run process_note_ids over invented notes with the fake provider and a
    stand-in stitcher. Returns (outcome, dialogs, media folder listing).
    """

    held = {}

    original = {
        name: getattr(
            browser_integration,
            name,
        )
        for name in (
            "OUTPUT_DIR",
            "process_notes",
            "copy_generated_audio_to_media",
            "showInfo",
            "showWarning",
        )
    }

    dialogs = {
        "info": [],
        "warning": [],
    }

    def action():
        registry.set_override_chain(
            [
                RecordingEdge(),
            ]
        )

        browser_integration.OUTPUT_DIR = structured_audio.OUTPUT_DIR
        browser_integration.showInfo = dialogs[
            "info"
        ].append
        browser_integration.showWarning = dialogs[
            "warning"
        ].append

        if process_notes is not None:
            browser_integration.process_notes = process_notes

        if copy is not None:
            browser_integration.copy_generated_audio_to_media = copy

        with TemporaryDirectory() as media:
            mw = FakeMainWindow(
                notes,
                Path(
                    media
                ),
            )

            held[
                "outcome"
            ] = browser_integration.process_note_ids(
                [
                    note.id
                    for note in notes
                ],
                mw,
                "AnkiTTS",
                show_messages=show_messages,
            )

            held[
                "media"
            ] = sorted(
                path.name
                for path in Path(
                    media
                ).iterdir()
            )

    try:
        with_directories(
            action
        )

    finally:
        for (
            name,
            value,
        ) in original.items():
            setattr(
                browser_integration,
                name,
                value,
            )

    return (
        held[
            "outcome"
        ],
        dialogs,
        held[
            "media"
        ],
    )


def assert_no_text(
    *reports,
):
    for report in reports:
        for sentence in SENTENCES:
            assert sentence not in report, "card text in an audit report"


def parsed(
    side,
    segments,
):
    return parse_speech_plan(
        v2_plan(
            side,
            segments,
        ),
        side,
    )


def check_only_sides_with_a_version_2_plan_are_audited():
    assert side_status(
        parsed(
            "front",
            good_front(),
        )
    ) == SPOKEN

    # A plan with no segments, and one whose every segment is unspoken.
    assert side_status(
        parsed(
            "front",
            [],
        )
    ) == EMPTY

    assert side_status(
        parsed(
            "back",
            unspoken_back(),
        )
    ) == EMPTY

    # One spoken segment among unspoken ones is a side with speech.
    assert side_status(
        parsed(
            "back",
            unspoken_back()
            + [
                v2_segment(
                    2,
                    BACK_TEXT,
                    "en-US",
                    "content",
                ),
            ],
        )
    ) == SPOKEN

    # A version 1 plan is not the audit's.
    version_1 = parse_speech_plan(
        json.dumps(
            {
                "schemaVersion": 1,
                "side": "front",
                "segments": [],
            }
        ),
        "front",
    )

    assert side_status(
        version_1
    ) is None

    assert side_status(
        None
    ) is None


def check_a_clean_run_reports_zero_silent_sides():
    outcome, dialogs, media = run_notes(
        [
            make_note(
                101
            ),
            make_note(
                102
            ),
        ],
        show_messages=True,
    )

    assert outcome[
        "success"
    ] is True

    assert outcome[
        "audit"
    ] == {
        "silent": 0,
        "empty": 0,
        "rejected": 0,
    }

    assert outcome[
        "audit_alarm"
    ] is False

    # Quiet: the one line, inside the ordinary information box.
    assert "0 silent sides" in outcome[
        "message"
    ]

    assert "AUDIO AUDIT" not in outcome[
        "message"
    ]

    assert len(
        dialogs[
            "info"
        ]
    ) == 1

    assert dialogs[
        "warning"
    ] == []

    assert len(
        media
    ) == 4

    assert_no_text(
        outcome[
            "message"
        ]
    )


def check_a_run_with_one_silent_side_reports_it():
    real = batch_processor.process_notes

    def losing_a_track(
        jobs,
        settings,
    ):
        """The engine reports success but hands back no back track for 202."""

        batch = real(
            jobs,
            settings,
        )

        batch[
            "results"
        ][
            1
        ][
            "back"
        ] = None

        return batch

    outcome, dialogs, media = run_notes(
        [
            make_note(
                201
            ),
            make_note(
                202
            ),
        ],
        show_messages=True,
        process_notes=losing_a_track,
    )

    assert outcome[
        "audit"
    ] == {
        "silent": 1,
        "empty": 0,
        "rejected": 0,
    }

    assert outcome[
        "audit_alarm"
    ] is True

    message = outcome[
        "message"
    ]

    # Impossible to miss: a banner, the count, the note, the side, the reason.
    assert "*** AUDIO AUDIT: 1 SIDE WITHOUT AUDIO" in message
    assert "1 silent side: note 202 (back: no track was produced)" in message
    assert "0 empty sides" in message
    assert "0 rejected plans" in message

    # The healthy note is not named.
    assert "note 201" not in message

    # A warning, not an information box.
    assert dialogs[
        "info"
    ] == []

    assert len(
        dialogs[
            "warning"
        ]
    ) == 1

    assert_no_text(
        message
    )


def check_the_other_reasons_a_side_can_be_silent():
    job = {
        "speech_plans": {
            "front": parsed(
                "front",
                good_front(),
            ),
            "back": parsed(
                "back",
                good_back(),
            ),
        },
    }

    destinations = {
        "front": "Front Audio",
        "back": "Back Audio",
    }

    with TemporaryDirectory() as directory:
        media = Path(
            directory
        )

        (
            media
            / "front.mp3"
        ).write_bytes(
            b"audio"
        )

        # An empty file is a missing track.
        (
            media
            / "back.mp3"
        ).write_bytes(
            b""
        )

        audit = AudioAudit()

        audit_published(
            audit,
            7,
            job,
            {
                "front": "front.mp3",
                "back": "back.mp3",
            },
            {
                "Front Audio": "[sound:front.mp3]",
                "Back Audio": "[sound:back.mp3]",
            },
            media,
            destinations,
        )

        assert [
            (
                finding.side,
                finding.reason,
            )
            for finding in audit.silent
        ] == [
            (
                "back",
                "the track file is missing from Anki's media folder",
            ),
        ]

        # The track is there but the field does not point at it.
        (
            media
            / "back.mp3"
        ).write_bytes(
            b"audio"
        )

        audit = AudioAudit()

        audit_published(
            audit,
            7,
            job,
            {
                "front": "front.mp3",
                "back": "back.mp3",
            },
            {
                "Front Audio": "[sound:front.mp3]",
                "Back Audio": "",
            },
            media,
            destinations,
        )

        assert [
            (
                finding.side,
                finding.reason,
            )
            for finding in audit.silent
        ] == [
            (
                "back",
                "the audio field is empty",
            ),
        ]

        # Everything where it should be: clean.
        audit = AudioAudit()

        audit_published(
            audit,
            7,
            job,
            {
                "front": "front.mp3",
                "back": "back.mp3",
            },
            {
                "Front Audio": "[sound:front.mp3]",
                "Back Audio": "[sound:back.mp3]",
            },
            media,
            destinations,
        )

        assert audit.is_clean


def check_an_empty_plan_lands_in_the_empty_count():
    outcome, dialogs, _media = run_notes(
        [
            make_note(
                301,
                back=unspoken_back(),
            ),
            make_note(
                302,
                front=[],
            ),
            make_note(
                303
            ),
        ],
        show_messages=True,
    )

    # Reported, not silent: the run itself still succeeds.
    assert outcome[
        "success"
    ] is True

    assert outcome[
        "audit"
    ] == {
        "silent": 0,
        "empty": 2,
        "rejected": 0,
    }

    message = outcome[
        "message"
    ]

    assert "2 empty sides: note 301 (back: the plan has no spoken segment); note 302 (front: the plan has no spoken segment)" in message

    assert "0 silent sides" in message
    assert "note 303" not in message

    assert len(
        dialogs[
            "warning"
        ]
    ) == 1

    assert_no_text(
        message
    )


def check_a_rejected_plan_lands_in_the_rejected_count_and_stops_the_run():
    healthy = make_note(
        401
    )

    back_refused = make_note(
        402
    )

    back_refused[
        "Back Speech Plan"
    ] = refused_plan(
        "back"
    )

    both_refused = make_note(
        403
    )

    both_refused[
        "Front Speech Plan"
    ] = refused_plan(
        "front"
    )

    both_refused[
        "Back Speech Plan"
    ] = refused_plan(
        "back"
    )

    before = dict(
        healthy
    )

    outcome, dialogs, media = run_notes(
        [
            healthy,
            back_refused,
            both_refused,
        ],
        show_messages=True,
    )

    # The run is still all-or-nothing, and nothing was written.
    assert outcome[
        "success"
    ] is False

    assert "No selected notes were changed." in outcome[
        "message"
    ]

    assert media == []

    assert dict(
        healthy
    ) == before

    # But every refused plan is counted, not only the first.
    assert outcome[
        "audit"
    ] == {
        "silent": 0,
        "empty": 0,
        "rejected": 3,
    }

    message = outcome[
        "message"
    ]

    assert "3 rejected plans: note 402 (back: the plan was refused by the validator); note 403 (front: the plan was refused by the validator); note 403 (back: the plan was refused by the validator)" in message

    assert "note 401" not in message

    assert len(
        dialogs[
            "warning"
        ]
    ) == 1

    assert_no_text(
        message
    )


def check_a_failed_synthesis_names_the_note():
    real = structured_audio.process_structured_job

    calls = []

    def failing_on_the_second(
        job,
        settings,
    ):
        calls.append(
            job[
                "rce_card_id"
            ]
        )

        if len(
            calls
        ) == 2:
            raise structured_audio.StructuredAudioProcessingError(
                f"simulated failure for {BACK_TEXT}"
            )

        return real(
            job,
            settings,
        )

    original = batch_processor.process_structured_job

    batch_processor.process_structured_job = failing_on_the_second

    try:
        outcome, _dialogs, media = run_notes(
            [
                make_note(
                    501
                ),
                make_note(
                    502
                ),
                make_note(
                    503
                ),
            ],
            show_messages=True,
        )

    finally:
        batch_processor.process_structured_job = original

    assert outcome[
        "success"
    ] is False

    assert media == []

    # Both sides of the note that failed had speech and got none.
    assert outcome[
        "audit"
    ] == {
        "silent": 2,
        "empty": 0,
        "rejected": 0,
    }

    message = outcome[
        "message"
    ]

    assert "note 502 (front: synthesis failed); note 502 (back: synthesis failed)" in message

    assert "note 501" not in message
    assert "note 503" not in message

    # The report's own lines never carry the failure's text.
    assert BACK_TEXT not in outcome[
        "audit_message"
    ]


def check_a_failed_copy_marks_every_audited_side_silent():
    def failing_copy(
        audio_files,
        media_folder,
        settings,
    ):
        raise OSError(
            "disk full"
        )

    outcome, _dialogs, media = run_notes(
        [
            make_note(
                601
            ),
        ],
        copy=failing_copy,
    )

    assert outcome[
        "success"
    ] is False

    assert media == []

    assert outcome[
        "audit"
    ]["silent"] == 2

    assert "note 601 (front: the track could not be copied into Anki's media folder)" in outcome[
        "message"
    ]


def check_an_unattended_run_tells_alec_without_a_box_and_a_clean_one_stays_quiet():
    """
    Changed on purpose by CA-81/CA-83: this check used to assert that an
    unattended run raised a warning BOX for a dirty audit. A box nobody is
    watching is what held Anki's event loop; the run now shows a tooltip that
    closes itself, once, and no box.
    """

    original_process = automation.start_note_run
    original_warning = automation.showWarning
    original_tooltip = ui_module.tooltip

    warnings = []
    notices = []

    ui_module.tooltip = lambda text, period=None, **_: notices.append(
        text
    )

    def run(
        outcome,
        show_completion,
    ):
        note = AutomationNote(
            1,
            [
                "personal",
                automation.RCE_AUDIO_PENDING_TAG,
                automation.RCE_AUDIO_IMMEDIATE_TAG,
            ],
        )

        window = AutomationWindow(
            [
                note,
            ]
        )

        def fake_process_note_ids(
            note_ids,
            passed_window,
            addon_name,
            reset_callback=None,
            show_messages=True,
        ):
            assert show_messages is False

            mark_ready_if_managed(
                note
            )

            return outcome

        automation.start_note_run = synchronous_run(fake_process_note_ids)

        automation.showWarning = warnings.append

        controller = automation.RceAudioAutomationController(
            window,
            "AnkiTTS",
        )

        controller._process(
            [
                1,
            ],
            show_completion=show_completion,
        )

    try:
        dirty = {
            "success": True,
            "message": "complete",
            "audit_alarm": True,
            "audit_message": "*** AUDIO AUDIT: 1 SIDE ... ***",
            "audit_notice": "AnkiTTS audio audit: 1 side without audio.",
        }

        # Unattended: a notice, once; no box at all.
        run(
            dirty,
            show_completion=False,
        )

        assert warnings == []

        assert notices == [
            "AnkiTTS audio audit: 1 side without audio.",
        ]

        # Watched (a manual run): its own result box carries the lines, so
        # neither a second box nor a notice.
        warnings.clear()
        notices.clear()

        run(
            dirty,
            show_completion=True,
        )

        assert "*** AUDIO AUDIT: 1 SIDE ... ***" not in warnings
        assert notices == []

        # Clean: nothing is shown.
        warnings.clear()

        run(
            {
                "success": True,
                "message": "complete",
                "audit_alarm": False,
                "audit_message": "Audio audit: 0 silent sides, 0 empty sides, 0 rejected plans.",
            },
            show_completion=False,
        )

        assert warnings == []
        assert notices == []

    finally:
        automation.start_note_run = original_process
        automation.showWarning = original_warning
        ui_module.tooltip = original_tooltip


def check_an_empty_front_keeps_its_audio_and_the_back_is_written():
    """
    CA-81 (1), through the whole run. An empty front beside a normal back
    leaves the front's field as it was and writes the back's; the audit still
    counts the empty side; a non-empty plan still replaces what was there.
    """

    kept = make_note(
        801,
        front=[],
    )

    kept[
        "Front Audio"
    ] = "[sound:old-front.mp3]"

    kept[
        "Back Audio"
    ] = "[sound:old-back.mp3]"

    replaced = make_note(
        802,
    )

    replaced[
        "Front Audio"
    ] = "[sound:old-front.mp3]"

    outcome, _dialogs, media = run_notes(
        [
            kept,
            replaced,
        ],
    )

    assert outcome[
        "success"
    ] is True

    # The empty front: its audio is left as it is.
    assert kept[
        "Front Audio"
    ] == "[sound:old-front.mp3]"

    # The normal back beside it: written, replacing the old one.
    assert kept[
        "Back Audio"
    ].startswith(
        "[sound:"
    )

    assert kept[
        "Back Audio"
    ] != "[sound:old-back.mp3]"

    # A plan with spoken segments still replaces the field.
    assert replaced[
        "Front Audio"
    ].startswith(
        "[sound:"
    )

    assert replaced[
        "Front Audio"
    ] != "[sound:old-front.mp3]"

    assert len(
        media
    ) == 3

    # And it is still reported: one empty side, nothing silent.
    assert outcome[
        "audit"
    ] == {
        "silent": 0,
        "empty": 1,
        "rejected": 0,
    }


def check_the_log_line_carries_counts_and_ids_only():
    audit = AudioAudit()

    outcome, _dialogs, _media = run_notes(
        [
            make_note(
                701,
                back=unspoken_back(),
            ),
        ],
    )

    assert outcome[
        "audit"
    ]["empty"] == 1

    from audio_audit import (
        Finding,
        REASON_NO_TRACK,
    )

    audit.silent.append(
        Finding(
            9,
            "back",
            REASON_NO_TRACK,
        )
    )

    line = audit.log_line()

    assert "1 silent sides [9]" in line
    assert "0 empty sides []" in line
    assert "0 rejected plans []" in line

    assert_no_text(
        line,
        outcome[
            "audit_message"
        ],
    )


def run():
    checks = [
        check_only_sides_with_a_version_2_plan_are_audited,
        check_a_clean_run_reports_zero_silent_sides,
        check_a_run_with_one_silent_side_reports_it,
        check_the_other_reasons_a_side_can_be_silent,
        check_an_empty_plan_lands_in_the_empty_count,
        check_a_rejected_plan_lands_in_the_rejected_count_and_stops_the_run,
        check_a_failed_synthesis_names_the_note,
        check_a_failed_copy_marks_every_audited_side_silent,
        check_an_unattended_run_tells_alec_without_a_box_and_a_clean_one_stays_quiet,
        check_an_empty_front_keeps_its_audio_and_the_back_is_written,
        check_the_log_line_carries_counts_and_ids_only,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
