from card_processor import (
    combine_statistics,
    empty_statistics,
    process_field_definitions,
)
from rce_contract import RCE_JOB_TYPE
from structured_audio import process_structured_job


def process_notes(
    notes,
    settings,
):
    """
    Process one or more generic or structured audio jobs.
    """

    results = []
    statistics = empty_statistics()

    for job in notes:
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

        statistics = combine_statistics(
            statistics,
            result["statistics"],
        )

        results.append(
            result
        )

    return {
        "processed": len(notes),
        "statistics": statistics,
        "results": results,
    }
