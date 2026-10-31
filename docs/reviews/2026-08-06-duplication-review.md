# Duplication & cleanup review — 2026-08-06

Four-area review (Python backend, OHLC subsystem, frontend, tests + windows/ninjascript)
focused on repeated code, copy-paste drift, and dead code. Findings verified against the
working tree as of commit 711aedf + uncommitted changes.

Legend: **[BUG]** = behavior is wrong today, not just untidy. Risk = refactor risk.

---

## Tier 1 — Latent bugs born from copy-paste drift (fix first, each with a test)

### B1. [BUG] Provider-reach clamp logic: 4 divergent copies
- `services/ohlc/fetcher.py:31-52` — only copy with the 3600s `REACH_MARGIN_SECONDS` safety margin
- `routes/ohlc.py:129-151` — no margin; 409s when fully out of reach
- `routes/monitoring.py:94-102` — no margin
- `services/ohlc/gap_reports.py:61-70` — no margin AND missing the `< 365*86400` intraday-only guard

Consequence: gap_reports can record a gap as fillable that the fetcher will perpetually drop
(`dropped_out_of_reach`) — feeds the known "stale abandoned gaps accumulate" incident follow-up.
Fix: single `reach_floor(timeframe, *, now, margin=0)` helper in `services/ohlc/reach.py`
(which already owns `PROVIDER_REACH`); margin becomes an explicit per-call-site parameter.
Risk: low-med. Tests exist per-site (`test_reach.py`, `test_ohlc_fetcher.py`, `test_routes_ohlc.py`,
`test_ohlc_gap_reports.py`) but nothing pins cross-site consistency — add one.

### B2. [BUG] `?limit=-1` on imports API returns every row
`routes/imports.py:20` — `limit = min(int(...), 500)` clamps only the top; SQLite `LIMIT -1` = unlimited.
`routes/positions.py:117` does it right (`max(1, min(...))`). Part of a broader split: some routes
parse ints with try/400 (`positions.py:112-116`, `support.py:22-28`), others raw-`int()` and 500 on bad
input (`imports.py:20-21,31,34,120-121`, `monitoring.py:38,86-87`).
Fix: shared `int_arg(args, key, *, default, lo, hi)` helper (e.g. `routes/_params.py`); use everywhere.
Risk: low.

### B3. [BUG] PUT /api/config/chart-defaults silently clears `display_timezone` when omitted
`routes/settings.py:139-167` — `source_timezone` write is gated on `"source_timezone" in body` (:143,166)
but `display_timezone` is written unconditionally (:142,165). Omit the key → stored setting cleared.
Works today only because the settings page always sends both. Fix: same `in body` guard for both.
Risk: low; add an omission test to `test_settings_routes_chart.py`.

### B4. [BUG] Custom-fields 409 decided by substring-matching an error message
`services/custom_fields.py:100-107` rebrands ANY insert failure as `ValueError("duplicate name: ...")`;
`routes/settings.py:246-250` does `if "duplicate" in msg: 409`. A locked-DB error becomes a bogus 409.
Fix: catch `sqlite3.IntegrityError` specifically, raise a `DuplicateFieldError(ValueError)`, route
catches the type. Risk: low.

### B5. [BUG] Three competing OHLC failure-classification implementations
- `services/ohlc/fetcher.py:61-71` `_error_class` — else `None`
- `services/ohlc/circuit_breaker.py:182-197` `_classify` — else `"other"`, also returns retry_after
- `services/ohlc/_classify.py:30-57` `classify_http_error` — else `"other"`, no-response → `"network"`

The forensic trail (`fetch_source_attempts.error_class`) can disagree with what the breaker actually
did for the same exception. Fix: one module-level `classify_exception(err)` in `_classify.py`; breaker
and fetcher both call it. Risk: low; well covered by breaker tests.

