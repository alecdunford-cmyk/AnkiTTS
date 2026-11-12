from time import perf_counter

from ankitts_log import get_logger
from card_processor import (
    combine_statistics,
    empty_statistics,
    process_field_definitions,
)
from providers.audio import AudioStepTimedOut
from rce_contract import RCE_JOB_TYPE
from structured_audio import process_structured_job


logger = get_logger(
    "batch"
)


class RunCancelled(Exception):
    """The run was stopped between notes (Anki is closing the profile)."""


def timed_out_step(
    error,
):
    """
    The AudioStepTimedOut behind a note's failure, or None.

    It is looked for in the exception's causes and contexts, and in the
    attempts a SynthesisFailed carries (one per provider), however deep.
    """

    pending = [
        error,
    ]

    seen = set()

    while pending:
        current = pending.pop()

        if (
            current is None
            or id(
                current
            )
            in seen
        ):
            continue

        seen.add(
            id(
                current
            )
        )

        if isinstance(
            current,
            AudioStepTimedOut,
        ):
            return current

        pending.append(
            current.__cause__
        )

        pending.append(
            current.__context__
        )

        for attempt in getattr(
            current,
            "attempts",
            (),
        ) or ():
            if (
                isinstance(
                    attempt,
                    tuple,
                )
                and len(
                    attempt
                )
                == 3
                and isinstance(
                    attempt[2],
                    BaseException,
                )
            ):
                pending.append(
                    attempt[2]
                )

    return None


def process_notes(
    notes,
    settings,
    should_cancel=None,
    continue_after_timeout=False,
):
    """
    Process one or more generic or structured audio jobs.

    should_cancel, when given, is asked before each note; the run is stopped
    between notes with RunCancelled, so a run that cannot finish does not hold
    Anki open at exit. The check is a plain call that reads a flag.

    A run is all-or-nothing (CA-78), with one exception when
    continue_after_timeout is set (a batch run, CA-93): a note whose failure is
    an audio step that timed out (AudioStepTimedOut) is failed alone, its
    result is None, its index and step are in "timed_out", and the run goes on
    with the next note.
    """

    results = []
    timed_out = []
    statistics = empty_statistics()
    started_at = perf_counter()

    for index, job in enumerate(
        notes
    ):
        if (
            should_cancel is not None
            and should_cancel()
        ):
            error = RunCancelled(
                "The run was stopped before this note."
            )

            error.job_index = index

            raise error

        try:
            if (
                job.get(
                    "job_type"
                )
                == RCE_JOB_TYPE
            ):
                result = process_structured_job(
                    job,
                    settings,
                )

            else:
                result = process_field_definitions(
                    job["fields"],
                    settings,
                )

        except Exception as error:
            timeout = (
                timed_out_step(
                    error
                )
                if continue_after_timeout
                else None
            )

            if timeout is None:
                # Which job failed, for the audio audit (item C); the run is
                # still all-or-nothing.
                error.job_index = index

                raise

            # The step only: the exception's own text can hold card text.
            logger.warning(
                "Audio run: note %d of %d failed: the %s step timed out.",
                index + 1,
                len(
                    notes
                ),
                timeout.step,
            )

            timed_out.append(
                (
                    index,
                    timeout.step,
                )
            )

            results.append(
                None
            )

            continue

        statistics = combine_statistics(
            statistics,
            result["statistics"],
        )

        # Where a run is, in counts only (CA-89): if a run ever stalls, the
        # last such line in the log says how far it got.
        logger.info(
            "Audio run: note %d of %d done.",
            index + 1,
            len(
                notes
            ),
        )

        results.append(
            result
        )

    return {
        "processed": len(notes),
        "statistics": statistics,
        "results": results,
        "timed_out": timed_out,
        "elapsed_seconds": max(
            0.0,
            perf_counter()
            - started_at,
        ),
    }
