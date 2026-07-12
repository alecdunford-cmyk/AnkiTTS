def get_mapped_field_names(settings):
    """Return the four configured Anki field names."""

    return {
        "front_text": settings.front_text_field,
        "back_text": settings.back_text_field,
        "front_audio": settings.front_audio_field,
        "back_audio": settings.back_audio_field,
    }


def get_missing_mapped_fields(
    note,
    settings,
):
    """Return configured fields that do not exist on the note."""

    field_names = get_mapped_field_names(
        settings
    )

    return [
        field_name
        for field_name in field_names.values()
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


def create_note_job(
    front,
    back,
    front_language=None,
    generate_front=True,
    generate_back=True,
):
    """Create a generic audio-generation job."""

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
    """Create an audio job using the configured note fields."""

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

    return create_note_job(
        front=note[
            settings.front_text_field
        ],
        back=note[
            settings.back_text_field
        ],
        generate_front=generate_front,
        generate_back=generate_back,
    )


def get_generation_requirements(
    note,
    settings,
):
    """
    Return which sides need audio.

    This is intended for missing-only batch generation.
    """

    return {
        "generate_front": not field_has_audio(
            note,
            settings.front_audio_field,
        ),
        "generate_back": not field_has_audio(
            note,
            settings.back_audio_field,
        ),
    }


def write_audio_fields(
    note,
    audio_files,
    settings,
):
    """Write generated sound tags into the configured audio fields."""

    if audio_files.get(
        "front_processed",
        True,
    ):
        front_filename = audio_files.get(
            "front"
        )

        if front_filename:
            note[
                settings.front_audio_field
            ] = f"[sound:{front_filename}]"
        else:
            note[
                settings.front_audio_field
            ] = ""

    if audio_files.get(
        "back_processed",
        True,
    ):
        back_filename = audio_files.get(
            "back"
        )

        if back_filename:
            note[
                settings.back_audio_field
            ] = f"[sound:{back_filename}]"
        else:
            note[
                settings.back_audio_field
            ] = ""