### B6. [BUG] `fetch_range` "partial" status is unreachable
`services/ohlc/fetcher.py:380-385` — `bars_collected` non-empty implies `any_gap_filled`, so a fetch
filling 1 of 3 gaps reports `"ok"`. Restore intent with `all_gaps_filled` tracking (or delete branch).
Related micro-drift at :343 vs :358 (DB outcome `"ok"/"empty"` vs in-memory always `"ok"`). Risk: low.

### B7. [BUG] On-demand chart fetches bypass the global token bucket
`services/ohlc/rate_limiter.py` docstring says it gates *every* provider call, but only the scheduled
jobs path (`app.py:98-110`) passes `token_bucket`. Both route closures (`routes/ohlc.py:164-173`,
`:288-297`) call `fetch_range` without it — chart-driven fetches are unthrottled. Given the Yahoo-429
breaker-poisoning history this is a real hole. Fix: `_token_bucket()` accessor in the blueprint,
pass through. Risk: low.

### B8. [BUG] `post_gap_retry` breaks the 202+job_id pattern and mislabels the trigger
`routes/ohlc.py:284-300` uses raw `pool.submit` (no job_id, exceptions vanish) and passes
`trigger="self_heal"` for a user-initiated retry (dashboard mislabels manual clicks as scheduler
activity). Fix: route through `jobs.submit(...)` with `trigger="on_demand"`. Risk: low.

### B9. [BUG] data-health job poller has no timeout
`static/js/data_health_coverage.js:202-230` — recursion with no cap; a stuck `running` job polls
forever. The other two pollers (`PriceChart.js:735-752`, `position_detail.js:279-306`) have 120s caps.
Fix in the shared `ohlc_jobs.js` consolidation (D5 below). Risk: low.

### B10. [BUG] Frontend zero-P&L and escaping drift
- pnl class ternary exists in two forms: strict (`>0 pos, <0 neg, 0 unstyled`) in `api.js:98`,
  `positions_list.js:92`, `position_detail.js:137-142`; gte (`>=0 pos` — zero is green) ~11 inline
  copies in `statistics.js` + `stats_charts.js:257`. Pick one.
- `statistics.js` interpolates server data into innerHTML with NO escaping (`:205`, `:264`) while six
  other files carry identical `escHtml` copies; `data_health_coverage.js:50-51` escapes cell text but
  not `data-inst` attributes.
- `position_detail.js:159-162` uses Unicode minus "−"; every other formatter uses ASCII "-".

### B11. [BUG] windows/ninjascript findings
- **Compile collision:** `PositionValidationTracker`/`PositionValidationEntry` defined 3×;
  `ExecutionExporter.cs:1393-1548` and `TradeFeedbackIndicator.cs:322-443` share the same namespace →
  CS0101 if both are installed. Copies have drifted (`SerializeToText` `?? "None"` in 2 of 3).
  Evidence suggests `TradeFeedbackIndicator.cs` is a superseded predecessor — deleting it resolves
  the collision.
- **Validation never reaches the CSV:** three separate `SharedValidationMap` statics
  (`ExecutionExporter.cs:50`, `TradeFeedbackAddOn.cs:47`, `TradeFeedbackIndicator.cs:38`) that never
  see each other; the exporter reads only its own, so AddOn validations never reach the
  `TradeValidation` column. The AddOn's core flow may also be inert: `TradeFeedbackAddOn.cs:147,153`
  calls `GetUnrealizedProfitLoss` on an already-flat position (≈0, so `pnl < 0` never fires).
- **State-file clobber:** AddOn and Indicator write the same `trade_feedback_state.txt` from
  independent trackers (triplicated Save/Load at `ExecutionExporter.cs:1233-1265`,
  `TradeFeedbackAddOn.cs:407-441`, `TradeFeedbackIndicator.cs:286-315`).
- **Installer payload:** `windows/build/assemble-payload.ps1` ships ninjascript twice (missing from
  `$excludeDirs` :79-83 then copied again :88-90), leaks nested `__pycache__` (stale cpython-313 .pyc
  vs bundled 3.11), copies session dot-dirs (`.superpowers/...`), and ships `*Tests.cs` to end users
  (NUnit refs → NT compile failure if dropped in whole).
