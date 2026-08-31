from rce_contract import (
    RCE_JOB_TYPE,
    create_rce_speech_plan_job,
    is_apparent_rce_note,
)


def get_mapped_field_names(
    settings,
):
    """Return all currently configured Anki field names."""

    field_names = {}

    for (
        side,
        side_mapping,
    ) in settings.field_mapping.items():
        field_names[
            f"{side}_text"
        ] = side_mapping["text"]

        field_names[
            f"{side}_audio"
        ] = side_mapping["audio"]

    return field_names


def get_missing_mapped_fields(
    note,
    settings,
):
    """Return configured fields that do not exist on the note."""

    return [
        field_name
        for field_name in get_mapped_field_names(
            settings
        ).values()
        if field_name not in note
    ]


def has_mapped_fields(
    note,
    settings,
):
    """Return whether the note contains all configured fields."""

    return not get_missing_mapped_fields(
        note,
        settings,
    )


def is_processable_note(
    note,
    settings,
):
    """
    Return whether a note belongs to either supported integration path.

    Apparent RCE notes remain processable here even when incomplete so
    strict contract validation can report the real error instead of
    silently skipping or treating them as generic notes.
    """

    return (
        is_apparent_rce_note(
            note
        )
        or has_mapped_fields(
            note,
            settings,
        )
    )


def create_field_definitions_from_note(
    note,
    settings,
):
    """
    Build engine field definitions from configured Anki fields.
    """

    missing_fields = get_missing_mapped_fields(
        note,
        settings,
    )

    if missing_fields:
        formatted_fields = "\n".join(
            missing_fields
        )

        raise ValueError(
            "The note does not contain the following "
            f"configured AnkiTTS fields:\n\n{formatted_fields}"
        )

    field_definitions = {}

    for (
        field_name,
        field_mapping,
    ) in settings.field_mapping.items():
        field_definitions[field_name] = {
            "text": note[
                field_mapping["text"]
            ],
            "speech_profile": field_mapping[
                "speech_profile"
            ],
            "enabled": True,
        }

    return field_definitions


def create_job_from_note(
    note,
    settings,
):
    """
    Create a structured RCE job or a generic fields-based engine job.

    An apparent RCE Card always takes precedence over generic field
    mappings so its semantic speech plans cannot be mistaken for HTML.
    """

    if is_apparent_rce_note(
        note
    ):
        return create_rce_speech_plan_job(
            note
        )

    return {
        "fields": create_field_definitions_from_note(
            note,
            settings,
        )
    }


def get_audio_field_destinations(
    audio_files,
    settings,
):
    """
    Resolve result keys to their authoritative Anki audio fields.

    Structured RCE results carry fixed destinations from the validated
    RCE contract. Generic results continue to use configurable mappings.
    """

    if (
        audio_files.get(
            "job_type"
        )
        == RCE_JOB_TYPE
    ):
        audio_fields = audio_files.get(
            "audio_fields"
        )

        if (
            not isinstance(
                audio_fields,
                dict,
            )
            or set(
                audio_fields
            )
            != {
                "front",
                "back",
            }
        ):
            raise ValueError(
                "The structured RCE audio result has invalid "
                "audio-field destinations."
            )

        return dict(
            audio_fields
        )

    return {
        field_name: field_mapping[
            "audio"
        ]
        for (
            field_name,
            field_mapping,
        ) in settings.field_mapping.items()
    }


def iter_processed_audio_outputs(
    audio_files,
    settings,
):
    """
    Yield processed result keys, Anki destinations, and filenames.

    A processed empty track deliberately yields a None filename so its
    destination field is cleared. An unprocessed generic field is omitted
    so its existing sound tag is preserved.
    """

    for (
        field_name,
        audio_field,
    ) in get_audio_field_destinations(
        audio_files,
        settings,
    ).items():
        if not audio_files.get(
            f"{field_name}_processed",
            True,
        ):
            continue

        yield (
            field_name,
            audio_field,
            audio_files.get(
                field_name
            ),
        )


def write_audio_fields(
    note,
    audio_files,
    settings,
):
    """Write sound tags into structured or configured audio fields."""

    for (
        _field_name,
        audio_field,
        filename,
    ) in iter_processed_audio_outputs(
        audio_files,
        settings,
    ):
        if audio_field not in note:
            raise ValueError(
                "The note does not contain the destination "
                f'AnkiTTS field "{audio_field}".'
            )

        if filename:
            field_value = (
                f"[sound:{filename}]"
            )
        else:
            field_value = ""

        note[
            audio_field
        ] = field_value
