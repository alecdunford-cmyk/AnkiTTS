"""
The unattended run must not hold Anki's main thread (review batch 3).

Diagnosis (docs/DESIGN-providers.md, section 18, "Review batch 3"): the add-on's
one-second timer slot, `RceAudioAutomationController.poll_immediate_requests`,
ran the whole generation run (synthesis, stitching, copying, publication) on
Anki's main thread, one note after another, and published nothing until the
last note was done. A batch of fifteen cards takes minutes; for those minutes
the main thread pumps no events and Windows calls the window Not Responding.
Ending Anki loses the run, and the recovery of interrupted notes at the next
start keeps their `immediate` tag, so the same minutes-long run starts again
four seconds after the add-on loads.

Since CA-82 the run has three parts: the notes are read and the jobs built on
the main thread, synthesis and stitching run on a background thread, and the
fields are written and the result shown back on the main thread. CA-83: an
unattended run shows no box, only a notice that closes itself, once. CA-84: the
resume at start-up is deferred and cannot raise into Anki.

No Anki, no Qt, no speech service: the stand-ins here are a window whose
`taskman` runs a task on a real thread and hands the result back on the test's
own (main) thread, a collection that answers tag searches like Anki's, and the
fake provider the other checks use. Notes and ids are invented.
"""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from tempfile import TemporaryDirectory
import logging
import queue
import threading
import time

from tests.test_anki_integration import (
    FakeCollection as BaseCollection,
    FakeMainWindow as BaseWindow,
    browser_integration,
)
from tests.test_rce_audio_automation import (
    FakeTimer,
    automation,
)

from anki_integration import ui as ui_module
from anki_integration.rce_audio_status import (
    RCE_AUDIO_FAILED_TAG,
    RCE_AUDIO_IMMEDIATE_TAG,
    RCE_AUDIO_PENDING_TAG,
    RCE_AUDIO_PROCESSING_TAG,
    RCE_AUDIO_READY_TAG,
)
import batch_processor
from providers import registry
import structured_audio
from tests.test_audio_audit import (
    BACK_TEXT,
    FRONT_TEXT,
    make_note,
)
from tests.test_role_voices import (
    RecordingEdge,
    with_directories,
)


MAIN_THREAD = threading.main_thread()


class ThreadedTaskman:
    """
    Anki's TaskManager as far as the add-on uses it: a task runs on a real
    thread, its on_done and anything given to run_on_main wait in a queue for
    the main thread, which here is the test's own thread (drain).
    """

    def __init__(
        self,
    ):
        self.queue = queue.Queue()
        self.threads = []
        self.task_thread_names = []
        self.uses_collection = []

    def run_in_background(
        self,
        task,
        on_done=None,
        args=None,
        uses_collection=True,
    ):
        future = Future()

        self.uses_collection.append(
            uses_collection
        )

        def work():
            self.task_thread_names.append(
                threading.current_thread().name
            )

            try:
                future.set_result(
                    task()
                )

            except BaseException as error:
                future.set_exception(
                    error
                )

            if on_done is not None:
                self.queue.put(
                    lambda: on_done(
                        future
                    )
                )

        thread = threading.Thread(
            target=work,
            name="fake-taskman",
            daemon=True,
        )

        self.threads.append(
            thread
        )

        thread.start()

        return future

    def run_on_main(
        self,
        closure,
    ):
        self.queue.put(
            closure
        )

    def drain(
        self,
        timeout=20.0,
    ):
        """Run what the main thread owes, until the background work is done."""

        assert (
            threading.current_thread()
            is MAIN_THREAD
        )

        deadline = time.monotonic() + timeout

        while True:
            try:
                closure = self.queue.get(
                    timeout=0.05
                )

            except queue.Empty:
                if (
                    not any(
                        thread.is_alive()
                        for thread in self.threads
                    )
                    and self.queue.empty()
                ):
                    return

                assert (
                    time.monotonic() < deadline
                ), "the background work did not finish"

                continue

            closure()


class TaggedCollection(
    BaseCollection
):
    """Anki's tag search over invented notes: the add-on's real pending test."""

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