- **Port drift:** launcher/installer default to 8003 (`config.go:36,46,50`, `pages.pas:28,32,33`) but
  `config.py:34-37` defaults `windows.port` to 8000 — settings UI can show the wrong port when the
  `windows` section is absent.
- Indicator `isInitialized` static never reset (`TradeFeedbackIndicator.cs:28,56,83`) — after first
  instance terminates, no resubscription until NT restart.

### B12. [BUG] Test that silently tests the wrong thing
`tests/test_positions_sort.py:48-54` — name promises cross-account/instrument behavior but the local
`_ex` hardcodes account/instrument with no override, so it just re-tests plain pairing. Rewrite or delete.

---

## Tier 2 — Highest-value duplication consolidations

### D1. Executions SELECT + hydration copy-pasted 5×/4× (backend's biggest)
Column list + 14-kwarg `Execution(...)` construction duplicated across
`services/positions_service.py:19-60`, `services/statistics.py:118-153`, `services/integrity.py:83-109`,
`routes/positions.py:172-178,222-251`. Adding a column = 9 coordinated edits today.
→ `services/execution_db.py`: `EXECUTION_COLUMNS` + `execution_from_row(row)` + `load_executions(...)`.
Also: `routes/positions.py` `get_executions` vs `get_markers` duplicate the whole load-filter block and
double-load rows already walked by `get_position()`. Risk: low, strong coverage.

### D2. Transaction boilerplate ×17 (+~25 read-only variants)
The 10-line connect/BEGIN/COMMIT/ROLLBACK/close ceremony repeats across notes, flags, preferences,
custom_fields (×6), chart_defaults, import_pipeline, integrity, routes/positions, app.py — plus five
more copies inside `services/ohlc/` (fetcher ×3, self_heal ×2, with ROLLBACK-on-exception asymmetry
between copies). → `db.transaction(db_path)` + `db.read_conn(db_path)` contextmanagers. ~150+ lines
removed, one canonical rollback behavior. Risk: low-med, mechanical.

### D3. `config.py`: five near-identical atomic read-modify-write savers
`save_source_timezone`/`save_display_timezone` are identical except the key path; `save_windows_port`,
`save_theme`, `save_filter_default`, `clear_all_filter_defaults` repeat the lock+tmp+`os.replace` dance.
→ `_atomic_update(path, mutate)`. ~60 lines. Also: routes re-validate what config.py validates
(port range, theme values, accounts shape — with drifted error strings); let the service layer be the
single validator, routes map ValueError→400. `VALID_TIMEFRAMES` tuple exists in 5 places (two identical
`Timeframe` Literals in `models/settings.py:5` and `models/bar.py:5`) — one source, import elsewhere.

### D4. Frontend `format.js` + api.js adoption (frontend's biggest)
- api.js used by only 3 of 19 fetching modules; 16 hand-roll fetch, mostly without `resp.ok` checks;
  `first_run.js:20-32` shadows api.js's `postJSON`/`getJSON` names with non-throwing variants;
  POST-with-headers boilerplate ~20×; 6 files hand-roll PUT (add `putJSON`).
- New `static/js/format.js`: `escHtml` (6 identical copies), `formatTime`/`displayTz` (~25 tz-ignorant
  `toLocaleString` call sites vs the one tz-aware helper — imports/data-health/system pages show
  browser tz while positions pages show configured tz for the same events), `fmtMoney`/`pnlClass`
  (5 divergent money formatters — `stats_charts.js:284-288` `_formatPnl` is a verbatim copy of
  `statistics.js:76-80` `fmtMoney`), `formatDuration`, epoch/date-input helpers.
- Query-string serialization: 6 hand-rolled variants alongside `api.js buildQuery`; the stats↔positions
  drilldown param mapping lives in two files (`statistics.js positionsUrl` vs
  `positions_list.js renderBackToStats`) that must stay in sync with no shared constant.

