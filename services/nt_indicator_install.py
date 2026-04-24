"""Copy ExecutionExporter.cs into a target NinjaTrader Indicators dir.

Three conflict policies:
  overwrite       - replace dest file unconditionally
  keep            - leave dest alone if it already exists
  backup_replace  - rename dest to <name>.bak-YYYYMMDD-HHMMSS, then copy source
"""

import shutil
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

OnConflict = Literal["overwrite", "keep", "backup_replace"]


class InstallResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool
    dest_path: Path | None = None
    backup_path: Path | None = None
    error: str | None = None


def install_indicator(
    *,
    source: Path,
    dest_dir: Path,
    on_conflict: OnConflict,
) -> InstallResult:
    if not source.is_file():
        return InstallResult(success=False, error=f"source not found: {source}")
    if not dest_dir.is_dir():
        return InstallResult(success=False, error=f"dest directory not found: {dest_dir}")

    dest = dest_dir / source.name
    backup_path: Path | None = None

    if dest.exists():
        if on_conflict == "keep":
            return InstallResult(success=True, dest_path=dest, backup_path=None)
        if on_conflict == "backup_replace":
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup_path = dest.with_name(f"{dest.name}.bak-{stamp}")
            shutil.move(str(dest), str(backup_path))
        # "overwrite" falls through to copy without backup

    shutil.copy2(str(source), str(dest))
    return InstallResult(success=True, dest_path=dest, backup_path=backup_path)