class Window(
    BaseWindow
):
    def __init__(
        self,
        notes,
        media_directory,
        taskman=None,
    ):
        super().__init__(
            notes,
            media_directory,
        )

        self.col = TaggedCollection(
            notes,
            media_directory,
        )

        if taskman is not None:
            self.taskman = taskman


def queued_note(
    note_id,
    front=None,
    back=None,
):
    """An invented RCE note, queued for audio and asked for at once."""

    note = make_note(
        note_id,
        front=front,
        back=back,
    )

    note.tags = [
        "personal",
        RCE_AUDIO_PENDING_TAG,
        RCE_AUDIO_IMMEDIATE_TAG,
    ]

    return note


class LogCapture(
    logging.Handler
):
    def __init__(
        self,
    ):
        super().__init__(
            logging.INFO
        )

        self.records = []

    def emit(
        self,
        record,
    ):
        self.records.append(
            record
        )


def run_with_pipeline(
    action,
):
    """
    The fake provider and the stand-in stitcher. Every dialog and every notice
    is recorded with the thread that raised it; (kind, thread, text).
    """

    names = (
        "OUTPUT_DIR",
        "process_notes",
        "showInfo",
        "showWarning",
    )

    original = {
        name: getattr(
            browser_integration,
            name,
        )
        for name in names
    }

    original_automation = {
        name: getattr(
            automation,
            name,
        )
        for name in (
            "showInfo",
            "showWarning",
        )
    }

    original_tooltip = ui_module.tooltip

    shown = []

    def recorder(
        kind,
    ):
        def show(
            text,
            *args,
            **kwargs,
        ):
            shown.append(
                (
                    kind,
                    threading.current_thread(),
                    text,
                )
            )

        return show

    capture = LogCapture()

    logging.getLogger(
        "ankitts"
    ).addHandler(
        capture
    )

    def inner():
        registry.set_override_chain(
            [
                RecordingEdge(),
            ]
        )

        browser_integration.OUTPUT_DIR = structured_audio.OUTPUT_DIR

        for module in (
            browser_integration,
            automation,
        ):
            module.showInfo = recorder(
                "info"
            )

            module.showWarning = recorder(
                "warning"
            )

        ui_module.tooltip = recorder(
            "notice"
        )

        action(
            shown,
            capture.records,
        )

    try:
        with_directories(
            inner
        )

    finally:
        logging.getLogger(
            "ankitts"
        ).removeHandler(
            capture
        )

        ui_module.tooltip = original_tooltip

        for name, value in original.items():
            setattr(
                browser_integration,
                name,
                value,
            )

        for name, value in original_automation.items():
            setattr(
                automation,
                name,
                value,
            )


def assert_all_on_main(
    shown,
):
    """The tripwire: a dialog, tooltip or notice from any other thread fails."""

    for (
        kind,
        thread,
        _text,
    ) in shown:
        assert (
            thread is MAIN_THREAD
        ), f"a {kind} was raised from the thread {thread.name}"


def counting_process_notes(
    work,
    gate=None,
):
    """The real batch processor, counting the jobs it is given."""

    real = batch_processor.process_notes

    def counted(
        jobs,
        settings,
        **kwargs,
    ):
        work.append(
            (
                len(
                    jobs
                ),
                threading.current_thread(),
            )
        )

        if gate is not None:
            gate()

        return real(
            jobs,
            settings=settings,
            **kwargs,
        )

    return counted


