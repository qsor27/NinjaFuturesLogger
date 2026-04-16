"""StatisticsService — the I/O wrapper around the pure aggregation helpers.

Plan 15. One method per /api/stats/* endpoint. Each method takes a StatsFilter
and returns a typed Pydantic StrictModel. Routes do no SQL; this module owns
all of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from config import Config
from db import connect
from models.execution import Execution
from models.position import Position
from models.statistics import (
    DayOfWeekResponse,
    DistributionResponse,
    EquityCurveResponse,
    EquitySeries,
    HourBucketResponse,
    InstrumentBreakdown,
    SideBreakdown,
    SideStats,
    StatsFilter,
    StatsSummary,
    TimeBucketResponse,
)
from services.positions import build_positions
from services.statistics_aggregations import (
    _session_date_of,
    bucket_by_day_of_week,
    bucket_by_hour,
    bucket_by_session_date,
    compute_summary,
    cumulative_equity,
    per_instrument,
    pnl_histogram,
    split_by_side,
)


@dataclass(frozen=True)
class _LoadResult:
    closed_with_pnl: list[Position]
    closed_missing_multiplier: list[Position]
    open: list[Position]


class StatisticsService:
    def __init__(self, config: Config) -> None:
        self._config = config

    # -- I/O --------------------------------------------------------------

    def _load_closed_positions(self, filter: StatsFilter) -> _LoadResult:
        executions = self._load_executions(account=filter.account)
        groups: dict[tuple[str, str], list[Execution]] = {}
        for e in executions:
            groups.setdefault((e.account, e.instrument), []).append(e)

        closed_with_pnl: list[Position] = []
        closed_missing_mult: list[Position] = []
        open_positions: list[Position] = []
        for _key, group in groups.items():
            positions, _issues = build_positions(group)
            for p in positions:
                if p.exit_time is None:
                    open_positions.append(p)
                elif p.dollars_pnl is None:
                    closed_missing_mult.append(p)
                else:
                    closed_with_pnl.append(p)

        if filter.from_date is not None or filter.to_date is not None:
            closed_with_pnl = [
                p
                for p in closed_with_pnl
                if self._in_session_range(p, filter.from_date, filter.to_date)
            ]
            closed_missing_mult = [
                p
                for p in closed_missing_mult
                if self._in_session_range(p, filter.from_date, filter.to_date)
            ]
            open_positions = [
                p
                for p in open_positions
                if self._in_session_range(p, filter.from_date, filter.to_date)
            ]

        if filter.side is not None:
            closed_with_pnl = [p for p in closed_with_pnl if p.side == filter.side]
            closed_missing_mult = [p for p in closed_missing_mult if p.side == filter.side]
            open_positions = [p for p in open_positions if p.side == filter.side]

        return _LoadResult(
            closed_with_pnl=closed_with_pnl,
            closed_missing_multiplier=closed_missing_mult,
            open=open_positions,
        )

    @staticmethod
    def _in_session_range(p: Position, from_date, to_date) -> bool:
        sd = _session_date_of(p)
        if from_date is not None and sd < from_date:
            return False
        if to_date is not None and sd > to_date:
            return False
        return True

    def _load_executions(self, *, account: str | None) -> list[Execution]:
        sql = (
            "SELECT nt_execution_id, account, instrument, timestamp, side,"
            " original_action, quantity, price, commission, entry_exit,"
            " position_after, source_order_id, source_filename, imported_at "
            "FROM executions"
        )
        params: tuple = ()
        if account is not None:
            sql += " WHERE account = ?"
            params = (account,)
        sql += " ORDER BY account, instrument, timestamp, nt_execution_id"
        conn = connect(self._config.db_path)
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return [
            Execution(
                nt_execution_id=r["nt_execution_id"],
                account=r["account"],
                instrument=r["instrument"],
                timestamp=r["timestamp"],
                side=r["side"],
                original_action=r["original_action"],
                quantity=r["quantity"],
                price=r["price"],
                commission=r["commission"],
                entry_exit=r["entry_exit"],
                position_after=r["position_after"],
                source_order_id=r["source_order_id"],
                source_filename=r["source_filename"],
                imported_at=r["imported_at"],
            )
            for r in rows
        ]

    # -- Public methods ---------------------------------------------------

    def summary(self, filter: StatsFilter) -> StatsSummary:
        loaded = self._load_closed_positions(filter)
        s = compute_summary(loaded.closed_with_pnl)
        return s.model_copy(
            update={
                "open_positions": len(loaded.open),
                "skipped_no_multiplier": len(loaded.closed_missing_multiplier),
            }
        )

    def by_instrument(self, filter: StatsFilter) -> InstrumentBreakdown:
        loaded = self._load_closed_positions(filter)
        return InstrumentBreakdown(rows=per_instrument(loaded.closed_with_pnl))

    def by_day(self, filter: StatsFilter) -> TimeBucketResponse:
        return self._time_bucket(filter, granularity="day")

    def by_week(self, filter: StatsFilter) -> TimeBucketResponse:
        return self._time_bucket(filter, granularity="week")

    def by_month(self, filter: StatsFilter) -> TimeBucketResponse:
        return self._time_bucket(filter, granularity="month")

    def _time_bucket(self, filter: StatsFilter, *, granularity) -> TimeBucketResponse:
        loaded = self._load_closed_positions(filter)
        buckets = bucket_by_session_date(
            loaded.closed_with_pnl,
            granularity=granularity,
            from_date=filter.from_date,
            to_date=filter.to_date,
        )
        return TimeBucketResponse(granularity=granularity, buckets=buckets)

    def by_hour(self, filter: StatsFilter) -> HourBucketResponse:
        loaded = self._load_closed_positions(filter)
        tz_name = self._config.display_timezone or self._config.session.exchange_timezone
        tz = ZoneInfo(tz_name)
        return HourBucketResponse(
            timezone=tz_name,
            buckets=bucket_by_hour(loaded.closed_with_pnl, display_tz=tz),
        )

    def by_side(self, filter: StatsFilter) -> SideBreakdown:
        loaded = self._load_closed_positions(filter)
        longs, shorts = split_by_side(loaded.closed_with_pnl)
        return SideBreakdown(
            long=_side_stats(longs),
            short=_side_stats(shorts),
        )

    def equity_curve(self, filter: StatsFilter) -> EquityCurveResponse:
        loaded = self._load_closed_positions(filter)
        by_account: dict[str, list[Position]] = {}
        for p in loaded.closed_with_pnl:
            by_account.setdefault(p.account, []).append(p)
        series = [
            EquitySeries(account=account, points=cumulative_equity(positions))
            for account, positions in sorted(by_account.items())
        ]
        return EquityCurveResponse(series=series)

    def distribution(self, filter: StatsFilter) -> DistributionResponse:
        loaded = self._load_closed_positions(filter)
        buckets = pnl_histogram(loaded.closed_with_pnl, n_buckets=10)
        return DistributionResponse(buckets=buckets, bucket_count=10)

    def by_day_of_week(self, filter: StatsFilter) -> DayOfWeekResponse:
        loaded = self._load_closed_positions(filter)
        return DayOfWeekResponse(buckets=bucket_by_day_of_week(loaded.closed_with_pnl))


def _side_stats(positions: list[Position]) -> SideStats:
    s = compute_summary(positions)
    return SideStats(
        position_count=s.total_positions,
        total_pnl=s.total_pnl,
        win_rate=s.win_rate,
        avg_win=s.avg_win,
        avg_loss=s.avg_loss,
        profit_factor=s.profit_factor,
    )
