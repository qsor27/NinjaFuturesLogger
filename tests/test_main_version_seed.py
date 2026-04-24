"""Tests for the _seed_version_env helper in main.py.

The Windows build writes `<install>/version.txt` next to the exe; main.py
reads it at startup and seeds FTL_* env vars so services.version surfaces
the real build info the same way Docker does via ARG -> ENV.
"""

import importlib
import os
import sys
from pathlib import Path


def _import_main_from(tmp_install_app_dir: Path):
    """Import main.py as if it lives at <tmp>/app/main.py.

    Copies the real main.py to the tmp location so the `Path(__file__).parent.parent`
    version-file lookup resolves to `<tmp>/version.txt`.
    """
    repo_root = Path(__file__).resolve().parent.parent
    src = repo_root / "main.py"
    dst = tmp_install_app_dir / "main.py"
    tmp_install_app_dir.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    # Make sure the tmp location is importable.
    sys.path.insert(0, str(tmp_install_app_dir))
    # Evict any cached main module so reimport picks up the tmp copy.
    sys.modules.pop("main", None)
    return importlib.import_module("main")


def test_seed_version_env_populates_from_version_txt(tmp_path, monkeypatch):
    install_root = tmp_path / "install"
    app_dir = install_root / "app"
    install_root.mkdir(parents=True, exist_ok=True)
    (install_root / "version.txt").write_text(
        "image_tag=v9.9.9\ngit_sha=abc1234\nbuilt_at=2026-04-24T00:00:00Z\n",
        encoding="utf-8",
    )
    for name in ("FTL_IMAGE_TAG", "FTL_GIT_SHA", "FTL_BUILT_AT"):
        monkeypatch.delenv(name, raising=False)

    mod = _import_main_from(app_dir)
    try:
        mod._seed_version_env()
        assert os.environ["FTL_IMAGE_TAG"] == "v9.9.9"
        assert os.environ["FTL_GIT_SHA"] == "abc1234"
        assert os.environ["FTL_BUILT_AT"] == "2026-04-24T00:00:00Z"
    finally:
        sys.path.remove(str(app_dir))
        sys.modules.pop("main", None)


def test_seed_version_env_is_no_op_when_file_missing(tmp_path, monkeypatch):
    install_root = tmp_path / "install"
    app_dir = install_root / "app"
    for name in ("FTL_IMAGE_TAG", "FTL_GIT_SHA", "FTL_BUILT_AT"):
        monkeypatch.delenv(name, raising=False)

    mod = _import_main_from(app_dir)
    try:
        mod._seed_version_env()  # does not raise
        assert "FTL_IMAGE_TAG" not in os.environ
    finally:
        sys.path.remove(str(app_dir))
        sys.modules.pop("main", None)


def test_seed_version_env_does_not_overwrite_existing_env(tmp_path, monkeypatch):
    """Docker's ENV should win — the file seed only fills unset vars."""
    install_root = tmp_path / "install"
    app_dir = install_root / "app"
    install_root.mkdir(parents=True, exist_ok=True)
    (install_root / "version.txt").write_text(
        "image_tag=v_from_file\n", encoding="utf-8"
    )
    monkeypatch.setenv("FTL_IMAGE_TAG", "v_from_env")
    monkeypatch.delenv("FTL_GIT_SHA", raising=False)

    mod = _import_main_from(app_dir)
    try:
        mod._seed_version_env()
        assert os.environ["FTL_IMAGE_TAG"] == "v_from_env"
    finally:
        sys.path.remove(str(app_dir))
        sys.modules.pop("main", None)


def test_seed_version_env_ignores_blank_and_unknown_lines(tmp_path, monkeypatch):
    install_root = tmp_path / "install"
    app_dir = install_root / "app"
    install_root.mkdir(parents=True, exist_ok=True)
    (install_root / "version.txt").write_text(
        "\n# a comment line without equals\nimage_tag=v1.0.0\nunknown_key=foo\n",
        encoding="utf-8",
    )
    for name in ("FTL_IMAGE_TAG", "FTL_GIT_SHA", "FTL_BUILT_AT"):
        monkeypatch.delenv(name, raising=False)

    mod = _import_main_from(app_dir)
    try:
        mod._seed_version_env()
        assert os.environ["FTL_IMAGE_TAG"] == "v1.0.0"
        assert "FTL_GIT_SHA" not in os.environ
    finally:
        sys.path.remove(str(app_dir))
        sys.modules.pop("main", None)
