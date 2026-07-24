from card_processor import (
    combine_statistics,
    empty_statistics,
    process_field_definitions,
)
from rce_contract import RCE_JOB_TYPE


def process_notes(
    notes,
    settings,
):
    """
    Process one or more field-definition audio jobs.

    Each job must contain:
        fields
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
            raise ValueError(
                "Structured RCE speech-plan processing is not "
                "available until AnkiTTS Phase 1C."
            )

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
