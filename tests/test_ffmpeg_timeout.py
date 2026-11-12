"""
CA-87 / review batch 4, item C: every ffmpeg run in src/providers is bounded.

A stalled ffmpeg used to hold one background run until Anki was restarted.
Now `providers.audio._run_ffmpeg` (every loudness measurement, every MP3
encode, Edge's carrier cut) ends and reaps a run that has not finished after
FFMPEG_TIMEOUT_SECONDS and raises AudioStepTimedOut naming the step only. In a
batch run the note fails alone, the run goes on, the note is not published,
keeps `pending` and loses `immediate` (CA-93).

The "ffmpeg" here is a real process that never returns (a sleeping Python),
started through the add-on's process-wide window-hiding patch. No speech
service, no Anki, no Qt. Every string is invented.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time

import batch_processor
from providers import audio
from providers import registry
from providers.audio import (
    AudioStepTimedOut,
    LOUDNESS_VERSION,
)
from rce_contract import create_rce_speech_plan_job
from settings import AppSettings
from stitcher import hide_subprocess_windows
import structured_audio
from tests.test_audio_audit import make_note
from tests.test_role_voices import (
    RecordingEdge,
    v2_note,
    v2_segment,
    with_directories,
)
from tests.test_unattended_run import (
    MAIN_THREAD,
    RCE_AUDIO_FAILED_TAG,
    RCE_AUDIO_IMMEDIATE_TAG,
    RCE_AUDIO_PENDING_TAG,
    RCE_AUDIO_READY_TAG,
    ThreadedTaskman,
    Window,
    assert_all_on_main,
    automation,
    browser_integration,
    counting_process_notes,
    run_with_pipeline,
)


REAL_POPEN = subprocess.Popen

# The bound the checks use: short, so they run fast.
TEST_BOUND_SECONDS = 1.0

# How long past the bound a call may take: ending and reaping a process.
SLACK_SECONDS = 8.0

STALL_TEXT = "une lanterne en panne"


class StallingFfmpeg:
    """
    subprocess.Popen while installed: an ffmpeg command starts a process that
    never returns (a Python that sleeps for ten minutes); anything else is
    started as asked.
    """

    def __init__(
        self,
    ):
        self.started = []
        self.flags = []

    def __call__(
        self,
        args,
        **kwargs,
    ):
        command = (
            args
            if isinstance(
                args,
                (list, tuple),
            )
            else [
                args,
            ]
        )

        if command[0] != audio._ffmpeg():
            return REAL_POPEN(
                args,
                **kwargs,
            )

        self.flags.append(
            kwargs.get(
                "creationflags",
                0,
            )
        )

        process = REAL_POPEN(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(600)",
            ],
            **kwargs,
        )

        self.started.append(
            process
        )

        return process


def with_stalling_ffmpeg(
    action,
):
    """The stand-in for ffmpeg and the short bound, put back afterwards."""

    stalling = StallingFfmpeg()

    original_bound = audio.FFMPEG_TIMEOUT_SECONDS

    subprocess.Popen = stalling
    audio.FFMPEG_TIMEOUT_SECONDS = TEST_BOUND_SECONDS

    try:
        action(
            stalling
        )

    finally:
        subprocess.Popen = REAL_POPEN
        audio.FFMPEG_TIMEOUT_SECONDS = original_bound

        # Nothing is left running, whatever a check did.
        for process in stalling.started:
            if process.poll() is None:
                process.kill()
                process.wait()


def assert_ended_and_reaped(
    stalling,
):
    assert stalling.started, "no ffmpeg run was started"

    for process in stalling.started:
        # Ended (no longer running) and reaped (its exit status collected).
        assert process.poll() is not None
        assert process.returncode is not None


def check_the_bound_is_a_named_constant_and_no_version_moved():
    assert audio.FFMPEG_TIMEOUT_SECONDS == 120
    assert audio.FFMPEG_REAP_SECONDS == 10

    # The audio produced is the same: nothing refills for this item.
    assert structured_audio.STITCH_VERSION == "2"
    assert LOUDNESS_VERSION == "1"


def check_a_stalled_run_is_ended_and_reaped_within_the_bound():
    def action(
        stalling,
    ):
        # The add-on's process-wide window-hiding patch is active around the
        # call, as it is around every batch (browser.generate_run).
        with hide_subprocess_windows():
            started = time.monotonic()

            try:
                audio._run_ffmpeg(
                    [
                        "-i",
                        "C:/somewhere/secret-name.mp3",
                    ],
                    step="loudness measurement",
                )

            except AudioStepTimedOut as error:
                elapsed = time.monotonic() - started
                raised = error

            else:
                raise AssertionError(
                    "the stalled run returned"
                )

        assert TEST_BOUND_SECONDS <= elapsed < (
            TEST_BOUND_SECONDS + SLACK_SECONDS
        ), elapsed

        assert_ended_and_reaped(
            stalling
        )

        # The window-hiding flag reached the process: the patch was active.
        if hasattr(
            subprocess,
            "CREATE_NO_WINDOW",
        ):
            assert all(
                flags & subprocess.CREATE_NO_WINDOW
                for flags in stalling.flags
            )

        # The step only: no path, no process output.
        assert str(
            raised
        ) == (
            "The loudness measurement step did not finish within 1 seconds "
            "and was stopped."
        )

        assert raised.step == "loudness measurement"
        assert "secret-name" not in str(
            raised
        )

        # The patch is put back as it was.
        assert subprocess.Popen is stalling

    with_stalling_ffmpeg(
        action
    )


def check_an_encode_that_stalls_names_its_step_and_leaves_nothing_behind():
    def action(
        stalling,
    ):
        with TemporaryDirectory() as directory:
            root = Path(
                directory
            )

            source = root / "clip.mp3"
            source.write_bytes(
                b"not really audio"
            )

            output = root / "out.mp3"

            try:
                audio.encode_mp3(
                    source,
                    output,
                )

            except AudioStepTimedOut as error:
                assert error.step == "loudness measurement"

            else:
                raise AssertionError(
                    "the stalled encode returned"
                )

            # No cache entry, no temporary file, and the encode lock is free.
            assert sorted(
                path.name
                for path in root.iterdir()
            ) == [
                "clip.mp3",
            ]

            assert audio._encode_lock.acquire(
                blocking=False
            )

            audio._encode_lock.release()

        assert_ended_and_reaped(
            stalling
        )

    with_stalling_ffmpeg(
        action
    )


class StallingEdge(
    RecordingEdge
):
    """The fake Edge; one text goes through the real encoder, which stalls."""

    def synthesize(
        self,
        text,
        language,
        profile,
        output_path,
    ):
        if text == STALL_TEXT:
            self.calls.append(
                (
                    text,
                    language,
                    profile,
                )
            )

            Path(
                output_path
            ).write_bytes(
                b"edge audio"
            )

            audio.normalise_mp3_in_place(
                output_path
            )

            return

        super().synthesize(
            text,
            language,
            profile,
            output_path,
        )


def stalling_front():
    return [
        v2_segment(
            1,
            STALL_TEXT,
            "fr-FR",
            "content",
            role="headword",
        )
    ]


def check_a_timed_out_note_fails_alone_and_the_run_goes_on():
    """
    The whole unattended path: one poll, three queued notes, the second one
    stalls in ffmpeg. The poll's run comes back within the bound; notes 1 and
    3 are published and ready; note 2 is not published, keeps `pending`,
    loses `immediate`; three polls after it do no work; the menu command
    still finds it.
    """

    def action(
        stalling,
    ):
        def pipeline(
            shown,
            records,
        ):
            registry.set_override_chain(
                [
                    StallingEdge(),
                ]
            )

            notes = [
                _queued(
                    1
                ),
                _queued(
                    2,
                    front=stalling_front(),
                ),
                _queued(
                    3
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

                started = time.monotonic()

                controller.poll_immediate_requests()

                taskman.drain(
                    timeout=TEST_BOUND_SECONDS + 30
                )

                elapsed = time.monotonic() - started

                # One stalled ffmpeg run, ended within the bound.
                assert TEST_BOUND_SECONDS <= elapsed < (
                    TEST_BOUND_SECONDS + SLACK_SECONDS + 10
                ), elapsed

                assert_ended_and_reaped(
                    stalling
                )

                assert len(
                    stalling.started
                ) == 1

                # The run went on: notes 1 and 3 are published and ready.
                for index in (
                    0,
                    2,
                ):
                    assert notes[
                        index
                    ].tags == [
                        "personal",
                        RCE_AUDIO_READY_TAG,
                    ], notes[index].tags

                    assert "[sound:" in notes[
                        index
                    ][
                        "Front Audio"
                    ]

                    assert "[sound:" in notes[
                        index
                    ][
                        "Back Audio"
                    ]

                # Note 2: failed, not ready, pending kept, immediate gone,
                # nothing published (its fields are as they were).
                assert notes[
                    1
                ].tags == [
                    "personal",
                    RCE_AUDIO_PENDING_TAG,
                    RCE_AUDIO_FAILED_TAG,
                ], notes[1].tags

                assert RCE_AUDIO_IMMEDIATE_TAG not in notes[
                    1
                ].tags

                assert notes[
                    1
                ][
                    "Front Audio"
                ] == ""

                assert notes[
                    1
                ][
                    "Back Audio"
                ] == ""

                # Only the two published notes' tracks reached Anki's media.
                published = {
                    path.name
                    for path in Path(
                        media
                    ).iterdir()
                }

                referenced = {
                    notes[
                        index
                    ][
                        field
                    ][
                        len("[sound:"):-1
                    ]
                    for index in (
                        0,
                        2,
                    )
                    for field in (
                        "Front Audio",
                        "Back Audio",
                    )
                }

                assert published == referenced, (
                    published,
                    referenced,
                )

                # Three polls after it: no work, the stalled note included.
                for _poll in range(
                    3
                ):
                    controller.poll_immediate_requests()
                    taskman.drain()

                assert [
                    jobs
                    for jobs, _thread in work
                ] == [
                    3,
                ], work

                assert len(
                    stalling.started
                ) == 1

                # Unattended: no box; the audit counts the silent note once,
                # in a notice; everything shown is on the main thread.
                assert [
                    kind
                    for kind, _thread, _text in shown
                ] == [
                    "notice",
                ], shown

                assert_all_on_main(
                    shown
                )

                # The log names the step and never the note's text.
                messages = [
                    record.getMessage()
                    for record in records
                ]

                assert (
                    "Audio run: note 2 of 3 failed: the loudness measurement "
                    "step timed out."
                ) in messages, messages

                batch_lines = [
                    record.getMessage()
                    for record in records
                    if record.name.endswith(
                        ".batch"
                    )
                    or record.name.endswith(
                        ".browser"
                    )
                    or record.name.endswith(
                        ".automation"
                    )
                    or record.name.endswith(
                        "providers.audio"
                    )
                ]

                assert not any(
                    STALL_TEXT in line
                    for line in batch_lines
                ), batch_lines

                # The menu command still retries it (it is pending), and only
                # it.
                controller.process_pending_requests()
                taskman.drain(
                    timeout=TEST_BOUND_SECONDS + 30
                )

                assert [
                    jobs
                    for jobs, _thread in work
                ] == [
                    3,
                    1,
                ], work

        run_with_pipeline(
            pipeline
        )

    with_stalling_ffmpeg(
        action
    )


def _queued(
    note_id,
    front=None,
):
    note = make_note(
        note_id,
        front=front,
    )

    note.tags = [
        "personal",
        RCE_AUDIO_PENDING_TAG,
        RCE_AUDIO_IMMEDIATE_TAG,
    ]

    return note


def check_outside_a_batch_run_and_for_any_other_failure_the_run_is_all_or_nothing():
    def action(
        stalling,
    ):
        def inner():
            registry.set_override_chain(
                [
                    StallingEdge(),
                ]
            )

            settings = AppSettings()

            jobs = [
                create_rce_speech_plan_job(
                    v2_note(
                        stalling_front(),
                        [],
                    )
                ),
            ]

            # The editor's single note (no continue_after_timeout): the
            # failure is raised, with the timeout behind it.
            try:
                with hide_subprocess_windows():
                    batch_processor.process_notes(
                        jobs,
                        settings,
                    )

            except Exception as error:
                assert error.job_index == 0
                assert batch_processor.timed_out_step(
                    error
                ).step == "loudness measurement"

            else:
                raise AssertionError(
                    "the run did not fail"
                )

            # A batch run whose failure is not a timeout is still stopped.
            class Broken(
                RecordingEdge
            ):
                def synthesize(
                    self,
                    *args,
                ):
                    raise RuntimeError(
                        "a provider failure"
                    )

            registry.set_override_chain(
                [
                    Broken(),
                ]
            )

            try:
                batch_processor.process_notes(
                    [
                        create_rce_speech_plan_job(
                            v2_note(
                                [],
                                [
                                    v2_segment(
                                        1,
                                        "a lamp",
                                        "en-US",
                                        "content",
                                        role="gloss",
                                    )
                                ],
                            )
                        ),
                    ],
                    settings,
                    continue_after_timeout=True,
                )

            except Exception as error:
                assert error.job_index == 0
                assert batch_processor.timed_out_step(
                    error
                ) is None

            else:
                raise AssertionError(
                    "the run did not fail"
                )

        with_directories(
            inner
        )

    with_stalling_ffmpeg(
        action
    )


def run():
    assert threading.current_thread() is MAIN_THREAD

    checks = [
        check_the_bound_is_a_named_constant_and_no_version_moved,
        check_a_stalled_run_is_ended_and_reaped_within_the_bound,
        check_an_encode_that_stalls_names_its_step_and_leaves_nothing_behind,
        check_a_timed_out_note_fails_alone_and_the_run_goes_on,
        check_outside_a_batch_run_and_for_any_other_failure_the_run_is_all_or_nothing,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
