# Spec: Bulk-delete positions from history (issue #7)

## Problem
The Positions history page (`templates/positions_list.html`, `static/js/positions_list.js`) is read-only.
Users cannot remove old trades. The issue asks for:

- selecting trades in the list, including "select all" for the current account filter, and deleting them with one click;
- deleted trades to be permanently removed;
- better performance once there are thousands of trades.

Positions are not stored. `services/positions_service.py::list_positions_page` rebuilds them from the
`executions` table on every request (the "no cache" rule in its docstring). A position is a derived
grouping of executions, so "deleting a position" means deleting its executions. Deleting executions
cascades to notes, flags, custom-field values and review attempts (migrations 005, 006 and 013).
Deleting rows alone is also not enough for permanence: the importer could re-ingest the same
executions from the NinjaTrader inbox files (see Open questions).

## Scope
1. Row checkboxes and a header "select all on this page" checkbox in the positions table.
2. A "select all N matching the current filters" action. It is offered when an account filter is
   active, and covers every page of results, not only the visible one.
3. A "Delete selected" button with a confirmation dialog that states the number of positions
   (and executions) to be removed and says the action is permanent.
4. A new backend endpoint that permanently deletes the executions of the selected positions in
   one transaction.
5. Dependent rows removed or kept consistent: FK-cascaded rows (notes, flags, custom-field values,
   review attempts), plus `integrity_issues` rows for the deleted executions. Integrity issues have
   no FK.
6. A performance improvement for the list and delete paths, sized to thousands of positions.
   See Approach.

## Non-goals
- Deleting individual executions from within a position.
- Undo or soft-delete. The issue says permanent.
- Changes to import parsing, the OHLC/bars cache, or simulation definitions.
- Materialising or caching positions. This would reverse the "recompute every call" rule, so it
  needs a decision first (see Open questions).
- Multi-user permissions or auth. The app is single-user.

## Affected files
- `routes/positions.py`: new `POST /api/positions/delete` endpoint. Reuses `_parse_filter_from_query`
  semantics for the filter mode.
- `services/positions_service.py`: new `delete_positions(...)` function. Resolves the selection to
  execution IDs and deletes them. Also the place for list-path performance work.
- `services/import_db.py`: reuse `delete_executions` (already exists). It may need chunking for
  large ID lists because of SQLite's variable limit.
- `services/integrity_db.py`: delete integrity issues for removed executions.
- `static/js/positions_list.js`, `templates/positions_list.html`, and CSS in `static/`: checkboxes,
  select-all banner, delete button, confirm dialog. Selection must survive re-render and must not
  trigger the row-click navigation.
- `static/js/api.js`: possibly a small helper for POST/DELETE if none exists.
- `tests/`: new `tests/test_routes_positions_delete.py` and service-level tests.
- A new migration only if an index or the import-tombstone decision requires one.

## Approach
**Selection model.** The client sends one of two bodies:
- explicit: `{"positions": [{"account", "instrument", "entry_execution_id"}, ...]}`, for hand-picked rows;
- filter: `{"filter": {<same keys as GET /api/positions>}, "expected_count": N}`, for "select all
  matching". The server re-resolves the filter itself, so the client never has to hold thousands of IDs.
  It rejects the request with 409 if the resolved count differs from `expected_count`. This stops a
  stale view from deleting more than the user saw.
The filter form must require at least one account, as the issue describes. An empty account list in
filter mode returns 400. Other restrictions are an open question.

**Resolution and deletion.** The server builds positions with `build_positions`, applies
`apply_filters`, maps each position to its `execution_ids`, and strips split suffixes with
`strip_split_suffix` (`#close`/`#open` halves map to the parent row). It then deletes those
executions inside one `transaction()`, chunked under SQLite's variable limit. A reversal execution
shared by two adjacent positions is removed once, and both positions are affected. The confirm
dialog and response must report this.

**Cascades and cleanup.** FK cascades require `PRAGMA foreign_keys=ON` on the connection. Verify
this in `db.py` and add a test rather than assuming. Delete `integrity_issues` rows whose
`execution_id` was removed.

**Remaining positions.** Deleting part of a day's executions can change how the leftover
executions pair up, so surviving positions may be rebuilt differently. This is inherent in the
derived model. The spec requires the post-delete list to be consistent with a fresh walk of the
remaining executions.

**Performance.** The list endpoint reloads and re-walks every execution for every page request.
Measure first with a seeded DB of about 5,000 positions. Candidate fixes:
- push the instrument and account filters fully into SQL (multi-account currently loads all);
- add an index on `executions(account, instrument, timestamp)` if one is missing;
- avoid rebuilding positions for accounts excluded by the filter.
The delete itself removes the large-data cause directly. Any optimisation must keep the position
results identical.

