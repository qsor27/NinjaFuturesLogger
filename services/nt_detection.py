"""Locate a NinjaTrader 8 install on the current machine.

Production callers pass `documents_override=None` and the function
defaults to `Path.home() / "Documents"`. Tests pass a tmp_path so we
never touch the real user profile.
"""

from pathlib import Path

from pydantic import BaseModel


class DetectionResult(BaseModel):
    found: bool
    indicators_path: Path | None

    class Config:
        arbitrary_types_allowed = True


def detect_ninjatrader(documents_override: Path | None = None) -> DetectionResult:
    documents = documents_override or (Path.home() / "Documents")
    indicators = documents / "NinjaTrader 8" / "bin" / "Custom" / "Indicators"
    if indicators.is_dir():
        return DetectionResult(found=True, indicators_path=indicators)
    return DetectionResult(found=False, indicators_path=None)
