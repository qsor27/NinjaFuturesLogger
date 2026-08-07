"""Shared query-string parameter parsing for route blueprints.

Routes catch BadParam and map it to the standard 400 JSON error:

    try:
        limit = int_arg(request.args, "limit", default=50, lo=1, hi=500)
    except BadParam as e:
        return jsonify({"error": str(e)}), 400
"""


class BadParam(ValueError):
    """A query parameter failed to parse or fell outside its allowed range."""


def int_arg(
    args,
    key: str,
    *,
    default: int | None,
    lo: int | None = None,
    hi: int | None = None,
) -> int | None:
    """Parse an optional integer query parameter.

    - Absent or empty value -> ``default``, returned as-is (bounds are not
      applied to defaults; callers own their defaults).
    - Non-integer text -> BadParam.
    - Parsed value outside [lo, hi] -> BadParam (each bound optional).

    ``args`` is any mapping with ``.get`` — ``request.args`` or a plain dict.
    """
    raw = args.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise BadParam(f"{key} must be an integer, got {raw!r}") from None
    if lo is not None and value < lo:
        raise BadParam(f"{key} must be >= {lo}")
    if hi is not None and value > hi:
        raise BadParam(f"{key} must be <= {hi}")
    return value