## Acceptance criteria
1. The positions table has a checkbox per row and a header checkbox that selects all rows on the current page.
2. Clicking a row checkbox does not navigate to the detail page. Clicking elsewhere on the row still does.
3. When at least one account is selected in the account filter and the result spans more than one
   page, a banner offers "Select all N positions matching filters". Choosing it sets the selection
   to the full filtered result set, not only the visible page.
4. With no account filter, the select-all-matching action is not offered (page-level selection
   remains). *Confirm in Open questions.*
5. "Delete selected" is disabled when nothing is selected. Clicking it shows a confirmation that
   states the position count and that deletion is permanent. Cancel makes no change.
6. Confirming issues one request to `POST /api/positions/delete`. On success the list reloads at a
   valid page number (clamped if the current page no longer exists) and the selection is cleared.
7. Explicit mode: after deleting positions P1..Pk, `GET /api/positions` no longer returns them, and
   `GET /api/positions/<account>/<instrument>/<entry_execution_id>` returns 404 for each.
8. Filter mode: for a seeded DB with accounts A and B, deleting with `{"filter": {"account": ["A"]}}`
   removes every execution of A and none of B's.
9. Filter mode applies every filter field accepted by `GET /api/positions` (instrument, side,
   outcome, dates, and so on). Only positions matching the full filter are deleted.
10. Filter mode with `expected_count` different from the server-resolved count returns 409 and
    deletes nothing.
11. Filter mode with an empty or absent account list returns 400 and deletes nothing.
12. Invalid input (malformed body, unknown filter value, an empty or non-list `positions`, a position
    that does not exist) returns 400 or 404 with a JSON `error`. The operation is atomic: on any
    failure no rows are deleted.
13. Deleted executions are gone from the `executions` table. Rows in `execution_notes`, the flags
    table, `execution_custom_field_values` and `review_attempts` referencing them are gone.
    `integrity_issues` rows for them are removed.
14. Executions of positions that were not selected are untouched. A reversal execution split into
    `#close`/`#open` halves is deleted via its real ID, and the response reports the number of
    executions actually deleted.
15. The response is `{"deleted_positions": n, "deleted_executions": m}`.
16. A deleted trade does not reappear after the importer next runs over the same source file (per the
    Open question resolution). The test re-runs the importer on the original file and asserts the
    rows stay deleted.
17. Performance: with a seeded DB of 5,000 positions, `GET /api/positions?page=1` completes within a
    budget agreed in review. The test asserts a generous bound, or compares the number of DB queries
    or rows loaded, to avoid flakiness. Results are identical to those before the optimisation.
18. All pre-existing tests pass unchanged, apart from the deselects already in `.ci/test.sh`.

## Test plan
`./.ci/kit/remote-test.sh` runs `.ci/test.sh`, which runs `ruff` and `pytest`. It must prove:
- Route tests in `tests/test_routes_positions_delete.py`, using the existing fixtures from
  `tests/test_routes_positions.py`, cover criteria 7-12, 14 and 15: happy paths, 400/404/409,
  and atomicity (inject a failure mid-delete, then assert the row count is unchanged).
- Service tests cover criteria 13 and 14: cascade and cleanup of dependent tables (including that
  foreign keys are enforced on the connection), split-suffix handling, chunking with more than
  1,000 IDs, and positions sharing a reversal execution.
- An importer test covers criterion 16 (re-import after delete).
- A performance regression test covers criterion 17, with a seeded dataset and a non-flaky assertion.
- The front-end has no JS test harness in the repo. Criteria 1-6 are covered by manual checks
  recorded in the PR description. If a harness is wanted, raise it on the issue.

## Open questions
1. **Re-import.** Deleted executions would be re-created if the importer re-reads the file (cursor
   reset, rollback and re-import, or a new file containing the same fills). Should deletion
   (a) just delete, accepting possible reappearance;
   (b) record tombstones of deleted `nt_execution_id`s that the importer skips; or
   (c) also advance or reset the import cursors? Criterion 16 assumes (b). Please confirm.
2. **Filter requirement.** Must "select all matching" require an account filter, as the issue says
   ("when they filter by an account")? Or should it also be allowed with only other filters
   (for example a date range across all accounts)?
3. **Meaning of "performance".** Is the slowness on the positions list, the statistics pages, or
   imports? Which pages and which data sizes should be the target? The spec only commits to the list
   endpoint plus the effect of deleting data. Should caching or materialising positions be in
   scope? That would break the documented "recompute every call" rule.
4. **Shared reversal executions.** Deleting one position whose closing execution is also the next
   position's opening (a reversal) removes both. Is that acceptable, or should it be blocked or warned?
5. **Confirmation strength.** Is a standard confirm dialog enough for a bulk, irreversible
   delete, or should the user type the account name or "DELETE"?
6. **Auditing.** Should deletions be logged (the `http.positions` logger, count and filter) or
   recorded in the DB for support bundles?
7. **Linked data.** Should OHLC bars cached for the affected instruments and dates be left alone
   (assumed yes, non-goal)?
