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
    """Create a fields-based engine job from an Anki note."""

    return {
        "fields": create_field_definitions_from_note(
            note,
            settings,
        )
    }


def write_audio_fields(
    note,
    audio_files,
    settings,
):
    """Write sound tags into the configured audio fields."""

    for (
        field_name,
        field_mapping,
    ) in settings.field_mapping.items():
        if not audio_files.get(
            f"{field_name}_processed",
            True,
        ):
            continue

        filename = audio_files.get(
            field_name
        )

        if filename:
            field_value = (
                f"[sound:{filename}]"
            )
        else:
            field_value = ""

        note[
            field_mapping["audio"]
        ] = field_value