from card_processor import (
    combine_statistics,
    empty_statistics,
    process_card,
)


def process_notes(
    notes,
    settings,
):
    """
    Process one or more audio-generation jobs.

    Each job may contain:
        front
        back
        front_language
        generate_front
        generate_back
    """

    results = []
    statistics = empty_statistics()

    for note in notes:
        result = process_card(
            front=note["front"],
            back=note["back"],
            front_language=note.get(
                "front_language"
            ),
            settings=settings,
            generate_front=note.get(
                "generate_front",
                True,
            ),
            generate_back=note.get(
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