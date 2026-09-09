from datetime import date

from models.simulation import SimulationRule
from models.statistics import StatsFilter
from services.simulation_service import SimulationService
from tests.conftest import make_execution, seed_executions

# 2026-04-13 session (Chicago). Entry 09:00 UTC, exit 09:10 UTC.
# 5-point moves: a 1-point MNQ move (-$2) would sit inside the $2 commission band and classify as scratch.
E0, X0 = 1776070800, 1776071400


def _seed_two_losses_then_win(db_path, account="Sim"):
    rows = []
    for i, (entry_px, exit_px) in enumerate([(100.0, 95.0), (100.0, 95.0), (100.0, 105.0)]):
        base = E0 + i * 1200
        rows.append(
            make_execution(f"a{i}", account=account, timestamp=base, price=entry_px, commission=1.0)
        )
        rows.append(
            make_execution(
                f"b{i}",
                account=account,
                timestamp=base + 600,
                side="Sell",
                original_action="Sell",
                price=exit_px,
                commission=1.0,
                entry_exit="Exit",
                position_after="-",
            )
        )
    seed_executions(db_path, rows)


def test_run_uses_shared_loader_and_engine(tmp_config, migrated_db):
    cfg = tmp_config.model_copy(update={"db_path": str(migrated_db)})
    _seed_two_losses_then_win(cfg.db_path)
    rule = SimulationRule(
        metric="losses", scope="session", comparator=">=", threshold=2, action="stop_session"
    )
    result = SimulationService(cfg).run([rule], StatsFilter())
    assert result.inputs.positions_considered == 3
    assert [s.entry_execution_id for s in result.skipped] == ["a2"]
    assert result.simulated.summary.total_positions == 2
    assert result.inputs.display_tz == "America/Chicago"


def test_filter_is_applied_before_engine(tmp_config, migrated_db):
    cfg = tmp_config.model_copy(update={"db_path": str(migrated_db)})
    _seed_two_losses_then_win(cfg.db_path, account="A")
    _seed_two_losses_then_win(cfg.db_path, account="B")
    svc = SimulationService(cfg)
    only_a = svc.run([], StatsFilter(accounts=("A",)))
    assert only_a.inputs.positions_considered == 3
    none = svc.run([], StatsFilter(from_date=date(2030, 1, 1)))
    assert none.inputs.positions_considered == 0
    assert none.actual.summary.total_positions == 0


def test_display_tz_prefers_config_override(tmp_config):
    cfg = tmp_config.model_copy(update={"display_timezone": "America/New_York"})
    assert SimulationService(cfg).display_tz_name() == "America/New_York"
    assert SimulationService(tmp_config).display_tz_name() == "America/Chicago"