### D5. `static/js/ohlc_jobs.js` — one fetch-trigger + one poller
3 pollers (one unbounded — B9), 4 copies of the POST-fetch trigger
(`PriceChart.js:689-693`, `position_detail.js:287-290`, `data_health_coverage.js:162-166,183-187`).
Result-status branching stays caller-side. Risk: med (touches chart CTA + data-health buttons).

### D6. Test conftest consolidation (biggest line-count win in the repo)
- `create_app` + try/finally `services.stop()`: **84 call sites in 30 files** → `app`/`client` fixtures.
  Kills ~300 lines and an indent level in nearly every route test.
- `_ex()` Execution builder defined 17× (several byte-identical); `_seed()` wrapper ×12; conftest's
  `migrated_db` reimplemented ~9× (one byte-identical, same name — `test_statistics_service.py:121-128`);
  two files use `tempfile.NamedTemporaryFile(delete=False)` and leak .db files outside tmp_path;
  `_seed_config` app.json writer ×4; full `Config(...)` hand-rolled 68× in 15 files; `_bar` ×4,
  `_pos` ×7, fake OHLC sources ×4; NT CSV header literal ×6 (mirrors the immutable doc-90 contract —
  one copy is safer).
- Exact duplicate test pairs across `test_app_factory_plan14.py` / `test_app_factory_plan19.py`
  (two pairs) — delete one of each.
- Parametrize candidates: windows-port rejects ×4, theme rejects ×2, monitoring runs-filters ×4.

### D7. fetcher.py structure (do LAST, after B1/B5/D2 settle)
507 lines doing 5 jobs; four near-identical short-circuit blocks (:118-198), `_record_and_log` +
AttemptRecord pairs ×5 with one asymmetry (`skipped_no_timeframe` gets no AttemptRecord,
`skipped_breaker` does — verify intentional). Extract `_try_sources_for_gap` + an attempt-trail helper;
fetch_range shrinks to ~150 lines of orchestration. Constraint preserved: fetch_range stays the only
source caller. Risk: med (hot path, 711aedf just touched it). Strong test coverage.

### D8. Adapter shared block
Verbatim 7-line transport-error classification in `yfinance_source.py:62-68` and `stooq_source.py:25-31`
→ `classified_transport_errors()` contextmanager in `_classify.py` (imports requests inside itself,
preserving lazy transport import). Bar-construction stays adapter-specific (intentional boundary).

