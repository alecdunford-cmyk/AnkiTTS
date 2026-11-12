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

No Anki, no Qt, no speech service: the stand-ins here are a window whose
`taskman` runs a task on a real thread and hands the result back on the test's
own (main) thread, a collection that answers tag searches like Anki's, and the
fake provider the other checks use. Notes and ids are invented.
"""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from tempfile import TemporaryDirectory
import queue
import threading
import time

from tests.test_anki_integration import (
    FakeCollection as BaseCollection,
    FakeMainWindow as BaseWindow,
    FakeNote,
    browser_integration,
)
from tests.test_rce_audio_automation import automation

from anki_integration.rce_audio_status import (
    RCE_AUDIO_IMMEDIATE_TAG,
    RCE_AUDIO_PENDING_TAG,
    RCE_AUDIO_READY_TAG,
)
import batch_processor
from providers import registry
import structured_audio
from tests.test_audio_audit import (
    BACK_TEXT,
    FRONT_TEXT,
    good_back,
    good_front,
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

    def run_in_background(
        self,
        task,
        on_done=None,
        args=None,
        uses_collection=True,
    ):
        future = Future()

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


def run_with_pipeline(
    action,
):
    """The fake provider and the stand-in stitcher; dialogs recorded by thread."""

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

        action(
            shown
        )

    try:
        with_directories(
            inner
        )

    finally:
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


def check_a_slow_batch_does_not_hold_the_timer_slot():
    """
    RED on the code of HEAD 534e983 (the diagnosis). Fifteen cards take
    minutes; three stand in here, with the synthesis held on an event. The
    timer slot must come back while the batch is still running, and the batch
    must not run on the thread that called the slot.
    """

    release = threading.Event()
    started = threading.Event()
    batch_threads = []

    real_process_notes = batch_processor.process_notes

    def slow_process_notes(
        jobs,
        settings,
        **kwargs,
    ):
        batch_threads.append(
            threading.current_thread()
        )

        started.set()

        assert release.wait(
            30
        ), "the test never released the batch"

        return real_process_notes(
            jobs,
            settings=settings,
            **kwargs,
        )

    def action(
        shown,
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

            browser_integration.process_notes = slow_process_notes

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

            assert batch_threads, "the batch never ran"

            assert (
                batch_threads[0]
                is not MAIN_THREAD
            ), "the batch ran on the main thread"

            # The dialogs are the other suspect (guess 1 of the managing
            # chat): none of them is raised off the main thread, then or now.
            for (
                _kind,
                thread,
                _text,
            ) in shown:
                assert (
                    thread is MAIN_THREAD
                ), "a dialog was raised from another thread"

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

    run_with_pipeline(
        action
    )


def run():
    checks = [
        check_a_slow_batch_does_not_hold_the_timer_slot,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
