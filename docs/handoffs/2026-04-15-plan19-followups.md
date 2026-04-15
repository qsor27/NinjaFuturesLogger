# Plan 19 Follow-Up Handoff — Data-Health Alignment + Minor Bugs

**Date:** 2026-04-15
**Context:** Plan 19 (OHLC Coverage Maintainer) landed at commit `37d3a75`. Smoke test
revealed a real data-display bug and two smaller cosmetic issues that were intentionally
left out of scope. This doc captures enough context for a fresh session to fix them
without re-deriving Plan 19's design.

**Prerequisite reading:**
- `docs/superpowers/specs/2026-04-14-ohlc-coverage-maintainer-design.md` — the design
- `docs/superpowers/plans/2026-04-15-19-ohlc-coverage-maintainer.md` — the plan

---

## Bug 1 (load-bearing) — `1d` cell always "missing" on data-health, even when daily bars are present

### Symptom

The data-health page shows the `1d` column as red for every active contract, even
after the daily cron job has successfully fetched daily bars from yfinance. Confirmed
live at smoke-test time (2026-04-15): the logs showed
`{"message": "fetch_range done", "instrument": "MNQ JUN26", "tf": "1d", "bars_added": 277, "status": "ok"}`
yet `/api/data-health/completeness?days=30` reported `"1d": "missing"` for MNQ JUN26
immediately afterward. User had noticed this symptom independently back on 2026-04-14
before Plan 19 started ("1d: 4 / 30").

### Root cause (confirmed by reading the code)

`services/ohlc/gap_detection.py::_expected_slots` generates expected bar timestamps
by walking the window on a stride of `timeframe_seconds(tf)` starting from the
**session-aligned boundary** (CME 17:00 CT). For `1d` (stride = 86400) the walker
emits timestamps at 17:00 CT of each day.

But yfinance timestamps daily bars at **00:00 UTC** of each trading day, which in
US DST is 19:00 CT the previous day (or 18:00 CT in standard time). So the bars in
the store have `time` values that are never at `_expected_slots`'s 17:00-CT alignment,
and `classify_window` classifies every expected 1d slot as `missing` while every
actual stored 1d bar goes unmatched.

This is a **pre-existing** bug in gap detection, not a Plan 19 regression. Plan 19
just made it more visible by adding honest `out_of_reach` classification everywhere
else.

### Why the intraday timeframes don't have this problem

Intraday yfinance bars (1m/5m/15m/1h) are stamped at epoch times that *do* fall on
the same 60-second / 5-minute / 1-hour / … strides that `_expected_slots` walks, so
the alignment happens to work. Daily is special because yfinance uses a calendar-day
boundary but the session-aware walker uses the 17:00-CT session open.

### Suggested fix — one of these three approaches, pick one

**Option A (cleanest): Use the actual bar-time distribution as the expected set for
daily and above.** For `1d`, `1wk`, `1mo`, the expected slots are "one bar per trading
day in the window that exists in the calendar," not "walk a 17:00-CT stride." A
simpler model: for `tf in (1d, 1wk, 1mo)`, just count trading days in the window (or
for `1wk`, trading weeks), and compare to the count of bars present regardless of
their exact stamp — only the day matters.

**Option B (local):** Special-case the alignment anchor per timeframe in
`_expected_slots`. For `1d`, anchor at UTC midnight (not 17:00 CT) so the walker's
slot timestamps match yfinance's stamping convention. For `1wk`, anchor at the
start-of-week boundary yfinance actually uses (Monday 00:00 UTC, probably). For
`1mo`, anchor at the first calendar day. Riskier — changing anchors per-tf is a
hairball, and yfinance's convention may change.

**Option C (pragmatic): Make `classify_window` "trading-day aware" for `1d+`.**
Keep `_expected_slots` computing a list of days, but compare against `{floor(t, 1d) for t in list_times(...)}` — i.e., bucket both sides to the UTC calendar day before comparing. This is less structural than A but doesn't require new helpers.

My recommendation is **Option C**. It's a 5-line change in `classify_window`, doesn't
touch `_expected_slots` (which has other consumers including `find_gaps` and the
maintainer windows), and the "day-bucket on both sides" logic handles daylight-saving
transitions automatically.

### Files likely to change

- `services/ohlc/gap_detection.py` — `classify_window` and maybe `_expected_slots`
- `tests/test_gap_detection.py` — add a test that inserts a 1d bar at UTC midnight
  and verifies it shows up as `present`, not `missing`
- `tests/test_routes_monitoring.py` — add a regression test that seeds 1d bars and
  asserts the cell comes back `complete` (or `partial` if the window extends beyond
  what was seeded)

### Test to write first (failing red)

```python
# tests/test_gap_detection.py (append)
def test_classify_window_matches_1d_bars_at_utc_midnight(tmp_path):
    from pathlib import Path
    from db import connect
    from migrations import run_migrations
    from services.ohlc.gap_detection import classify_window

    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    # Insert 5 daily bars at UTC midnight stamps — matches what yfinance returns.
    base_utc_midnight = 1776153600  # 2026-04-14T00:00:00Z
    for i in range(5):
        conn.execute(
            "INSERT INTO bars (instrument, timeframe, time, open, high, low, close,"
            " volume, source, fetched_at)"
            " VALUES ('MNQ JUN26', '1d', ?, 1, 2, 0, 1, 100, 'yfinance', 0)",
            (base_utc_midnight - i * 86400,),
        )
    now = base_utc_midnight + 86400
    summary = classify_window(
        conn,
        instrument="MNQ JUN26",
        timeframe="1d",
        start=base_utc_midnight - 5 * 86400,
        end=now,
        now=now,
    )
    assert summary["present"] == 5  # CURRENTLY: 0 — the bug
    assert summary["missing"] == 0
```

