RCE_AUDIO_TAG_PREFIX = "rce-audio::"

RCE_AUDIO_EXPORT_ONLY_TAG = (
    RCE_AUDIO_TAG_PREFIX
    + "export-only"
)

RCE_AUDIO_PENDING_TAG = (
    RCE_AUDIO_TAG_PREFIX
    + "pending"
)

RCE_AUDIO_IMMEDIATE_TAG = (
    RCE_AUDIO_TAG_PREFIX
    + "immediate"
)

RCE_AUDIO_PROCESSING_TAG = (
    RCE_AUDIO_TAG_PREFIX
    + "processing"
)

RCE_AUDIO_READY_TAG = (
    RCE_AUDIO_TAG_PREFIX
    + "ready"
)

RCE_AUDIO_FAILED_TAG = (
    RCE_AUDIO_TAG_PREFIX
    + "failed"
)

MANAGED_RCE_AUDIO_TAGS = (
    RCE_AUDIO_EXPORT_ONLY_TAG,
    RCE_AUDIO_PENDING_TAG,
    RCE_AUDIO_IMMEDIATE_TAG,
    RCE_AUDIO_PROCESSING_TAG,
    RCE_AUDIO_READY_TAG,
    RCE_AUDIO_FAILED_TAG,
)


def get_note_tags(
    note,
):
    """Return a defensive copy of one Anki note's tags."""

    tags = getattr(
        note,
        "tags",
        None,
    )

    if tags is None:
        return []

    return [
        str(tag)
        for tag in tags
    ]


def has_managed_audio_status(
    note,
):
    """Return whether a note participates in RCE audio automation."""

    managed = set(
        MANAGED_RCE_AUDIO_TAGS
    )

    return any(
        tag in managed
        for tag in get_note_tags(
            note
        )
    )


def set_audio_status(
    note,
    status_tags,
):
    """
    Replace only AnkiTTS-owned RCE audio-state tags.

    User tags and every non-audio RCE organizational tag remain intact.
    """

    requested = []
    requested_set = set()

    for tag in status_tags:
        if (
            tag not in MANAGED_RCE_AUDIO_TAGS
            or tag in requested_set
        ):
            continue

        requested.append(
            tag
        )

        requested_set.add(
            tag
        )

    result = [
        tag
        for tag in get_note_tags(
            note
        )
        if tag not in MANAGED_RCE_AUDIO_TAGS
    ]

    result.extend(
        requested
    )

    note.tags = result


def mark_ready_if_managed(
    note,
):
    """
    Mark a managed RCE note ready when audio publication succeeds.

    Ordinary notes and RCE notes generated outside the automation workflow
    retain their existing tags unchanged.
    """

    if not has_managed_audio_status(
        note
    ):
        return

    set_audio_status(
        note,
        [
            RCE_AUDIO_READY_TAG,
        ],
    )
