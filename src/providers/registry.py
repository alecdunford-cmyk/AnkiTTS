from __future__ import annotations

import atexit
import importlib
import json
import threading

from ankitts_log import get_logger


# id -> (module, class); imported lazily so a missing optional engine
# never breaks the others.
PROVIDER_CLASSES = {
    "pocket": (
        "providers.pocket",
        "PocketProvider",
    ),
    "fish": (
        "providers.fish",
        "FishProvider",
    ),
    "edge": (
        "providers.edge",
        "EdgeProvider",
    ),
}

logger = get_logger(
    "providers.registry"
)

_lock = threading.Lock()
_instances = {}
_override_chain = None


def known_provider_ids():
    return tuple(
        PROVIDER_CLASSES
    )


def _load_class(
    provider_id,
):
    module_name, class_name = PROVIDER_CLASSES[
        provider_id
    ]

    module = importlib.import_module(
        module_name
    )

    return getattr(
        module,
        class_name,
    )


def get_provider(
    provider_id,
    settings,
):
    """
    Return the provider instance for an id and its current config.

    Instances are reused while the config is unchanged, so one Pocket
    worker serves a whole batch; a changed config closes the old one.
    """

    if provider_id not in PROVIDER_CLASSES:
        raise KeyError(
            f'Unknown provider "{provider_id}".'
        )

    config = settings.get_provider_settings(
        provider_id
    )

    config_key = json.dumps(
        config,
        sort_keys=True,
        ensure_ascii=False,
    )

    with _lock:
        existing = _instances.get(
            provider_id
        )

        if (
            existing is not None
            and existing[0] == config_key
        ):
            return existing[1]

        provider = _load_class(
            provider_id
        )(
            config
        )

        _instances[
            provider_id
        ] = (
            config_key,
            provider,
        )

    if existing is not None:
        existing[1].close()

    return provider


def resolve_chain(
    settings,
):
    """Return the providers to try, in order, for these settings."""

    if _override_chain is not None:
        return list(
            _override_chain
        )

    providers = []

    for provider_id in settings.provider_chain:
        try:
            providers.append(
                get_provider(
                    provider_id,
                    settings,
                )
            )

        except Exception as error:
            logger.warning(
                "Provider %s could not be loaded and is skipped: %s",
                provider_id,
                error,
            )

    return providers


def set_override_chain(
    providers,
):
    """Tests only: force a fixed chain, or None to use settings again."""

    global _override_chain

    _override_chain = (
        None
        if providers is None
        else list(
            providers
        )
    )


def close_all():
    with _lock:
        instances = list(
            _instances.values()
        )

        _instances.clear()

    for _config_key, provider in instances:
        try:
            provider.close()

        except Exception as error:
            logger.warning(
                "Closing provider %s failed: %s",
                provider.provider_id,
                error,
            )


atexit.register(
    close_all
)
