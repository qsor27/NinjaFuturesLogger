"""Pure marker builder.

Given a list of real Execution rows for one position, emit one Marker per
execution. No DB access. No mutation. No suffix handling — the route is
responsible for passing only real (un-suffixed) execution rows. Order is
preserved as a guarantee, not an accident; tests assert it.

This service exists to keep the route thin (Rule 2) and to give the
marker-shape logic a home that's easy to unit test without spinning up Flask
or SQLite.
"""

from models.execution import Execution
from models.markers import Marker


def build_markers(executions: list[Execution]) -> list[Marker]:
    """Return one Marker per real Execution. Input order is preserved."""
    return [
        Marker(
            time=e.timestamp,
            price=e.price,
            side=e.side,
            quantity=e.quantity,
            label=e.nt_execution_id,
        )
        for e in executions
    ]
