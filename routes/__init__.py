from flask import current_app


def db_path() -> str:
    """SQLite path for the current app context (FTL_DB_PATH)."""
    return current_app.config["FTL_DB_PATH"]
