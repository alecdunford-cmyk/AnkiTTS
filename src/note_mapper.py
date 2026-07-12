SUPPORTED_SIDES = (
    "front",
    "back",
)


def get_side_mapping(
    settings,
    side,
):
    """Return the configured text/audio mapping for one side."""

    if side not in SUPPORTED_SIDES:
        raise ValueError(
            f'Unsupported audio side: "{side}".'
        )

    return settings.field_mapping[
        side
    ]


def get_mapped_field_names(
    settings,
):
    """Return all currently configured Anki field names."""

    field_names = {}

    for side in SUPPORTED_SIDES:
        side_mapping = get_side_mapping(
            settings,
            side,
        )

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


def field_has_audio(
    note,
    field_name,
):
    """Return whether an audio field already contains content."""

    return bool(
        note[field_name].strip()
    )


def create_field_definitions_from_note(
    note,
    settings,
    generate_front=True,
    generate_back=True,
):
    """
    Build engine field definitions from configured Anki fields.

    This introduces the configuration-driven representation while
    preserving the existing front/back job interface.
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

    generation_settings = {
        "front": {
            "enabled": generate_front,
            "language": settings.front_language,
        },
        "back": {
            "enabled": generate_back,
            "language": None,
        },
    }

    field_definitions = {}

    for side in SUPPORTED_SIDES:
        side_mapping = get_side_mapping(
            settings,
            side,
        )

        field_definitions[side] = {
            "text": note[
                side_mapping["text"]
            ],
            "language": generation_settings[
                side
            ]["language"],
            "enabled": generation_settings[
                side
            ]["enabled"],
        }

    return field_definitions


def create_note_job(
    front,
    back,
    front_language=None,
    generate_front=True,
    generate_back=True,
):
    """Create the engine's current front/back audio job."""

    return {
        "front": front,
        "back": back,
        "front_language": front_language,
        "generate_front": generate_front,
        "generate_back": generate_back,
    }


def create_job_from_note(
    note,
    settings,
    generate_front=True,
    generate_back=True,
):
    """Create a fields-based engine job from an Anki note."""

    return {
        "fields": create_field_definitions_from_note(
            note,
            settings,
            generate_front=generate_front,
            generate_back=generate_back,
        )
    }


def get_generation_requirements(
    note,
    settings,
):
    """
    Return which sides need audio.

    This preserves the Browser command's missing-only behavior.
    """

    requirements = {}

    for side in SUPPORTED_SIDES:
        side_mapping = get_side_mapping(
            settings,
            side,
        )

        requirements[
            f"generate_{side}"
        ] = not field_has_audio(
            note,
            side_mapping["audio"],
        )

    return requirements


def write_audio_fields(
    note,
    audio_files,
    settings,
):
    """Write sound tags into the configured audio fields."""

    for side in SUPPORTED_SIDES:
        if not audio_files.get(
            f"{side}_processed",
            True,
        ):
            continue

        side_mapping = get_side_mapping(
            settings,
            side,
        )

        filename = audio_files.get(
            side
        )

        if filename:
            field_value = (
                f"[sound:{filename}]"
            )
        else:
            field_value = ""

        note[
            side_mapping["audio"]
        ] = field_value