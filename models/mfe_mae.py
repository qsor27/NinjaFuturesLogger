from pydantic import Field, model_validator

from models.base import StrictModel


class MfeMaeResult(StrictModel):
    """Excursion result for a single closed position. Computed from 1m bars
    over [entry_time, exit_time]. See docs/superpowers/specs/
    2026-04-21-mfe-mae-design.md for the formulas."""

    mfe_dollars: float = Field(ge=0.0)
    mae_dollars: float = Field(le=0.0)
    mfe_time: int
    mae_time: int
    coverage: float = Field(ge=0.0, le=1.0)
    capture_efficiency: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_efficiency: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _at_most_one_efficiency(self) -> "MfeMaeResult":
        if self.capture_efficiency is not None and self.risk_efficiency is not None:
            raise ValueError(
                "MfeMaeResult: only one of capture_efficiency / risk_efficiency may be set"
            )
        return self