This test should fail on master today. Write the fix, watch it go green, then
regression-test with `/api/data-health/completeness` end-to-end.

---

## Bug 2 (cosmetic) — Maintainer panel `last_run_at` stays null after manual triggers

### Symptom

On `/data-health`, the "Coverage Maintainer" panel always shows `Last run —` even
after you POST to `/api/system/run-job/ohlc_coverage_maintainer`. Real scheduled
runs at the top of the 30-minute interval DO populate the field correctly; only
manual triggers don't.

### Root cause

`BackgroundServices._on_job_submitted` and `_on_job_finished` in `background.py`
are APScheduler event listeners wired up in `start()`. They only fire for jobs
executed by the APScheduler thread. `BackgroundServices.run_job_now` submits the
job function directly to the thread pool (`self.pool.submit(job.func, ...)`),
bypassing the scheduler entirely — so the listeners never see the run.

### Suggested fix

Option A: in `run_job_now`, wrap the submitted callable so it records its own
start/end into `_job_history` under the same job_id key the listener would use.
Pattern:

```python
def run_job_now(self, job_id: str) -> bool:
    job = self.scheduler.get_job(job_id)
    if job is None:
        return False
    fn = job.func

    def wrapped():
        started = int(time.time() * 1000)
        is_error = False
        exc_repr = None
        try:
            return fn(*job.args, **job.kwargs)
        except Exception as e:  # noqa: BLE001 — record anything
            is_error = True
            exc_repr = repr(e)
            raise
        finally:
            finished = int(time.time() * 1000)
            record = {
                "started_at": started // 1000,
                "duration_ms": finished - started,
                "status": "error" if is_error else "success",
                "error": exc_repr,
            }
            if job_id not in self._job_history:
                self._job_history[job_id] = deque(maxlen=20)
            self._job_history[job_id].appendleft(record)

    self.pool.submit(wrapped)
    return True
```

Small scope, localized change.

### Files

- `background.py` — `run_job_now`
- `tests/test_background.py` — new test that asserts `_job_history` gets an entry
  after `run_job_now` is called with a job that has a trivial function

---

## Bug 3 (pre-existing, unrelated to Plan 19) — 4 failing tests in `test_routes_pages.py` for link_group routes

### Context

At the start of the Plan 19 work, `git status` already showed these deleted files
unstaged (deletions authored before this session started):
- `routes/links.py` (deleted)
- `services/links.py` (deleted)
- `static/js/link_group.js` (deleted)
- `templates/link_group.html` (deleted)
- `tests/test_links_service.py` (deleted)
- `tests/test_routes_links.py` (deleted)

Plus a new unstaged migration `migrations/007_drop_link_groups.sql`.

These are mid-removal of a feature that pre-dates Plan 19. The failing tests in
`test_routes_pages.py` that reference link_group routes have been stale since the
removal started, and remain unstaged/uncommitted on the user's working tree.

### Suggested action

Two viable paths:

1. **Finish the link_group removal:** stage the deletions + the new migration +
   delete the stale tests in `test_routes_pages.py` (look for
   `test_link_group_page_renders_with_id` and `test_links_index_redirects_or_renders_positions`).
   One commit, ~minus 500 lines of dead code, full suite goes to 617/617 clean.

2. **Leave as-is until the user wants to finalize the feature removal.**

This is bookkeeping, not a bug fix. My recommendation: do path 1 as the very first
commit in a new session, before touching bugs 1 and 2 — it clears the noise so the
full suite is truly green before you start changing gap_detection.

---

## Not bugs, but worth noting

- The `apscheduler` `ohlc_monthly_refresh` job is one-shot + self-rescheduling. Every
  time it fires it re-schedules itself for the next month's last day at 16:01 CT,
  with December→January year rollover handled. The first seeding happens at
  `create_app` time. If `create_app` runs within microseconds of the actual 16:01
  deadline on the last day of the month, the seeded `run_date` is guarded against
  being in the past (`if run_date <= now_local: roll forward`). Tested manually
  in Task 15.
- `last_error` on the yfinance source snapshot will periodically show
  `"...possibly delisted; no price data found"` for specific overnight minutes on
  forward-month contracts (e.g. MNQ JUN26 when the current trading month is April).
  These are classified as `"other"` failures and correctly DO NOT trip the breaker —
  it's just yfinance legitimately having no data for those slots. User was briefed
  on this during Plan 19 brainstorming ("contracts that aren't the prevailing or
  major volume contract will have weird or spotty data").

---

## State of the repo at handoff time

- Branch: `master`
- HEAD: `37d3a75` (style(plan19): ruff format pass across plan 19 files)
- Plan 19 test count: **617 passed**
- Known failures when running the full suite: **4 failing tests in
  `test_routes_pages.py`** for the deleted link_group feature — see Bug 3 above.
- Docker container was rebuilt and running at smoke-test time. Bars table has real
  MNQM26.CME data from the smoke run (21k+ bars). Safe to delete if you want a
  clean-slate test — migration 009 runs exactly once per schema_migrations row so
  it won't re-purge on restart.