def check_a_slow_batch_does_not_hold_the_timer_slot():
    """
    The reproduction of the freeze (item A), RED on HEAD 534e983. Fifteen
    cards take minutes; three stand in here, with the synthesis held on an
    event. The timer slot must come back while the batch is still running, and
    the batch must not run on the thread that called the slot.
    """

    release = threading.Event()
    batch_threads = []

    def hold():
        assert release.wait(
            30
        ), "the test never released the batch"

    def action(
        shown,
        _records,
    ):
        # Two of the three notes have a front whose plan has no segment: the
        # run the log shows (three empty fronts among the cards).
        notes = [
            queued_note(
                1,
                front=[],
            ),
            queued_note(
                2,
            ),
            queued_note(
                3,
                front=[],
            ),
        ]

        with TemporaryDirectory() as media:
            taskman = ThreadedTaskman()

            window = Window(
                notes,
                Path(
                    media
                ),
                taskman,
            )

            controller = automation.RceAudioAutomationController(
                window,
                "AnkiTTS",
            )

            work = []

            browser_integration.process_notes = counting_process_notes(
                work,
                hold,
            )

            # What a stuck synthesis would do: after one second, whatever the
            # code under test is doing, the batch is let go so the test ends.
            safety = threading.Timer(
                1.0,
                release.set,
            )

            safety.start()

            try:
                controller.poll_immediate_requests()

                returned_while_running = not release.is_set()

                busy_while_running = controller.busy

            finally:
                release.set()

                safety.cancel()

            taskman.drain()

            assert returned_while_running, (
                "the timer slot did not return until the batch was over: "
                "the whole run executes on the thread that called it, which "
                "in Anki is the main thread (Not Responding for the length "
                "of the batch)"
            )

            assert busy_while_running, "a run in flight must hold busy"

            batch_threads.extend(
                thread
                for _jobs, thread in work
            )

            assert batch_threads, "the batch never ran"

            assert (
                batch_threads[0]
                is not MAIN_THREAD
            ), "the batch ran on the main thread"

            # The task manager is told the task uses no collection.
            assert taskman.uses_collection == [
                False,
            ]

            # The dialogs are the other suspect (guess 1 of the managing
            # chat): none is raised off the main thread.
            assert_all_on_main(
                shown
            )

            # And the run does finish: every note is ready.
            for note in notes:
                assert (
                    RCE_AUDIO_READY_TAG
                    in note.tags
                )

            assert not window.col.find_notes(
                "tag:"
                + RCE_AUDIO_PENDING_TAG
            )

            assert not controller.busy

    run_with_pipeline(
        action
    )


def check_an_unattended_run_shows_one_notice_and_no_box():
    """
    Item B. Three queued cards, two with an empty front: the run is dirty
    (two empty sides). It shows no dialog at all; it tells Alec once, with a
    notice, from the main thread; the counts are in the outcome and the line is
    in the log; no note is failed, retried or re-queued by it.
    """

    def action(
        shown,
        records,
    ):
        notes = [
            queued_note(
                1,
                front=[],
            ),
            queued_note(
                2,
            ),
            queued_note(
                3,
                front=[],
            ),
        ]

        with TemporaryDirectory() as media:
            taskman = ThreadedTaskman()

            window = Window(
                notes,
                Path(
                    media
                ),
                taskman,
            )

            controller = automation.RceAudioAutomationController(
                window,
                "AnkiTTS",
            )

            outcomes = []

            real_start = automation.start_note_run

            def spying_start(
                *args,
                on_finished,
                **kwargs,
            ):
                def capture(
                    outcome,
                ):
                    outcomes.append(
                        outcome
                    )

                    on_finished(
                        outcome
                    )

                real_start(
                    *args,
                    on_finished=capture,
                    **kwargs,
                )

            automation.start_note_run = spying_start

            try:
                controller.poll_immediate_requests()

                taskman.drain()

            finally:
                automation.start_note_run = real_start

            kinds = [
                kind
                for kind, _thread, _text in shown
            ]

            assert kinds == [
                "notice",
            ], f"expected one notice and no box, got {kinds}"

            assert_all_on_main(
                shown
            )

            notice = shown[
                0
            ][2]

            assert "2 sides" in notice
            assert "0 silent, 2 empty, 0 rejected" in notice

            for sentence in (
                FRONT_TEXT,
                BACK_TEXT,
            ):
                assert sentence not in notice

            assert len(
                outcomes
            ) == 1

            assert outcomes[
                0
            ]["audit"] == {
                "silent": 0,
                "empty": 2,
                "rejected": 0,
            }

            assert outcomes[
                0
            ]["success"] is True

            lines = [
                record.getMessage()
                for record in records
                if record.getMessage().startswith(
                    "Audio audit:"
                )
            ]

            assert lines == [
                "Audio audit: 0 silent sides [], 2 empty sides [1, 3], "
                "0 rejected plans [].",
            ]

            # CA-89: the run says where it is, in counts, and nothing else.
            progress = [
                record.getMessage()
                for record in records
                if record.getMessage().startswith(
                    "Audio run:"
                )
            ]

            assert len(
                progress
            ) == 3

            for index, line in enumerate(
                progress,
                1,
            ):
                assert line == f"Audio run: note {index} of 3 done."

            started = [
                record.getMessage()
                for record in records
                if record.getMessage().startswith(
                    "Audio run started"
                )
                or record.getMessage().startswith(
                    "Audio run finished"
                )
            ]

            assert len(
                started
            ) == 2

            # (The generator's own "synthesized ..." lines carry a short text
            # preview, as they did before; the lines of the run, the audit and
            # the automation never do.)
            for record in records:
                if record.name in (
                    "ankitts.batch",
                    "ankitts.browser",
                    "ankitts.automation",
                    "ankitts.ui",
                ):
                    for sentence in (
                        FRONT_TEXT,
                        BACK_TEXT,
                    ):
                        assert sentence not in record.getMessage()

            # The dirty audit failed, retried and re-queued nothing.
            for note in notes:
                assert note.tags == [
                    "personal",
                    RCE_AUDIO_READY_TAG,
                ]

    run_with_pipeline(
        action
    )


