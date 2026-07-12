from card_processor import (
    combine_statistics,
    empty_statistics,
    process_card,
    process_field_definitions,
)


def process_notes(
    notes,
    settings,
):
    """
    Process one or more audio-generation jobs.

    Jobs may contain either:
        fields

    or the legacy keys:
        front
        back
        front_language
        generate_front
        generate_back
    """

    results = []
    statistics = empty_statistics()

    for job in notes:
        if "fields" in job:
            result = process_field_definitions(
                job["fields"],
                settings,
            )
        else:
            result = process_card(
                front=job["front"],
                back=job["back"],
                front_language=job.get(
                    "front_language"
                ),
                settings=settings,
                generate_front=job.get(
                    "generate_front",
                    True,
                ),
                generate_back=job.get(
                    "generate_back",
                    True,
                ),
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