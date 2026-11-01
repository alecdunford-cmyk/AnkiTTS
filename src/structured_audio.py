from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

from cache import get_structured_audio_path
from card_processor import (
    combine_statistics,
    empty_statistics,
)
from generator import (
    SynthesisFailed,
    create_audio,
)
from rce_contract import RCE_JOB_TYPE
from settings import SpeechProfile
from stitcher import stitch_structured_audio
from structured_processor import (
    ResolvedSpeechTrack,
    resolve_speech_plan,
)


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

MAX_PARALLEL_SYNTHESIS = 3


class StructuredAudioProcessingError(
    RuntimeError
):
    """Raised when a complete structured RCE card cannot be synthesized."""


def cleanup_orphaned_temporary_audio_files(
    output_directory=OUTPUT_DIR,
):
    """Remove only unpublished structured-track temporary artifacts."""

    directory = Path(
        output_directory
    )

    if not directory.exists():
        return 0

    removed = 0

    for path in directory.iterdir():
        is_structured_temporary = (
            path.name.startswith(
                ".rce_"
            )
            or path.name.startswith(
                "..rce_"
            )
        )

        if (
            not path.is_file()
            or not is_structured_temporary
            or not (
                path.name.endswith(
                    ".pending"
                )
                or path.name.endswith(
                    ".tmp"
                )
            )
        ):
            continue

        try:
            path.unlink()

        except FileNotFoundError:
            continue

        removed += 1

    return removed


def process_structured_job(
    job,
    settings,
):
    """
    Synthesize both sides of one structured RCE job transactionally.

    Segment cache files may survive a failed attempt, but final track files
    are published only after every nonempty side has stitched successfully.
    """

    if (
        not isinstance(
            job,
            dict,
        )
        or job.get(
            "job_type"
        )
        != RCE_JOB_TYPE
    ):
        raise StructuredAudioProcessingError(
            "A valid structured RCE job is required."
        )

    rce_card_id = job.get(
        "rce_card_id"
    )

    speech_plans = job.get(
        "speech_plans"
    )

    audio_fields = job.get(
        "audio_fields"
    )

    if (
        not isinstance(
            rce_card_id,
            str,
        )
        or not rce_card_id
        or not isinstance(
            speech_plans,
            dict,
        )
        or not isinstance(
            audio_fields,
            dict,
        )
    ):
        raise StructuredAudioProcessingError(
            "The structured RCE job contract is incomplete."
        )

    try:
        resolved_tracks = {
            side: resolve_speech_plan(
                speech_plans[
                    side
                ],
                settings,
            )
            for side in (
                "front",
                "back",
            )
        }

    except (
        KeyError,
        ValueError,
    ) as error:
        raise StructuredAudioProcessingError(
            f"RCE speech resolution failed: {error}"
        ) from error

    statistics = empty_statistics()
    prepared_tracks = {}

    try:
        for side in (
            "front",
            "back",
        ):
            prepared, side_statistics = _prepare_track(
                rce_card_id=rce_card_id,
                track=resolved_tracks[
                    side
                ],
                settings=settings,
            )

            prepared_tracks[
                side
            ] = prepared

            statistics = combine_statistics(
                statistics,
                side_statistics,
            )

        _stitch_prepared_tracks(
            prepared_tracks
        )

    except StructuredAudioProcessingError:
        _remove_pending_tracks(
            prepared_tracks
        )

        raise

    except Exception as error:
        _remove_pending_tracks(
            prepared_tracks
        )

        raise StructuredAudioProcessingError(
            f"Structured RCE audio processing failed: {error}"
        ) from error

    result = {
        "job_type": RCE_JOB_TYPE,
        "rce_card_id": rce_card_id,
        "audio_fields": dict(
            audio_fields
        ),
        "statistics": statistics,
    }

    for side in (
        "front",
        "back",
    ):
        prepared = prepared_tracks[
            side
        ]

        result[
            side
        ] = prepared[
            "filename"
        ]

        result[
            f"{side}_processed"
        ] = True

    return result


