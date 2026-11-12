from time import perf_counter

from ankitts_log import get_logger
from card_processor import (
    combine_statistics,
    empty_statistics,
    process_field_definitions,
)
from rce_contract import RCE_JOB_TYPE
from structured_audio import process_structured_job


logger = get_logger(
    "batch"
)


class RunCancelled(Exception):
    """The run was stopped between notes (Anki is closing the profile)."""


def process_notes(
    notes,
    settings,
    should_cancel=None,
):
    """
    Process one or more generic or structured audio jobs.

    should_cancel, when given, is asked before each note; the run is stopped
    between notes with RunCancelled, so a run that cannot finish does not hold
    Anki open at exit. The check is a plain call that reads a flag.
    """

    results = []
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
            # Which job failed, for the audio audit (item C); the run is
            # still all-or-nothing.
            error.job_index = index

            raise

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
        "elapsed_seconds": max(
            0.0,
            perf_counter()
            - started_at,
        ),
    }
