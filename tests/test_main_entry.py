"""Tests for the Windows entry point (main.py).

main.py is called by the Go launcher with FTL_PORT and FTL_DATA_DIR env vars.
It starts waitress in a background thread and opens a pywebview window.
We can't exercise the real pywebview loop in pytest, so we mock both
pywebview and waitress and assert the wiring calls them with the right args.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


def _write_config(data_dir: Path) -> None:
    (data_dir / "config").mkdir(parents=True, exist_ok=True)
    (data_dir / "inbox").mkdir(exist_ok=True)
    (data_dir / "archive").mkdir(exist_ok=True)
    (data_dir / "logs").mkdir(exist_ok=True)
    app_json = {
        "data_dir": str(data_dir),
        "db_path": str(data_dir / "app.db"),
        "inbox_dir": str(data_dir / "inbox"),
        "archive_dir": str(data_dir / "archive"),
        "log_dir": str(data_dir / "logs"),
        "session": {
            "exchange_timezone": "America/Chicago",
            "source_timezone": "America/Chicago",
            "trade_date_rollover": "17:00",
            "archive_job_time": "18:00",
        },
        "thread_pool": {"max_workers": 4},
        "scheduler": {"heartbeat_seconds": 60},
        "display_timezone": None,
        "theme": "dark",
    }
    (data_dir / "config" / "app.json").write_text(json.dumps(app_json))


def test_main_run_invokes_waitress_then_pywebview(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    _write_config(data_dir)

    monkeypatch.setenv("FTL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FTL_PORT", "8765")

    mock_webview = MagicMock()
    mock_waitress_serve = MagicMock()

    with (
        patch.dict("sys.modules", {"webview": mock_webview}),
        patch("waitress.serve", mock_waitress_serve),
    ):
        import importlib

        import main

        importlib.reload(main)
        main.run()

    assert mock_webview.create_window.called
    create_args = mock_webview.create_window.call_args
    assert create_args.args[0] == "NinjaFuturesLogger"
    assert create_args.args[1] == "http://127.0.0.1:8765/"
    assert mock_webview.start.called

    # waitress.serve is invoked in a daemon thread; wait briefly for it.
    import time

    for _ in range(20):
        if mock_waitress_serve.called:
            break
        time.sleep(0.05)
    assert mock_waitress_serve.called
    kwargs = mock_waitress_serve.call_args.kwargs
    assert kwargs.get("host") == "127.0.0.1"
    assert kwargs.get("port") == 8765


def test_main_run_raises_when_env_vars_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("FTL_DATA_DIR", raising=False)
    monkeypatch.delenv("FTL_PORT", raising=False)

    import importlib

    import main

    importlib.reload(main)

    import pytest

    with pytest.raises((KeyError, RuntimeError)):
        main.run()