def create_structured_track_filename(
    rce_card_id,
    track,
    provider_identity,
):
    """
    Create a deterministic filename from schedule and synthesis inputs.

    provider_identity is one identity for every segment or a sequence
    with one identity per segment; a track may mix providers.
    """

    if not isinstance(
        track,
        ResolvedSpeechTrack,
    ):
        raise StructuredAudioProcessingError(
            "A resolved speech track is required."
        )

    if isinstance(
        provider_identity,
        dict,
    ):
        segment_identities = [
            provider_identity
        ] * len(
            track.segments
        )
    else:
        segment_identities = list(
            provider_identity
        )

    if len(
        segment_identities
    ) != len(
        track.segments
    ):
        raise StructuredAudioProcessingError(
            "One provider identity is required per segment."
        )

    identity = {
        "rce_card_id": rce_card_id,
        "schema_version": (
            track.schema_version
        ),
        "side": track.side,
        "segments": [
            {
                "provider_identity": dict(
                    segment_identity
                ),
                "text": segment.text,
                "language": segment.language,
                "profile_key": (
                    segment.resolved_profile_key
                ),
                "profile_language": (
                    segment.resolved_profile_language
                ),
                "voice": segment.voice,
                "rate": segment.edge_rate,
                "volume": segment.volume,
                "pitch": segment.pitch,
                "pause_before_milliseconds": (
                    segment.pause_before_milliseconds
                ),
                "pause_after_milliseconds": (
                    segment.pause_after_milliseconds
                ),
            }
            for segment, segment_identity in zip(
                track.segments,
                segment_identities,
            )
        ],
    }

    serialized_identity = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )

    track_hash = hashlib.sha256(
        serialized_identity.encode(
            "utf-8"
        )
    ).hexdigest()[
        :24
    ]

    return (
        f"rce_{track.side}_{track_hash}.mp3"
    )


def _prepare_track(
    rce_card_id,
    track,
    settings,
):
    statistics = empty_statistics()

    if not track.segments:
        return (
            {
                "filename": None,
                "final_path": None,
                "pending_path": None,
                "segments": [],
            },
            statistics,
        )

    segment_requests = [
        _create_segment_request(
            segment
        )
        for segment in track.segments
    ]

    unique_requests = {}

    for request in segment_requests:
        unique_requests.setdefault(
            request[
                "key"
            ],
            request,
        )

    results = _synthesize_missing_segments(
        rce_card_id,
        list(
            unique_requests.values()
        ),
        settings,
    )

    counted_paths = set()
    audio_segments = []
    segment_identities = []

    for request in segment_requests:
        segment = request[
            "segment"
        ]

        synthesis = results[
            request[
                "key"
            ]
        ]

        if (
            synthesis.generated
            and synthesis.path
            not in counted_paths
        ):
            statistics[
                "generated"
            ] += 1

        else:
            statistics[
                "cached"
            ] += 1

        counted_paths.add(
            synthesis.path
        )

        segment_identities.append(
            synthesis.identity
        )

        audio_segments.append(
            {
                "file": str(
                    synthesis.path
                ),
                "pause_before_milliseconds": (
                    segment.pause_before_milliseconds
                ),
                "pause_after_milliseconds": (
                    segment.pause_after_milliseconds
                ),
            }
        )

    filename = create_structured_track_filename(
        rce_card_id,
        track,
        segment_identities,
    )

    final_path = OUTPUT_DIR / filename

    pending_path = final_path.with_name(
        f".{final_path.name}.pending"
    )

    if pending_path.exists():
        pending_path.unlink()

    return (
        {
            "filename": filename,
            "final_path": final_path,
            "pending_path": pending_path,
            "segments": audio_segments,
        },
        statistics,
    )


