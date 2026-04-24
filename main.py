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


def _seed_version_env() -> None:
    """Populate FTL_IMAGE_TAG / FTL_GIT_SHA / FTL_BUILT_AT from version.txt.

    The Windows build script writes `<install>/version.txt` (one directory
    above main.py) with lines like `image_tag=v1.2.3`. services.version
    reads these keys from os.environ, so mirroring them here unifies the
    Windows and Docker version paths. No-op if the file is missing or if
    the env var was already set by the caller (Docker's FTL_* ENV wins).
    """
    version_file = Path(__file__).resolve().parent.parent / "version.txt"
    if not version_file.is_file():
        return
    mapping = {
        "image_tag": "FTL_IMAGE_TAG",
        "git_sha": "FTL_GIT_SHA",
        "built_at": "FTL_BUILT_AT",
    }
    for raw in version_file.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        env_name = mapping.get(key.strip().lower())
        if env_name and env_name not in os.environ:
            os.environ[env_name] = value.strip()


def run() -> None:
    data_dir = os.environ["FTL_DATA_DIR"]
    port_raw = os.environ["FTL_PORT"]
    try:
        port = int(port_raw)
    except ValueError as e:
        raise RuntimeError(f"FTL_PORT must be an integer, got {port_raw!r}") from e

    # The Go launcher doesn't set a working directory for us, so Python's
    # cwd is wherever the user double-clicked from. create_app loads
    # migrations with a relative Path("migrations") — we anchor cwd to this
    # file's parent (the install's app/ directory, which contains
    # migrations/) so those loads resolve correctly. Docker sets WORKDIR
    # /app, so this chdir is a no-op there.
    os.chdir(Path(__file__).resolve().parent)

    # The Windows build writes `<install>/version.txt` next to the exe.
    # Mirror its key=value lines into FTL_* env vars so services.version
    # returns the real build info in /system/health and support bundles —
    # matching what Docker gets from ARG -> ENV at image build time.
    _seed_version_env()

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
