from card_processor import (
    combine_statistics,
    empty_statistics,
    process_field_definitions,
)


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