def check_a_run_by_hand_shows_one_box_with_the_audit_and_no_notice():
    """
    Item B, the manual path: the result box he already gets carries the
    audit's lines; no second box, no notice. Raised on the main thread.
    """

    def action(
        shown,
        _records,
    ):
        notes = [
            queued_note(
                1,
                front=[],
            ),
            queued_note(
                2,
            ),
        ]

        with TemporaryDirectory() as media:
            taskman = ThreadedTaskman()

            window = Window(
                notes,
                Path(
                    media
                ),
                taskman,
            )

            outcomes = []

            browser_integration.start_note_run(
                [
                    1,
                    2,
                ],
                window,
                "AnkiTTS",
                on_finished=outcomes.append,
                show_messages=True,
            )

            taskman.drain()

            assert [
                kind
                for kind, _thread, _text in shown
            ] == [
                "warning",
            ]

            assert_all_on_main(
                shown
            )

            box = shown[
                0
            ][2]

            assert "*** AUDIO AUDIT: 1 SIDE WITHOUT AUDIO" in box
            assert "1 empty side" in box

            assert len(
                outcomes
            ) == 1

            assert outcomes[
                0
            ]["success"] is True

    run_with_pipeline(
        action
    )


def check_pending_audio_terminates_with_empty_sides():
    """
    Item C. The real pending test is the tag search the automation runs
    (IMMEDIATE_AUDIO_QUERY, then PENDING_AUDIO_QUERY) over `rce-audio::pending`:
    after one run, a note with an empty front is ready like the others, its back
    is generated as usual, and the next polls find no work. Three consecutive
    polls over the same notes: 3 jobs, 0, 0.
    """

    def action(
        shown,
        _records,
    ):
        notes = [
            queued_note(
                1,
                front=[],
            ),
            queued_note(
                2,
            ),
            queued_note(
                3,
                front=[],
            ),
        ]

        with TemporaryDirectory() as media:
            taskman = ThreadedTaskman()

            window = Window(
                notes,
                Path(
                    media
                ),
                taskman,
            )

            controller = automation.RceAudioAutomationController(
                window,
                "AnkiTTS",
            )

            work = []

            browser_integration.process_notes = counting_process_notes(
                work
            )

            done = []

            for _poll in range(
                3
            ):
                before = len(
                    work
                )

                controller.poll_immediate_requests()

                taskman.drain()

                done.append(
                    sum(
                        jobs
                        for jobs, _thread in work[
                            before:
                        ]
                    )
                )

            assert done == [
                3,
                0,
                0,
            ], f"work per poll: {done}"

            # The manual command finds nothing either.
            controller.process_pending_requests()

            assert shown[
                -1
            ][0:1] == (
                "info",
            )

            assert shown[
                -1
            ][2] == (
                "No RCE cards are currently queued for AnkiTTS."
            )

            # The back of the note with an empty front was generated as usual.
            assert (
                "[sound:"
                in notes[
                    0
                ]["Back Audio"]
            )

            assert (
                "[sound:"
                in notes[
                    1
                ]["Front Audio"]
            )

            for note in notes:
                assert note.tags == [
                    "personal",
                    RCE_AUDIO_READY_TAG,
                ]

            assert not window.col.find_notes(
                "tag:"
                + RCE_AUDIO_PENDING_TAG
            )

            assert_all_on_main(
                shown
            )

    run_with_pipeline(
        action
    )


