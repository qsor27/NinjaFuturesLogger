"""Gunicorn entry point.

Run locally:
    gunicorn -w 1 -b 0.0.0.0:8000 wsgi:app

We pin workers to 1 because BackgroundServices owns in-process state that
multiple gunicorn workers would each duplicate (two schedulers, two
watchdog observers, etc.). The app is single-user -- one worker is correct.
"""
import atexit

from app import create_app
from config import load_config

config = load_config("data/config/app.json")
app, background_services = create_app(config, start_background=True)


@atexit.register
def _shutdown() -> None:
    background_services.stop()
