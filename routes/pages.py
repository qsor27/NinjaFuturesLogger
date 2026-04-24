from flask import Blueprint, current_app, redirect, render_template, url_for

from services.preferences import get_preference


def build_pages_blueprint() -> Blueprint:
    bp = Blueprint("pages", __name__)

    @bp.get("/")
    def root():
        first_run_done = get_preference(current_app.config["FTL_DB_PATH"], "first_run_complete")
        if not first_run_done:
            return redirect(url_for("first_run.first_run_page"))
        return redirect(url_for("pages.positions_list"))

    @bp.get("/positions")
    def positions_list():
        return render_template("positions_list.html")

    @bp.get("/positions/<account>/<instrument>/<entry_execution_id>")
    def position_detail(account: str, instrument: str, entry_execution_id: str):
        return render_template(
            "position_detail.html",
            account=account,
            instrument=instrument,
            entry_execution_id=entry_execution_id,
        )

    @bp.get("/statistics")
    def statistics_page():
        return render_template("statistics.html")

    @bp.get("/calendar")
    def calendar_page():
        return render_template("calendar.html")

    @bp.get("/imports")
    def imports_list():
        return render_template("imports.html")

    @bp.get("/imports/<int:tick_id>")
    def imports_detail(tick_id: int):
        return render_template("imports_detail.html", tick_id=tick_id)

    @bp.get("/validation")
    def validation_page():
        return render_template("validation.html")

    @bp.get("/data-health")
    def data_health_page():
        return render_template("data_health.html")

    @bp.get("/data-health/system")
    def data_health_system_page():
        return render_template("data_health_system.html")

    @bp.get("/system/health")
    def system_health_page():
        return render_template("system_health.html")

    return bp
