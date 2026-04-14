from flask import Blueprint, redirect, render_template, url_for


def build_pages_blueprint() -> Blueprint:
    bp = Blueprint("pages", __name__)

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

    @bp.get("/links/<int:link_group_id>")
    def link_group(link_group_id: int):
        return render_template("link_group.html", link_group_id=link_group_id)

    @bp.get("/links")
    def links_index():
        # For now, the link-groups index reuses the positions list as the
        # landing page. A dedicated index can ship later if there's demand.
        return redirect(url_for("pages.positions_list"))

    @bp.get("/statistics")
    def statistics_page():
        return render_template("statistics.html")

    @bp.get("/reports")
    def reports_page():
        return render_template("reports.html")

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

    @bp.get("/system/health")
    def system_health_page():
        return render_template("system_health.html")

    return bp
