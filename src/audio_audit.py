"""
The audio audit (review batch 2, item C; CA-71 (3), "never silent").

After a generation run AnkiTTS reports, for the sides that carry a schema
version 2 speech plan, every note whose side ended without audio it should
have. Three counts, each with its note ids; never a segment's text:

  silent    the plan has spoken segments but no audio was produced or attached
            (no track, the track file missing, the audio field empty, or the
            run failed before the note got any)
  empty     the plan has no spoken segment at all (no segments, or every
            segment spoken false): RCE's defect, caught here if one remains
  rejected  the validator refused the plan, so its segments cannot be read

The generic path's notes and schema version 1 plans are not audited. This
module is pure: it knows nothing of Anki, so the checks run with plain dicts
and folders in tests.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)
from pathlib import Path

SIDES = (
    "front",
    "back",
)

AUDITED_SCHEMA_VERSION = 2

SPOKEN = "spoken"
EMPTY = "empty"

# Fixed phrases only: a reason never carries an exception's text or a
# segment's, because those can hold card text.
REASON_NO_TRACK = "no track was produced"
REASON_FILE_MISSING = "the track file is missing from Anki's media folder"
REASON_FIELD_EMPTY = "the audio field is empty"
REASON_SYNTHESIS_FAILED = "synthesis failed"
REASON_COPY_FAILED = "the track could not be copied into Anki's media folder"
REASON_NO_SPOKEN_SEGMENT = "the plan has no spoken segment"
REASON_PLAN_REFUSED = "the plan was refused by the validator"


@dataclass(frozen=True)
class Finding:
    note_id: object
    side: str
    reason: str


@dataclass
class AudioAudit:
    silent: list[Finding] = field(
        default_factory=list
    )
    empty: list[Finding] = field(
        default_factory=list
    )
    rejected: list[Finding] = field(
        default_factory=list
    )

    @property
    def is_clean(
        self,
    ) -> bool:
        return not (
            self.silent
            or self.empty
            or self.rejected
        )

    def counts(
        self,
    ) -> dict[str, int]:
        return {
            "silent": len(
                self.silent
            ),
            "empty": len(
                self.empty
            ),
            "rejected": len(
                self.rejected
            ),
        }

    def note_ids(
        self,
    ) -> dict[str, list]:
        return {
            kind: [
                finding.note_id
                for finding in findings
            ]
            for kind, findings in (
                (
                    "silent",
                    self.silent,
                ),
                (
                    "empty",
                    self.empty,
                ),
                (
                    "rejected",
                    self.rejected,
                ),
            )
        }

    def lines(
        self,
    ) -> list[str]:
        """The report: quiet when clean, impossible to miss when not."""

        if self.is_clean:
            return [
                "Audio audit: 0 silent sides, 0 empty sides, "
                "0 rejected plans."
            ]

        counts = self.counts()

        total = sum(
            counts.values()
        )

        lines = [
            "*** AUDIO AUDIT: "
            f"{total} SIDE{'S' if total != 1 else ''} "
            "WITHOUT AUDIO THAT SHOULD HAVE SOME ***",
        ]

        for (
            label,
            findings,
        ) in (
            (
                "silent",
                self.silent,
            ),
            (
                "empty",
                self.empty,
            ),
            (
                "rejected",
                self.rejected,
            ),
        ):
            noun = (
                "plan"
                if label == "rejected"
                else "side"
            )

            count = len(
                findings
            )

            lines.append(
                f"{count} {label} {noun}{'s' if count != 1 else ''}"
                + (
                    ": "
                    + "; ".join(
                        f"note {finding.note_id} "
                        f"({finding.side}: {finding.reason})"
                        for finding in findings
                    )
                    if findings
                    else ""
                )
            )

        return lines

    def message(
        self,
    ) -> str:
        return "\n".join(
            self.lines()
        )

    def log_line(
        self,
    ) -> str:
        """One line for the log: counts and note ids, never text."""

        counts = self.counts()

        ids = self.note_ids()

        return (
            f"Audio audit: {counts['silent']} silent sides "
            f"{ids['silent']}, {counts['empty']} empty sides "
            f"{ids['empty']}, {counts['rejected']} rejected plans "
            f"{ids['rejected']}."
        )


def side_status(
    plan,
) -> str | None:
    """
    SPOKEN if the plan has a spoken segment, EMPTY if it has none, and None
    for a plan the audit does not cover (anything but schema version 2).
    """

    if (
        getattr(
            plan,
            "schema_version",
            None,
        )
        != AUDITED_SCHEMA_VERSION
    ):
        return None

    if any(
        segment.spoken
        for segment in plan.segments
    ):
        return SPOKEN

    return EMPTY


def _audited_sides(
    job,
):
    """(side, status) for each side of a structured job that is audited."""

    plans = job.get(
        "speech_plans"
    )

    if not isinstance(
        plans,
        dict,
    ):
        return

    for side in SIDES:
        status = side_status(
            plans.get(
                side
            )
        )

        if status is not None:
            yield (
                side,
                status,
            )


def audit_job(
    audit: AudioAudit,
    note_id,
    job,
) -> None:
    """Before generation: the sides whose plan has nothing to speak."""

    for (
        side,
        status,
    ) in _audited_sides(
        job
    ):
        if status == EMPTY:
            audit.empty.append(
                Finding(
                    note_id,
                    side,
                    REASON_NO_SPOKEN_SEGMENT,
                )
            )


def audit_rejected(
    audit: AudioAudit,
    note_id,
    sides,
) -> None:
    """A plan the validator refused: one finding per refused side."""

    for side in sides:
        audit.rejected.append(
            Finding(
                note_id,
                side,
                REASON_PLAN_REFUSED,
            )
        )


def audit_unfinished(
    audit: AudioAudit,
    note_id,
    job,
    reason: str,
) -> None:
    """
    A note the run did not finish (synthesis failed, the copy failed): each
    side with spoken segments got no audio.
    """

    for (
        side,
        status,
    ) in _audited_sides(
        job
    ):
        if status == SPOKEN:
            audit.silent.append(
                Finding(
                    note_id,
                    side,
                    reason,
                )
            )


def audit_published(
    audit: AudioAudit,
    note_id,
    job,
    result,
    note,
    media_folder,
    destinations,
) -> None:
    """
    After the audio was written into the note: each side with spoken segments
    must have a track, that track in Anki's media folder, and a sound tag for
    it in the side's audio field.
    """

    for (
        side,
        status,
    ) in _audited_sides(
        job
    ):
        if status != SPOKEN:
            continue

        filename = result.get(
            side
        )

        if not filename:
            reason = REASON_NO_TRACK

        else:
            media_file = (
                Path(
                    media_folder
                )
                / filename
            )

            field_name = destinations.get(
                side
            )

            value = (
                note[
                    field_name
                ]
                if field_name is not None
                and field_name in note
                else ""
            )

            if (
                not media_file.is_file()
                or media_file.stat().st_size == 0
            ):
                reason = REASON_FILE_MISSING

            elif (
                f"[sound:{filename}]"
                not in str(
                    value
                )
            ):
                reason = REASON_FIELD_EMPTY

            else:
                continue

        audit.silent.append(
            Finding(
                note_id,
                side,
                reason,
            )
        )