### D9. ninjascript consolidation (needs a semantics decision first)
`GeneratePositionId` triplicated — it's the join key across components; drift silently breaks validation
lookup. `IsAutomatedOrder` has three different definitions (exporter/indicator vs AddOn) — same
user-facing setting behaves differently per component; reconcile deliberately. Account.All
subscribe/unsubscribe loop ×6. NT8 compiles all .cs into one assembly, so a shared
`TradeValidationShared.cs` is viable. **Caveat:** the CSV contract methods (`FormatExecutionAsCSV`/
`EscapeCSVField`) have zero working tests (no .csproj; NUnit files can't compile outside NT) —
characterize before touching anything nearby.

---

## Tier 3 — Dead code inventory (pure deletion)

Backend:
- `session.trade_date_rollover` config key: declared required (`config.py:17`), read by nothing
  (`time_utils.py` hardcodes Chicago/16:00). Editing it in app.json does nothing. (Careful: StrictModel
  `extra="forbid"` means dropping the field breaks existing configs — keep field, document, or default+deprecate.)
- `DEFAULT_TIMEFRAMES` (`services/instruments.py:17`) production-dead; docstring claims app.py imports
  it — false since the coverage-maintainer replaced the OHLC post-tick hook.
- Test-only publics: `notes.get_note`/`delete_note`, `flags.get_flag`, `integrity_db.list_open_for_pair`,
  `models.ChartDefaults` (the chart-defaults flow passes raw dicts, quietly sidestepping the
  "Pydantic at every boundary" rule — use it or delete it), the entire 87-line `models/__init__.py`
  re-export surface.
- OHLC: `SourceRegistry.sources_for`, `reach.is_out_of_reach` (fold into B1's helper),
  `gap_reports.list_open` (route hand-rolls the same SQL instead — inverse duplication).
- Stale plan-era comments: `routes/health.py:28-35` ("Plan 17 hardens this" — shipped; healthz still
  hardcodes `pool_saturated = False` though `system_health_snapshot` measures it), `background.py:25-26`,
  `fetcher.py:93-95` (`post_import` trigger no longer exists), `gap_detection.py:131-133`,
  `routes/ohlc.py:123-128` (clamp rationale describes pre-711aedf breaker behavior).

Frontend:
- `stats_charts.js:99-181` `mountHistogramChart` + private helpers — imported nowhere (~85 lines).
- `api.js:95` dead sign ternary; `PriceChart.js:583` references never-assigned `_lastClickHit`.
- Dead template attrs (`data-endpoint` on 3 settings templates, `data-active-tab`) and ~70 lines of
  dead CSS (grep-confirmed): settings.css `.row-actions`, `.badge*`, `.coverage-state`, `.dot*`,
  `.btn-danger`, `.field-name`; stats.css all `.reports-page`, `.filter-bar button.active`.

ninjascript (~400+ lines):
- `TradeFeedbackAddOn.cs:696-985` entire duplicated `ValidationPanel` WPF class — unreachable.
- `ExecutionExporter.cs:487-528` `WriteToFileWithRetry` — never called, ignores its `append` param.
- Assorted: `ShowValidationPanelForActiveCharts` stub, write-only fields, unused usings, stale
  "FuturesTradingLog" identity comments.

---

## Tier 4 — Doc drift (free fixes)

- **CLAUDE.md "Post-tick hook chain" section is wrong**: describes the OHLC post-tick hook +
  `ohlc_refresh_recent`/`ohlc_refresh_week` jobs; plan-19 tests assert the opposite (only
  `_integrity_hook` registered; jobs are `ohlc_coverage_maintainer`/`ohlc_historical_sweep`/`ohlc_self_heal`).
- `windows/CLAUDE.md` + README say the launcher opens WebView2; actually Python does (`main.py:84-93`).
- Two different constants both named `CANONICAL_TIMEFRAMES` (`routes/ohlc.py:11` vs
  `routes/monitoring.py:18`) with different contents — rename to `CHART_TIMEFRAMES`/`HEALTH_TIMEFRAMES`.

## Confirmations of known deferred follow-ups (not new)
- Sweep bypasses gap backoff (`coverage_maintainer.py:74-87` ignores `next_retry_at`).
- Stale abandoned gaps never purged (no expiry path; `trim_older_than` trims attempts only).
- Self-heal never threads `attempt_id` into `record_retry_outcome` — `app.py:98 _fetch` discards
  `FetchResult`, so the schema's retry↔attempt correlation never happens.

---

## Suggested execution order

1. **Bug fixes, one commit each with a test:** B2, B3, B4 (backend params/settings) → B5, B6, B7, B8, B1
   (OHLC) → B9, B10 (frontend) → B12 (test fix). B11's payload-script fixes (exclusions) are low-risk;
   B11's ninjascript items need their own session + a decision on deleting TradeFeedbackIndicator.cs.
2. **Foundations:** D2 (`db.transaction`) → D1 (`execution_db`) → D3 (config savers + single-validator).
3. **Frontend:** D4 (`format.js` + api.js sweep, file-by-file) → D5 (`ohlc_jobs.js`).
4. **Tests:** D6 (conftest fixtures; migrate opportunistically).
5. **Doc sync:** Tier 4 + stale comments (free, do anytime).
6. **Last:** D7 (fetcher restructure) and D9 (ninjascript), each as its own plan.
