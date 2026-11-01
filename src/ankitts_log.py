from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading


LOGGER_NAME = "ankitts"
LOG_FILE_NAME = "ankitts.log"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 5

_configure_lock = threading.Lock()
_configured_path: Path | None = None


def default_log_directory() -> Path:
    """
    Return the add-on's user_files/logs folder.

    Anki preserves user_files across add-on updates. The engine runs either
    from the repository (src next to addon) or from a packaged add-on
    (src inside the add-on folder); both resolve to the same add-on folder.
    ANKITTS_LOG_DIR overrides the location.
    """

    override = os.environ.get(
        "ANKITTS_LOG_DIR"
    )

    if override:
        return Path(
            override
        )

    project_root = (
        Path(__file__)
        .resolve()
        .parent
        .parent
    )

    if (
        project_root
        / "addon"
    ).is_dir():
        addon_dir = (
            project_root
            / "addon"
        )
    else:
        addon_dir = project_root

    return (
        addon_dir
        / "user_files"
        / "logs"
    )


def configure_logging(
    log_directory: Path | None = None,
) -> Path:
    """Attach the rotating file handler once and return the log path."""

    global _configured_path

    with _configure_lock:
        if _configured_path is not None:
            return _configured_path

        directory = Path(
            log_directory
            or default_log_directory()
        )

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        log_path = (
            directory
            / LOG_FILE_NAME
        )

        handler = RotatingFileHandler(
            log_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )

        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s "
                "[%(threadName)s] %(name)s: %(message)s"
            )
        )

        logger = logging.getLogger(
            LOGGER_NAME
        )

        logger.setLevel(
            logging.INFO
        )

        logger.addHandler(
            handler
        )

        logger.propagate = False

        _configured_path = log_path

        return log_path


def get_logger(
    name: str,
) -> logging.Logger:
    """Return a child of the AnkiTTS logger, configuring it on first use."""

    try:
        configure_logging()

    except OSError:
        pass

    return logging.getLogger(
        f"{LOGGER_NAME}.{name}"
    )


def text_preview(
    text: str,
    limit: int = 80,
) -> str:
    """Shorten text for a log line."""

    if len(
        text
    ) <= limit:
        return text

    return (
        text[
            : limit - 3
        ]
        + "..."
    )