def check_the_start_up_resume_is_deferred_and_cannot_raise():
    """
    Item C, the start-up path, which holds whatever the diagnosis finds. The
    hooks only schedule the resume; nothing is searched, tagged or started
    inside them; and a failure when it does run is logged, never raised.
    """

    notes = [
        queued_note(
            1,
        ),
    ]

    notes[
        0
    ].tags = [
        "personal",
        RCE_AUDIO_PROCESSING_TAG,
        RCE_AUDIO_IMMEDIATE_TAG,
    ]

    with TemporaryDirectory() as media:
        window = Window(
            notes,
            Path(
                media
            ),
        )

        controller = automation.RceAudioAutomationController(
            window,
            "AnkiTTS",
        )

        timer = FakeTimer()

        scheduled = []

        lifecycle = automation.RceAudioPollingLifecycle(
            controller,
            timer,
            schedule=lambda delay, closure: scheduled.append(
                (
                    delay,
                    closure,
                )
            ),
        )

        window.col.updated_notes.clear()

        # The hook: collection_did_load.
        assert lifecycle.resume_later() is None

        assert len(
            scheduled
        ) == 1

        assert scheduled[
            0
        ][0] == automation.RESUME_DELAY_MS

        assert automation.RESUME_DELAY_MS >= 1000

        # Nothing has happened yet: no search, no tag written, no timer.
        assert window.col.updated_notes == []

        assert RCE_AUDIO_PROCESSING_TAG in notes[
            0
        ].tags

        assert not timer.active

        # Later, on Anki's schedule, the resume runs.
        assert scheduled[
            0
        ][1]() is True

        assert timer.active

        assert RCE_AUDIO_PROCESSING_TAG not in notes[
            0
        ].tags

        assert RCE_AUDIO_FAILED_TAG in notes[
            0
        ].tags

        assert RCE_AUDIO_IMMEDIATE_TAG in notes[
            0
        ].tags

    # A failure in the resume is logged and never raised into Anki.
    class BrokenController:
        def resume_polling(
            self,
        ):
            return True

        def recover_after_restart(
            self,
        ):
            raise RuntimeError(
                "a search failed: " + FRONT_TEXT
            )

        def suspend_polling(
            self,
        ):
            pass

    capture = LogCapture()

    logging.getLogger(
        "ankitts"
    ).addHandler(
        capture
    )

    try:
        timer = FakeTimer()

        lifecycle = automation.RceAudioPollingLifecycle(
            BrokenController(),
            timer,
            schedule=lambda delay, closure: closure(),
        )

        # The scheduler here runs the closure at once, as Qt would later.
        assert lifecycle.resume_later() is None

        assert lifecycle.resume_safely() is False

        # Even the scheduler failing is only logged.
        def broken_schedule(
            delay,
            closure,
        ):
            raise OSError(
                "no timer"
            )

        lifecycle = automation.RceAudioPollingLifecycle(
            BrokenController(),
            FakeTimer(),
            schedule=broken_schedule,
        )

        assert lifecycle.resume_later() is None

    finally:
        logging.getLogger(
            "ankitts"
        ).removeHandler(
            capture
        )

    messages = [
        record.getMessage()
        for record in capture.records
    ]

    assert any(
        message
        == "Resuming the RCE audio polling failed: RuntimeError"
        for message in messages
    )

    assert any(
        message
        == "Scheduling the RCE audio resume failed: OSError"
        for message in messages
    )

    # The exception's text can hold card text; only its type is logged.
    for message in messages:
        assert FRONT_TEXT not in message


