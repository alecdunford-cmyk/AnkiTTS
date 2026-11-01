from __future__ import annotations

import os


def read_user_environment(
    name: str,
) -> str | None:
    """
    Return an environment variable, never logging or printing it.

    The process environment wins; otherwise the Windows User-scope value
    (HKCU\\Environment) is read, because Anki is often started before a
    newly set user variable reaches its environment.
    """

    value = os.environ.get(
        name
    )

    if value:
        return value

    try:
        import winreg

    except ImportError:
        return None

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            "Environment",
        ) as key:
            value, _kind = winreg.QueryValueEx(
                key,
                name,
            )

    except OSError:
        return None

    return value or None
