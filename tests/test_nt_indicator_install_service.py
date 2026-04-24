from pathlib import Path

import pytest

from services.nt_indicator_install import InstallResult, install_indicator


@pytest.fixture
def source_file(tmp_path: Path) -> Path:
    src = tmp_path / "src" / "ExecutionExporter.cs"
    src.parent.mkdir()
    src.write_text("// current source")
    return src


def test_copies_file_when_dest_does_not_exist(source_file: Path, tmp_path: Path):
    dest_dir = tmp_path / "indicators"
    dest_dir.mkdir()
    result = install_indicator(source=source_file, dest_dir=dest_dir, on_conflict="backup_replace")
    assert isinstance(result, InstallResult)
    assert result.success is True
    assert result.dest_path == dest_dir / "ExecutionExporter.cs"
    assert result.backup_path is None
    assert result.dest_path.read_text() == "// current source"


def test_keep_existing_does_not_overwrite(source_file: Path, tmp_path: Path):
    dest_dir = tmp_path / "indicators"
    dest_dir.mkdir()
    existing = dest_dir / "ExecutionExporter.cs"
    existing.write_text("// existing content")
    result = install_indicator(source=source_file, dest_dir=dest_dir, on_conflict="keep")
    assert result.success is True
    assert result.backup_path is None
    assert existing.read_text() == "// existing content"


def test_overwrite_replaces_existing_without_backup(source_file: Path, tmp_path: Path):
    dest_dir = tmp_path / "indicators"
    dest_dir.mkdir()
    (dest_dir / "ExecutionExporter.cs").write_text("// existing")
    result = install_indicator(source=source_file, dest_dir=dest_dir, on_conflict="overwrite")
    assert result.success is True
    assert result.backup_path is None
    assert (dest_dir / "ExecutionExporter.cs").read_text() == "// current source"


def test_backup_replace_renames_existing_then_writes_source(source_file: Path, tmp_path: Path):
    dest_dir = tmp_path / "indicators"
    dest_dir.mkdir()
    (dest_dir / "ExecutionExporter.cs").write_text("// old")
    result = install_indicator(source=source_file, dest_dir=dest_dir, on_conflict="backup_replace")
    assert result.success is True
    assert result.backup_path is not None
    assert result.backup_path.exists()
    assert result.backup_path.read_text() == "// old"
    assert (dest_dir / "ExecutionExporter.cs").read_text() == "// current source"
    assert result.backup_path.name.startswith("ExecutionExporter.cs.bak-")


def test_returns_error_when_dest_dir_does_not_exist(source_file: Path, tmp_path: Path):
    missing = tmp_path / "does_not_exist"
    result = install_indicator(source=source_file, dest_dir=missing, on_conflict="overwrite")
    assert result.success is False
    assert "not found" in result.error.lower()
