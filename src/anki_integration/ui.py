"""
Everything that shows something to Alec goes through here, on the main thread.

Qt objects (dialogs, tooltips) may only be created on Anki's main thread. The
generation run does its long work on a background thread (CA-82) and hands back
to the main thread to publish; this module is the one place that knows how,
so no dialog, tooltip or notice function can be reached from another thread:
off the main thread a call is queued with Anki's own mechanism
(`mw.taskman.run_on_main`), and with no way to reach the main thread it is
dropped and logged, never made.
"""

from __future__ import annotations

import threading

from aqt.utils import tooltip

from ankitts_log import get_logger

logger = get_logger(
    "ui"
)

# A notice stays this long and needs no click (CA-83).
NOTICE_PERIOD_MS = 20000


def is_main_thread() -> bool:
    return (
        threading.current_thread()
        is threading.main_thread()
    )


def call_on_main(
    mw,
    closure,
):
    """Run closure on the main thread: now if already there, else queued."""

    if is_main_thread():
        closure()
        return

    taskman = getattr(
        mw,
        "taskman",
        None,
    )

    if taskman is None:
        logger.warning(
            "A message was dropped: it was raised off the main thread and "
            "Anki's task manager is not available to carry it over."
        )

        return

    taskman.run_on_main(
        closure
    )


def show_notice(
    mw,
    text,
    period=NOTICE_PERIOD_MS,
):
    """
    Tell Alec something without a box: Anki's tooltip, which closes by itself,
    needs no click and cannot hold the event loop.
    """

    call_on_main(
        mw,
        lambda: tooltip(
            text,
            period=period,
        ),
    )