def check_a_resume_during_a_run_leaves_the_timer_running_and_tries_again():
    """
    A temporary close of the collection can bring a resume in the middle of a
    run (it never could while the run held the main thread). It must not stop
    the poll timer for good: it leaves it, and tries again later.
    """

    notes = [
        queued_note(
            1,
        ),
    ]

    with TemporaryDirectory() as media:
        window = Window(
            notes,
            Path(
                media
            ),
        )

        controller = automation.RceAudioAutomationController(
            window,
            "AnkiTTS",
        )

        timer = FakeTimer()

        scheduled = []

        lifecycle = automation.RceAudioPollingLifecycle(
            controller,
            timer,
            schedule=lambda delay, closure: scheduled.append(
                closure
            ),
        )

        assert lifecycle.resume()

        assert timer.active

        stops = timer.stop_calls

        controller.busy = True

        assert lifecycle.resume() is False

        assert timer.active
        assert timer.stop_calls == stops
        assert len(
            scheduled
        ) == 1

        # The run ends; the scheduled attempt finds the controller idle.
        controller.busy = False

        assert scheduled[
            0
        ]() is True

        assert timer.active


def check_a_run_is_stopped_between_notes_when_the_collection_closes():
    """
    CA-85. Closing the profile while a run is in flight stops it between notes
    (no wait at exit), changes no tag (the collection is gone) and the notes
    are recovered at the next start and finish then.
    """

    release = threading.Event()

    def hold():
        assert release.wait(
            30
        )

    def action(
        shown,
        _records,
    ):
        notes = [
            queued_note(
                1,
            ),
            queued_note(
                2,
                front=[],
            ),
        ]

        with TemporaryDirectory() as media:
            taskman = ThreadedTaskman()

            window = Window(
                notes,
                Path(
                    media
                ),
                taskman,
            )

            controller = automation.RceAudioAutomationController(
                window,
                "AnkiTTS",
            )

            timer = FakeTimer()

            lifecycle = automation.RceAudioPollingLifecycle(
                controller,
                timer,
            )

            work = []

            browser_integration.process_notes = counting_process_notes(
                work,
                hold,
            )

            controller.poll_immediate_requests()

            # Anki closes the profile while the batch is still running.
            lifecycle.suspend()

            release.set()

            taskman.drain()

            # Stopped before the first note: nothing written, no box.
            assert shown == []

            assert notes[
                0
            ]["Front Audio"] == ""

            assert RCE_AUDIO_PROCESSING_TAG in notes[
                0
            ].tags

            assert not controller.busy

            # The next start: recovery keeps `immediate`, the poll finishes it.
            assert lifecycle.resume()

            assert RCE_AUDIO_PROCESSING_TAG not in notes[
                0
            ].tags

            browser_integration.process_notes = counting_process_notes(
                work
            )

            controller.poll_immediate_requests()

            taskman.drain()

            for note in notes:
                assert note.tags == [
                    "personal",
                    RCE_AUDIO_READY_TAG,
                ]

    run_with_pipeline(
        action
    )


def check_one_run_at_a_time_and_a_changed_collection_is_never_written():
    """
    CA-85. While a run is in flight a second poll starts nothing and the manual
    command says so; if the collection is replaced while the audio is made, the
    result is not published into the new collection.
    """

    release = threading.Event()

    def hold():
        assert release.wait(
            30
        )

    def action(
        shown,
        _records,
    ):
        notes = [
            queued_note(
                1,
            ),
        ]

        with TemporaryDirectory() as media:
            taskman = ThreadedTaskman()

            window = Window(
                notes,
                Path(
                    media
                ),
                taskman,
            )

            controller = automation.RceAudioAutomationController(
                window,
                "AnkiTTS",
            )

            work = []

            browser_integration.process_notes = counting_process_notes(
                work,
                hold,
            )

            controller.poll_immediate_requests()

            controller.poll_immediate_requests()

            controller.process_pending_requests()

            assert shown[
                -1
            ][2] == (
                "AnkiTTS is already processing an RCE audio request."
            )

            # A manual browser run asked for meanwhile is refused too.
            refused = []

            browser_integration.start_note_run(
                [
                    1,
                ],
                window,
                "AnkiTTS",
                on_finished=refused.append,
                show_messages=False,
            )

            assert refused[
                0
            ]["busy"] is True

            # The profile is switched while the audio is made.
            other = TaggedCollection(
                [],
                Path(
                    media
                ),
            )

            window.col = other

            release.set()

            taskman.drain()

            assert len(
                work
            ) == 1, "a second run was started"

            assert notes[
                0
            ]["Front Audio"] == ""

            assert not browser_integration.run_in_flight()

            assert not controller.busy

            assert_all_on_main(
                shown
            )

    run_with_pipeline(
        action
    )


