"""Windows entry point for NinjaFuturesLogger.

Consumed by the Go launcher (windows/launcher). The launcher sets
FTL_PORT and FTL_DATA_DIR env vars, then spawns `pythonw.exe main.py`.
We start waitress in a background thread and open a pywebview window
pointing at 127.0.0.1:<port>. When the user closes the window,
pywebview returns, and we shut background services down before the
process exits.

Never run under gunicorn (not supported on Windows). For Docker / Linux
dev, use wsgi.py via gunicorn instead -- this file is Windows-only.
"""

import os
import threading
from pathlib import Path

from waitress import serve

from app import create_app
from config import load_config


def run() -> None:
    data_dir = os.environ["FTL_DATA_DIR"]
    port_raw = os.environ["FTL_PORT"]
    try:
        port = int(port_raw)
    except ValueError as e:
        raise RuntimeError(f"FTL_PORT must be an integer, got {port_raw!r}") from e

    config_path = Path(data_dir) / "config" / "app.json"
    config = load_config(config_path)
    flask_app, services = create_app(config, start_background=True)

    server_thread = threading.Thread(
        target=lambda: serve(flask_app, host="127.0.0.1", port=port, threads=4),
        daemon=True,
        name="waitress-server",
    )
    server_thread.start()

    import webview  # lazy import so unit tests can mock via sys.modules

    webview.create_window(
        "NinjaFuturesLogger",
        f"http://127.0.0.1:{port}/",
        width=1400,
        height=900,
    )
    try:
        webview.start()
    finally:
        services.stop()


if __name__ == "__main__":
    run()
