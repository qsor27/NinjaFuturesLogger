"""SimulationService — I/O wrapper around the pure engine.

Loads positions through the same function the statistics page uses so both
pages agree on which trades a filter selects, then hands them to
run_simulation. No caching; results are recomputed on every call.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from config import Config
from models.simulation import SimulationResult, SimulationRule
from models.statistics import StatsFilter
from services.simulation import run_simulation
from services.statistics import load_closed_positions


class SimulationService:
    def __init__(self, config: Config) -> None:
        self._config = config

    def display_tz_name(self) -> str:
        return self._config.display_timezone or self._config.session.exchange_timezone

    def run(self, rules: list[SimulationRule], filter: StatsFilter) -> SimulationResult:
        loaded = load_closed_positions(self._config, filter)
        return run_simulation(
            loaded.closed_with_pnl,
            rules,
            display_tz=ZoneInfo(self.display_tz_name()),
            filter=filter,
        )