def check_the_cancel_hook_stops_the_batch_between_notes():
    cancelled = {
        "now": False,
    }

    calls = []

    original = batch_processor.process_field_definitions

    def fake_fields(
        fields,
        settings,
    ):
        calls.append(
            fields
        )

        cancelled[
            "now"
        ] = True

        return {
            "statistics": batch_processor.empty_statistics(),
        }

    batch_processor.process_field_definitions = fake_fields

    try:
        result = batch_processor.process_notes(
            [
                {
                    "fields": 1,
                },
            ],
            settings=None,
        )

        assert result[
            "processed"
        ] == 1

        calls.clear()

        cancelled[
            "now"
        ] = False

        try:
            batch_processor.process_notes(
                [
                    {
                        "fields": 1,
                    },
                    {
                        "fields": 2,
                    },
                ],
                settings=None,
                should_cancel=lambda: cancelled[
                    "now"
                ],
            )

        except batch_processor.RunCancelled as error:
            assert error.job_index == 1

        else:
            raise AssertionError(
                "the run was not stopped between notes"
            )

        # The first note was done; the second never started.
        assert calls == [
            1,
        ]

    finally:
        batch_processor.process_field_definitions = original


def check_nothing_reaches_a_dialog_from_another_thread():
    """
    The routing under the tripwire: off the main thread a notice is queued for
    the main thread through Anki's own mechanism, and with no way to reach it
    the call is dropped, never made. And the recorder does see a call made from
    another thread, so the other checks' assertions are not vacuous.
    """

    original_tooltip = ui_module.tooltip

    seen = []

    ui_module.tooltip = lambda text, period=None, **_: seen.append(
        (
            threading.current_thread(),
            text,
            period,
        )
    )

    try:
        taskman = ThreadedTaskman()

        class Window_:
            pass

        window = Window_()

        window.taskman = taskman

        worker = threading.Thread(
            target=lambda: ui_module.show_notice(
                window,
                "from a worker",
            ),
        )

        worker.start()

        worker.join()

        # Queued, not shown on the worker.
        assert seen == []

        taskman.drain()

        assert len(
            seen
        ) == 1

        assert seen[
            0
        ][0] is MAIN_THREAD

        assert seen[
            0
        ][2] == ui_module.NOTICE_PERIOD_MS

        # No task manager and not on the main thread: dropped.
        seen.clear()

        bare = Window_()

        worker = threading.Thread(
            target=lambda: ui_module.show_notice(
                bare,
                "dropped",
            ),
        )

        worker.start()

        worker.join()

        assert seen == []

        # On the main thread it is shown at once.
        ui_module.show_notice(
            bare,
            "now",
        )

        assert len(
            seen
        ) == 1

        # The negative control: a direct call from a worker is recorded as
        # being off the main thread.
        shown = []

        def record(
            text,
        ):
            shown.append(
                (
                    "warning",
                    threading.current_thread(),
                    text,
                )
            )

        worker = threading.Thread(
            target=lambda: record(
                "x"
            ),
        )

        worker.start()

        worker.join()

        try:
            assert_all_on_main(
                shown
            )

        except AssertionError:
            pass

        else:
            raise AssertionError(
                "the tripwire did not see a call from another thread"
            )

    finally:
        ui_module.tooltip = original_tooltip


def run():
    checks = [
        check_a_slow_batch_does_not_hold_the_timer_slot,
        check_an_unattended_run_shows_one_notice_and_no_box,
        check_a_run_by_hand_shows_one_box_with_the_audit_and_no_notice,
        check_pending_audio_terminates_with_empty_sides,
        check_the_start_up_resume_is_deferred_and_cannot_raise,
        check_a_resume_during_a_run_leaves_the_timer_running_and_tries_again,
        check_a_run_is_stopped_between_notes_when_the_collection_closes,
        check_one_run_at_a_time_and_a_changed_collection_is_never_written,
        check_the_cancel_hook_stops_the_batch_between_notes,
        check_nothing_reaches_a_dialog_from_another_thread,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
