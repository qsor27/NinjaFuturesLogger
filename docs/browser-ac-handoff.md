# Handoff — Browser AC Walkthrough for FuturesTradingLog

You are a fresh Claude Code session launched with `--chrome` to drive a browser
through the manual acceptance-criteria checklist for this single-user Flask
app. You have Playwright-style browser tooling available
(`mcp__plugin_playwright_playwright__browser_*`) plus the usual Read/Edit/Bash
tools. Use them to open pages, take snapshots, click, type, and inspect the
DOM.

## What you are doing

The app rebuild finished plans 00–17 but every plan that has a user-facing
surface (13, 15, 16, 17) shipped with "in-browser walkthrough deferred." The
backend tests are green (589 passing, ruff clean). Your job is the front-end
verification pass — click every page, every button, every filter, and confirm
each spec acceptance criterion visually.

## The checklist

**Read `docs/browser-acceptance-checklist.md` first.** It has ~90 checkboxes
grouped into four sections (Plan 13 / 15 / 16 / 17), each tied to a numbered AC
in `docs/rebuild-spec/{13,15,16,17}-*.md`. You will work through it one plan
section at a time, editing the file in place to mark items complete or flag
failures.

- **Pass**: change `- [ ]` to `- [x]`.
- **Fail**: change to `- [x] AC7 — **FAIL**: <one-line reason>. <optional
  details>`. Do NOT skip or re-order items.
- **Blocked / unverifiable**: `- [ ] AC20 — **BLOCKED**: need to force circuit
  breaker open; see note below`. Add a short explanation, do not mark complete.

## Environment facts

- App URL: `http://localhost:8000`
- Host project directory: `C:\Projects\NinjaFuturesLogger`
- Host bind mount for app data: `C:\Containers\NinjaFuturesLogger` → `/app/data`
  in the container
- CSV inbox (drop here to trigger import): `C:\Containers\NinjaFuturesLogger\inbox\`
- Config file (JSON, editable): `C:\Containers\NinjaFuturesLogger\config\app.json`
- Instruments registry (JSON, editable): `C:\Containers\NinjaFuturesLogger\config\instruments.json`
- Healthz endpoint: `GET http://localhost:8000/healthz`
- Solo-on-master workflow — no PRs, no feature branches. Commit checklist edits
  directly to master when you finish each plan section.

## Prerequisites check — do this first, stop if any fails

1. `docker compose ps` — expect exactly one service `futurestradinglog` with
   status `Up (healthy)`. If not healthy, run `docker compose up -d --build`
   and wait ~20 seconds, then recheck.
2. `curl -fsS http://localhost:8000/healthz` — expect 200.
3. Open `http://localhost:8000/positions` in the browser — expect at least one
   closed position visible. If the list is empty, stop and tell the user
   "I need real data to run the walkthrough — please drop a CSV into
   `C:\Containers\NinjaFuturesLogger\inbox\`."
4. Confirm the `instruments.json` file exists at
   `C:\Containers\NinjaFuturesLogger\config\instruments.json`. If not, the
   plan 16 seed step hasn't run; stop and tell the user.

If any of the above fails, do NOT start the walkthrough. Stop and report.

## How to work through a plan section

Work **one plan at a time**, in order 13 → 15 → 16 → 17. After each plan:

1. Announce which plan section you are starting, then open the first page in
   scope (e.g. a position detail URL for plan 13).
2. For each checkbox in order:
   - Read the AC item text.
   - Take a browser snapshot if the item is about visual layout, or inspect
     the DOM / Network tab for structural items.
   - For interactive items (click a button, toggle a filter), actually perform
     the click via the browser tool and verify the result.
   - Edit `docs/browser-acceptance-checklist.md` inline with the pass/fail
     result immediately. Do not batch — the checklist is your running state.
3. After the last item in the section, run `pytest -q` once as a smoke check
   (it should stay green since you haven't touched code). Commit the checklist
   edits with `docs: walkthrough plan N — <pass-count> pass, <fail-count> fail`.
4. Stop and summarize to the user before starting the next plan. Do not run
   the whole walkthrough without a review checkpoint.

## What to probe vs. what to eyeball

Several ACs require forcing unusual states (circuit breakers open, source
unavailable, rollback cascades). For those:

- **Circuit breakers open (plan 13 AC 20, plan 17 data-health banner)**: you
  can't easily force this from the browser. Mark BLOCKED with a note that it
  needs manual network isolation, and move on.
- **Multiplier change recomputes P&L (plan 16 AC 3.1)**: change it via
  `/settings/instruments`, then reload `/positions` and check one known row's
  `dollars_pnl`. Use the API (`curl` via Bash) as the source of truth.
- **Rollback cascade (plan 17 imports detail)**: pick a tick you can afford to
  roll back, actually click the button, then verify the executions and any
  linked notes/flags/custom field values are gone via API.
- **Anything involving timing (auto-refresh every 10s, flash for ~2s)**: watch
  the browser snapshot twice, separated by ~3 and ~12 seconds.

## Constraints

- Do NOT change application code. This is a verification pass, not a fix pass.
  If you find a bug, record it as **FAIL** with a short repro and move on.
  The user will triage and dispatch a separate session to fix.
- Do NOT modify `instruments.json`, `app.json`, or DB files unless the
  checklist explicitly asks you to (e.g. plan 16 AC 3.1 changes a multiplier).
  Restore any test edits before moving to the next plan section.
- Do NOT commit anything except edits to
  `docs/browser-acceptance-checklist.md`.
- Do NOT skip ACs. Mark BLOCKED if you can't verify, never silently skip.
- Report length: keep updates terse, one sentence per AC.

## Reference docs

- `CLAUDE.md` — project architecture + load-bearing rules (read this)
- `docs/browser-acceptance-checklist.md` — **the checklist you are executing**
- `docs/rebuild-spec/13-charting.md` — plan 13 ACs
- `docs/rebuild-spec/15-statistics.md` — plan 15 ACs
- `docs/rebuild-spec/16-settings-instruments.md` — plan 16 ACs
- `docs/rebuild-spec/17-import-monitoring.md` — plan 17 ACs

## First action

Read `docs/browser-acceptance-checklist.md` top to bottom. Then run the
prerequisites check. If all four prerequisites pass, announce "Prerequisites
green, starting Plan 13 walkthrough" and open the first position detail page.
Otherwise stop and report what's missing.
