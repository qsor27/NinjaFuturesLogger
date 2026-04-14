"""Chart default settings.

Plan 13 ships this as a module-level stub. Plan 16 will replace the body of
get_defaults() with a SELECT against a chart_defaults table backed by a
settings page. The function name is the seam: routes and the frontend pickup
helper both go through get_defaults(), so Plan 16's swap is invisible to
them.

Do NOT add a database read here. Do NOT add a chart_defaults table. Both
belong to Plan 16.
"""

DEFAULT_TIMEFRAME = "1m"
VOLUME_VISIBLE_DEFAULT = True


def get_defaults() -> dict:
    """Return the current chart default settings.

    A fresh dict is returned on every call so a caller mutating the result
    cannot poison subsequent calls.
    """
    return {
        "default_timeframe": DEFAULT_TIMEFRAME,
        "volume_visible_default": VOLUME_VISIBLE_DEFAULT,
    }
