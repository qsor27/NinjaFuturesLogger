"""First-run wizard: HTML page + JSON API for NT setup.

Surfaces:
  GET  /first-run                          - wizard HTML (vanilla JS)
  GET  /api/first-run/detect-nt            - Task 6
  POST /api/first-run/install-indicator    - Task 7
  GET  /api/first-run/inbox-status         - Task 8
  POST /api/first-run/complete             - Task 9
"""

from flask import Blueprint, render_template


def build_first_run_blueprint() -> Blueprint:
    bp = Blueprint("first_run", __name__)

    @bp.get("/first-run")
    def first_run_page():
        return render_template("first_run.html")

    return bp
