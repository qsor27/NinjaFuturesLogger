from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Project-wide base for typed contracts.

    `extra="forbid"` enforces that we never silently swallow fields that
    don't belong; `strict=True` blocks Pydantic's permissive coercion so
    that `int` fields refuse strings, etc.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=False)