def _create_segment_request(
    segment,
):
    """Describe one segment's synthesis inputs; scheduling is excluded."""

    profile = SpeechProfile(
        language=segment.resolved_profile_language,
        voice=segment.voice,
        rate=segment.edge_rate,
        volume=segment.volume,
        pitch=segment.pitch,
    )

    return {
        "segment": segment,
        "profile": profile,
        "key": (
            segment.text,
            segment.language,
            segment.resolved_profile_key,
            profile,
        ),
    }


def _synthesize_missing_segments(
    rce_card_id,
    requests,
    settings,
):
    """Resolve every unique segment through the provider chain."""

    if not requests:
        return {}

    worker_count = min(
        MAX_PARALLEL_SYNTHESIS,
        len(
            requests
        ),
    )

    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="ankitts-rce",
    ) as executor:
        futures = [
            (
                request[
                    "key"
                ],
                executor.submit(
                    _synthesize_segment,
                    rce_card_id,
                    request,
                    settings,
                ),
            )
            for request in requests
        ]

        return {
            key: future.result()
            for key, future in futures
        }


def _synthesize_segment(
    rce_card_id,
    request,
    settings,
):
    segment = request[
        "segment"
    ]

    def cache_path_for(
        identity,
        fields,
    ):
        provider_fields = dict(
            identity
        )

        return get_structured_audio_path(
            provider=provider_fields.pop(
                "provider"
            ),
            provider_model=provider_fields.pop(
                "provider_model"
            ),
            provider_version=provider_fields.pop(
                "provider_version"
            ),
            text=segment.text,
            language=segment.language,
            profile_key=(
                segment.resolved_profile_key
            ),
            **fields,
            **provider_fields,
        )

    try:
        return create_audio(
            text=segment.text,
            language=segment.resolved_profile_language,
            profile=request[
                "profile"
            ],
            cache_path_for=cache_path_for,
            settings=settings,
        )

    except SynthesisFailed as error:
        if error.no_audio_only:
            raise StructuredAudioProcessingError(
                "No provider returned usable audio after retries for "
                f'RCE card "{rce_card_id}", segment '
                f'"{segment.segment_id}", text '
                f"{_format_text_preview(segment.text)}, language "
                f'"{segment.language}", voice "{segment.voice}", '
                f'rate "{segment.edge_rate}" ({error}).'
            ) from error

        raise StructuredAudioProcessingError(
            "Synthesis failed for RCE segment "
            f'"{segment.segment_id}": {error}'
        ) from error


def _format_text_preview(
    text,
    limit=160,
):
    preview = text

    if len(
        preview
    ) > limit:
        preview = (
            preview[
                : limit - 3
            ]
            + "..."
        )

    return json.dumps(
        preview,
        ensure_ascii=False,
    )


def _stitch_prepared_tracks(
    prepared_tracks,
):
    stitched_tracks = []

    try:
        for side in (
            "front",
            "back",
        ):
            prepared = prepared_tracks[
                side
            ]

            pending_path = prepared[
                "pending_path"
            ]

            if pending_path is None:
                continue

            stitch_structured_audio(
                prepared[
                    "segments"
                ],
                str(
                    pending_path
                ),
            )

            if not _is_nonempty_file(
                pending_path
            ):
                raise StructuredAudioProcessingError(
                    "Structured stitching produced no usable "
                    f"{side} track."
                )

            stitched_tracks.append(
                prepared
            )

    except Exception:
        for prepared in stitched_tracks:
            pending_path = prepared[
                "pending_path"
            ]

            if pending_path.exists():
                pending_path.unlink()

        raise

    for prepared in stitched_tracks:
        prepared[
            "pending_path"
        ].replace(
            prepared[
                "final_path"
            ]
        )


def _remove_pending_tracks(
    prepared_tracks,
):
    for prepared in prepared_tracks.values():
        pending_path = prepared.get(
            "pending_path"
        )

        if (
            pending_path is not None
            and pending_path.exists()
        ):
            pending_path.unlink()


def _is_nonempty_file(
    path,
):
    return (
        path.exists()
        and path.is_file()
        and path.stat().st_size > 0
    )
