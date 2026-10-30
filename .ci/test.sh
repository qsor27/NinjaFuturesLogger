#!/usr/bin/env bash
# Test entrypoint for NinjaFuturesLogger. Runs INSIDE the disposable LXC (as root, in /work).
# Starting point from repo-kit/repo-tests - this file is owned by the repo once created.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv /tmp/venv
/tmp/venv/bin/pip install -q -r requirements.txt pytest ruff
# Lint is report-only until the existing findings are fixed (3 import-order errors at rollout);
# then drop --exit-zero so new lint errors fail the run.
/tmp/venv/bin/ruff check --exit-zero .
# testpaths=tests keeps windows/payload out. Deselected: date-bound tests that expect the June 2026
# front-month contract (MNQM26) - tracked in a repo issue; remove the deselects when fixed.
/tmp/venv/bin/python -m pytest -q \
  --deselect tests/test_yfinance_fallback.py::test_fallback_triggers_when_specific_contract_lookup_fails \
  --deselect tests/test_yfinance_fallback.py::test_no_fallback_when_window_outside_front_month \
  --deselect tests/test_yfinance_fallback.py::test_specific_contract_success_skips_fallback
