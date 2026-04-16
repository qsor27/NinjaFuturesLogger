# Position Detail — Per-Exit P&L, Commission Fallback, Color-Coded Header

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-exit P&L columns to the executions table on the position detail page, a `commission_per_contract` fallback field to the instrument registry, and green/red color-coding for P&L in the position header.

**Architecture:** `commission_per_contract` is a new optional field (default `0.0`) on `InstrumentConfig`; a new `effective_commission()` helper in `services/instruments.py` applies the fallback rule. The executions API endpoint is enriched server-side with `avg_entry_price`, `pnl_points`, and `pnl_dollars_net` for exit rows. The JS reads these pre-computed values and renders new columns and color classes.

**Tech Stack:** Python/Flask, Pydantic v2 (`StrictModel`), SQLite, vanilla ES modules, `base.html` already defines `.pnl-pos` / `.pnl-neg` CSS classes.

---

## File map

| File | Change |
|---|---|
| `models/settings.py` | Add `commission_per_contract: float = 0.0` to `InstrumentConfig` |
| `services/instruments.py` | Add `effective_commission()` helper function |
| `routes/positions.py` | Enrich `get_executions` endpoint response |
| `templates/settings_instruments.html` | Add Commission column + dialog field |
| `static/js/settings_instruments.js` | Read/write `commission_per_contract` |
| `static/js/position_detail.js` | Color-code header P&L; new table columns |
| `tests/test_models_settings.py` | Tests for new `commission_per_contract` field |
| `tests/test_instruments.py` | Tests for `effective_commission()` |
| `tests/test_routes_positions_detail.py` | Tests for enriched executions response |
| `tests/test_settings_routes_instruments.py` | Round-trip test for `commission_per_contract` |

---

## Task 1: Add `commission_per_contract` to `InstrumentConfig` and `effective_commission()` helper

**Files:**
- Modify: `models/settings.py`
- Modify: `services/instruments.py`
- Test: `tests/test_models_settings.py`
- Test: `tests/test_instruments.py`

- [ ] **Step 1.1 — Write failing tests for the model field**

Add to `tests/test_models_settings.py`:

```python
def test_instrument_config_commission_defaults_to_zero():
    raw = {
        "display_name": "E-mini Nasdaq-100",
        "multiplier": 20.0,
        "tick_size": 0.25,
        "sources": {
            "yfinance": {"continuous": "NQ=F", "contract_template": None},
            "stooq": {"continuous": "nq.f", "contract_template": None},
        },
        "session": {
            "timezone": "America/Chicago",
            "open": "17:00",
            "close": "16:00",
            "daily_break_start": "16:00",
            "daily_break_end": "17:00",
        },
    }
    cfg = InstrumentConfig(**raw)
    assert cfg.commission_per_contract == 0.0


def test_instrument_config_commission_round_trips():
    raw = {
        "display_name": "Micro E-mini Nasdaq-100",
        "multiplier": 2.0,
        "tick_size": 0.25,
        "commission_per_contract": 1.08,
        "sources": {
            "yfinance": {"continuous": "MNQ=F", "contract_template": None},
            "stooq": {"continuous": "mnq.f", "contract_template": None},
        },
        "session": {
            "timezone": "America/Chicago",
            "open": "17:00",
            "close": "16:00",
            "daily_break_start": "16:00",
            "daily_break_end": "17:00",
        },
    }
    cfg = InstrumentConfig(**raw)
    assert cfg.commission_per_contract == 1.08
    assert cfg.model_dump()["commission_per_contract"] == 1.08
```

- [ ] **Step 1.2 — Run tests to verify they fail**

```
pytest tests/test_models_settings.py::test_instrument_config_commission_defaults_to_zero tests/test_models_settings.py::test_instrument_config_commission_round_trips -v
```

Expected: FAIL — `InstrumentConfig` has no `commission_per_contract` field.

- [ ] **Step 1.3 — Add the field to `InstrumentConfig`**

In `models/settings.py`, change `InstrumentConfig`:

```python
class InstrumentConfig(StrictModel):
    display_name: str
    multiplier: float
    tick_size: float
    sources: InstrumentSources
    session: InstrumentSession
    commission_per_contract: float = 0.0
```

- [ ] **Step 1.4 — Run model tests to verify they pass**

```
pytest tests/test_models_settings.py -v
```

Expected: all PASS.

- [ ] **Step 1.5 — Write failing tests for `effective_commission()`**

Add to `tests/test_instruments.py`:

```python
from services.instruments import effective_commission


def test_effective_commission_uses_execution_value_when_positive():
    # NT provides commission > 0 — use it regardless of instrument config
    assert effective_commission("MNQ", execution_commission=3.24, quantity=3) == 3.24


def test_effective_commission_uses_fallback_when_execution_is_zero(tmp_path):
    import json
    from services.instruments import set_registry_path
    instruments_json = tmp_path / "instruments.json"
    instruments_json.write_text(json.dumps({
        "MNQ": {
            "display_name": "Micro E-mini Nasdaq-100",
            "multiplier": 2.0,
            "tick_size": 0.25,
            "commission_per_contract": 1.08,
            "sources": {
                "yfinance": {"continuous": "MNQ=F", "contract_template": None},
                "stooq": {"continuous": "mnq.f", "contract_template": None},
            },
            "session": {
                "timezone": "America/Chicago",
                "open": "17:00",
                "close": "16:00",
                "daily_break_start": "16:00",
                "daily_break_end": "17:00",
            },
        }
    }))
    set_registry_path(instruments_json)
    # NT reports 0 (sim-style), fallback applies: 1.08 × 2 contracts
    assert effective_commission("MNQ", execution_commission=0.0, quantity=2) == pytest.approx(2.16)


def test_effective_commission_zero_when_no_fallback_configured():
    # NT reports 0, no commission_per_contract set → stays 0 (sim account)
    assert effective_commission("MNQ", execution_commission=0.0, quantity=5) == 0.0


def test_effective_commission_zero_for_unknown_instrument():
    assert effective_commission("ZZZZ", execution_commission=0.0, quantity=1) == 0.0
```

Add `import pytest` at the top of the test file if not already present.

- [ ] **Step 1.6 — Run tests to verify they fail**

```
pytest tests/test_instruments.py::test_effective_commission_uses_execution_value_when_positive tests/test_instruments.py::test_effective_commission_uses_fallback_when_execution_is_zero tests/test_instruments.py::test_effective_commission_zero_when_no_fallback_configured tests/test_instruments.py::test_effective_commission_zero_for_unknown_instrument -v
```

Expected: FAIL — `effective_commission` not defined.

- [ ] **Step 1.7 — Add `effective_commission()` to `services/instruments.py`**

Add after the `get_multiplier` function:

```python
def effective_commission(instrument: str, execution_commission: float, quantity: int) -> float:
    """Return the commission to use for P&L calculations.

    Rule: use NT-reported commission if > 0; otherwise fall back to
    commission_per_contract × quantity from the instrument registry.
    A fallback of 0 means 'not configured' (e.g. sim accounts).
    """
    if execution_commission > 0:
        return execution_commission
    cfg = _REGISTRY.get(base_symbol(instrument))
    if cfg is None or cfg.commission_per_contract <= 0:
        return 0.0
    return cfg.commission_per_contract * quantity
```

- [ ] **Step 1.8 — Run all instrument tests**

```
pytest tests/test_instruments.py tests/test_models_settings.py tests/test_instrument_registry.py -v
```

Expected: all PASS.

- [ ] **Step 1.9 — Commit**

```bash
git add models/settings.py services/instruments.py tests/test_models_settings.py tests/test_instruments.py
git commit -m "feat: add commission_per_contract to InstrumentConfig and effective_commission helper"
```

---

## Task 2: Enrich executions API endpoint with per-exit P&L

**Files:**
- Modify: `routes/positions.py`
- Test: `tests/test_routes_positions_detail.py`

- [ ] **Step 2.1 — Write failing tests**

Add to `tests/test_routes_positions_detail.py`:

```python
def test_executions_endpoint_entry_rows_have_null_pnl(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path)
        resp = app.test_client().get("/api/positions/Sim/MNQ/a/executions")
        assert resp.status_code == 200
        body = resp.get_json()
        entry = next(e for e in body["executions"] if e["entry_exit"] == "Entry")
        assert entry["avg_entry_price"] is None
        assert entry["pnl_points"] is None
        assert entry["pnl_dollars_net"] is None
    finally:
        services.stop()


def test_executions_endpoint_exit_rows_have_pnl(tmp_config):
    # MNQ Long: entry 100.0, exit 101.0, qty 1, commission 0
    # MNQ multiplier = 2.0
    # pnl_points = (101.0 - 100.0) * 1 * 1 = 1.0
    # pnl_dollars_net = 1.0 * 2.0 - 0.0 = 2.0
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path)
        resp = app.test_client().get("/api/positions/Sim/MNQ/a/executions")
        assert resp.status_code == 200
        body = resp.get_json()
        exit_row = next(e for e in body["executions"] if e["entry_exit"] == "Exit")
        assert exit_row["avg_entry_price"] == pytest.approx(100.0)
        assert exit_row["pnl_points"] == pytest.approx(1.0)
        assert exit_row["pnl_dollars_net"] == pytest.approx(2.0)
    finally:
        services.stop()


def test_executions_endpoint_exit_pnl_uses_commission_fallback(tmp_path, tmp_config):
    import json
    from services.instruments import set_registry_path
    instruments_json = tmp_path / "instruments.json"
    instruments_json.write_text(json.dumps({
        "MNQ": {
            "display_name": "Micro E-mini Nasdaq-100",
            "multiplier": 2.0,
            "tick_size": 0.25,
            "commission_per_contract": 1.08,
            "sources": {
                "yfinance": {"continuous": "MNQ=F", "contract_template": None},
                "stooq": {"continuous": "mnq.f", "contract_template": None},
            },
            "session": {
                "timezone": "America/Chicago",
                "open": "17:00",
                "close": "16:00",
                "daily_break_start": "16:00",
                "daily_break_end": "17:00",
            },
        }
    }))
    set_registry_path(instruments_json)
    app, services = create_app(tmp_config, start_background=False)
    try:
        _seed(tmp_config.db_path)  # seeds MNQ with commission=0.0
        resp = app.test_client().get("/api/positions/Sim/MNQ/a/executions")
        body = resp.get_json()
        exit_row = next(e for e in body["executions"] if e["entry_exit"] == "Exit")
        # pnl_points = 1.0, multiplier = 2.0, eff_comm = 1.08 × 1 = 1.08
        # pnl_dollars_net = 2.0 - 1.08 = 0.92
        assert exit_row["pnl_dollars_net"] == pytest.approx(0.92)
    finally:
        services.stop()
```

Add `import pytest` to the imports at the top of `tests/test_routes_positions_detail.py`.

- [ ] **Step 2.2 — Run tests to verify they fail**

```
pytest tests/test_routes_positions_detail.py::test_executions_endpoint_entry_rows_have_null_pnl tests/test_routes_positions_detail.py::test_executions_endpoint_exit_rows_have_pnl tests/test_routes_positions_detail.py::test_executions_endpoint_exit_pnl_uses_commission_fallback -v
```

Expected: FAIL — the executions response has no `avg_entry_price`, `pnl_points`, or `pnl_dollars_net` keys.

- [ ] **Step 2.3 — Enrich `get_executions` in `routes/positions.py`**

Add these imports at the top of `routes/positions.py` (after existing imports):

```python
from services.instruments import effective_commission, get_multiplier
```

Replace the `get_executions` function body (lines 117–145) with:

```python
    @bp.get("/api/positions/<account>/<instrument>/<entry_execution_id>/executions")
    def get_executions(account: str, instrument: str, entry_execution_id: str):
        p = get_position(
            _db_path(),
            account=account,
            instrument=instrument,
            entry_execution_id=entry_execution_id,
        )
        if p is None:
            return jsonify({"error": "not found"}), 404
        from services.notes import strip_split_suffix

        wanted = {strip_split_suffix(eid) for eid in p.execution_ids}
        conn = connect(_db_path())
        try:
            rows = conn.execute(
                "SELECT nt_execution_id, account, instrument, timestamp, side,"
                " original_action, quantity, price, commission, entry_exit,"
                " position_after, source_order_id, source_filename, imported_at "
                "FROM executions WHERE account = ? AND instrument = ? "
                "ORDER BY timestamp, nt_execution_id",
                (account, instrument),
            ).fetchall()
        finally:
            conn.close()

        sign = 1 if p.side == "Long" else -1
        multiplier = get_multiplier(p.instrument)
        executions = []
        for r in rows:
            if r["nt_execution_id"] not in wanted:
                continue
            e = dict(r)
            if e["entry_exit"] == "Exit":
                eff_comm = effective_commission(p.instrument, e["commission"], e["quantity"])
                pnl_points = (e["price"] - p.entry_price) * e["quantity"] * sign
                e["avg_entry_price"] = p.entry_price
                e["pnl_points"] = round(pnl_points, 4)
                e["pnl_dollars_net"] = round(pnl_points * multiplier - eff_comm, 2)
            else:
                e["avg_entry_price"] = None
                e["pnl_points"] = None
                e["pnl_dollars_net"] = None
            executions.append(e)
        return jsonify({"executions": executions})
```

- [ ] **Step 2.4 — Run all positions-detail tests**

```
pytest tests/test_routes_positions_detail.py -v
```

Expected: all PASS.

- [ ] **Step 2.5 — Run the full test suite to catch regressions**

```
pytest -x -q
```

Expected: all PASS.

- [ ] **Step 2.6 — Commit**

```bash
git add routes/positions.py tests/test_routes_positions_detail.py
git commit -m "feat: enrich executions endpoint with per-exit pnl_points and pnl_dollars_net"
```

---

## Task 3: Instruments settings UI — commission_per_contract field

**Files:**
- Modify: `templates/settings_instruments.html`
- Modify: `static/js/settings_instruments.js`
- Test: `tests/test_settings_routes_instruments.py`

- [ ] **Step 3.1 — Write failing API round-trip test**

Add to `tests/test_settings_routes_instruments.py`:

```python
def test_put_instrument_commission_per_contract_round_trips(tmp_path: Path):
    client = _setup_app(tmp_path)
    payload = {
        "display_name": "Micro E-mini Nasdaq-100",
        "multiplier": 2.0,
        "tick_size": 0.25,
        "commission_per_contract": 1.08,
        "sources": {
            "yfinance": {"continuous": "MNQ=F", "contract_template": None},
            "stooq": {"continuous": "mnq.f", "contract_template": None},
        },
        "session": {
            "timezone": "America/Chicago",
            "open": "17:00",
            "close": "16:00",
            "daily_break_start": "16:00",
            "daily_break_end": "17:00",
        },
    }
    res = client.put("/api/config/instruments/MNQ", json=payload)
    assert res.status_code == 200
    body = res.get_json()
    assert body["instrument"]["commission_per_contract"] == 1.08

    res = client.get("/api/config/instruments")
    assert res.get_json()["instruments"]["MNQ"]["commission_per_contract"] == 1.08


def test_existing_instruments_default_commission_to_zero(tmp_path: Path):
    # Seeded instruments (ES, NQ, etc.) have no commission_per_contract → default 0.0
    client = _setup_app(tmp_path)
    res = client.get("/api/config/instruments")
    body = res.get_json()
    assert body["instruments"]["ES"]["commission_per_contract"] == 0.0
```

- [ ] **Step 3.2 — Run tests to verify they fail**

```
pytest tests/test_settings_routes_instruments.py::test_put_instrument_commission_per_contract_round_trips tests/test_settings_routes_instruments.py::test_existing_instruments_default_commission_to_zero -v
```

Expected: FAIL for `test_put_instrument_commission_per_contract_round_trips` (model not yet accepting the field — wait, it IS now after Task 1). Actually both should PASS after Task 1. Let's run them to confirm:

```
pytest tests/test_settings_routes_instruments.py -v
```

Expected: all PASS (the API layer already passes `**body` straight to `InstrumentConfig`; since the model now accepts `commission_per_contract`, no route changes needed).

- [ ] **Step 3.3 — Update `templates/settings_instruments.html`**

Add `<th>Commission/ct</th>` to the table header after `<th>Tick</th>`, and add the dialog field after `tick_size`. Replace the relevant sections:

Table header — change:
```html
          <th>Symbol</th><th>Display name</th><th>Multiplier</th><th>Tick</th>
          <th>yfinance</th><th>stooq</th><th>Session</th><th></th>
```
to:
```html
          <th>Symbol</th><th>Display name</th><th>Multiplier</th><th>Tick</th>
          <th>Commission/ct</th><th>yfinance</th><th>stooq</th><th>Session</th><th></th>
```

Dialog form — add after `<label>Tick size <input name="tick_size" type="number" step="any" required></label>`:
```html
      <label>Commission per contract ($) <input name="commission_per_contract" type="number" step="any" min="0" placeholder="0.00 = not configured"></label>
```

- [ ] **Step 3.4 — Update `static/js/settings_instruments.js`**

**In `refresh()`** — change the `innerHTML` template from 7 blank `<td>` + 1 actions `<td>` to 8 blank + 1 actions, and update cell indices:

Replace:
```js
    tr.innerHTML = `
      <td></td><td></td><td></td><td></td><td></td><td></td><td></td>
      <td><button data-act="edit"></button> <button data-act="del"></button></td>
    `;
    const cells = tr.querySelectorAll("td");
    cells[0].textContent = symbol;
    cells[1].textContent = cfg.display_name;
    cells[2].textContent = cfg.multiplier;
    cells[3].textContent = cfg.tick_size;
    cells[4].textContent = cfg.sources?.yfinance?.continuous ?? "";
    cells[5].textContent = cfg.sources?.stooq?.continuous ?? "";
    const s = cfg.session;
    cells[6].textContent = s ? `${s.timezone} · ${s.open}–${s.close}` : "";
    cells[6].title = s ? `Break ${s.daily_break_start}–${s.daily_break_end}` : "";
    const [editBtn, delBtn] = cells[7].querySelectorAll("button");
```
with:
```js
    tr.innerHTML = `
      <td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td>
      <td><button data-act="edit"></button> <button data-act="del"></button></td>
    `;
    const cells = tr.querySelectorAll("td");
    cells[0].textContent = symbol;
    cells[1].textContent = cfg.display_name;
    cells[2].textContent = cfg.multiplier;
    cells[3].textContent = cfg.tick_size;
    const commRate = cfg.commission_per_contract;
    cells[4].textContent = commRate > 0 ? `$${commRate}` : "—";
    cells[5].textContent = cfg.sources?.yfinance?.continuous ?? "";
    cells[6].textContent = cfg.sources?.stooq?.continuous ?? "";
    const s = cfg.session;
    cells[7].textContent = s ? `${s.timezone} · ${s.open}–${s.close}` : "";
    cells[7].title = s ? `Break ${s.daily_break_start}–${s.daily_break_end}` : "";
    const [editBtn, delBtn] = cells[8].querySelectorAll("button");
```

**In `openDialog()`** — add after `elements.tick_size.value = cfg?.tick_size ?? "";`:
```js
  elements.commission_per_contract.value = cfg?.commission_per_contract ?? 0;
```

**In `saveDialog()`** — add `commission_per_contract` to the payload object after `tick_size`:
```js
    const payload = {
      display_name: f.display_name.value,
      multiplier: parseFloat(f.multiplier.value),
      tick_size: parseFloat(f.tick_size.value),
      commission_per_contract: parseFloat(f.commission_per_contract.value) || 0.0,
      sources: {
        yfinance: { continuous: f.yfinance_continuous.value || null, contract_template: null },
        stooq: { continuous: f.stooq_continuous.value || null, contract_template: null },
      },
      session: {
        timezone: f.session_timezone.value,
        open: f.session_open.value,
        close: f.session_close.value,
        daily_break_start: f.session_break_start.value,
        daily_break_end: f.session_break_end.value,
      },
    };
```

- [ ] **Step 3.5 — Run the full settings instruments test suite**

```
pytest tests/test_settings_routes_instruments.py -v
```

Expected: all PASS.

- [ ] **Step 3.6 — Run full test suite**

```
pytest -x -q
```

Expected: all PASS.

- [ ] **Step 3.7 — Commit**

```bash
git add templates/settings_instruments.html static/js/settings_instruments.js tests/test_settings_routes_instruments.py
git commit -m "feat: add commission_per_contract field to instruments settings UI"
```

---

## Task 4: position_detail.js — color-coded P&L header and updated executions table

**Files:**
- Modify: `static/js/position_detail.js`

Note: `base.html` already defines `.pnl-pos { color: #6ee7b7; }` and `.pnl-neg { color: #fda4af; }`. No CSS changes needed.

- [ ] **Step 4.1 — Update `renderHeader()` to color-code P&L rows**

In `static/js/position_detail.js`, replace the `renderHeader` function (lines 33–59):

```js
function renderHeader(detail) {
  const p = detail.position;
  setText(title, `${p.instrument} ${p.side} × ${p.quantity}`);
  const rows = [
    ["Account", p.account, null],
    ["Instrument", p.instrument, null],
    ["Side", p.side, null],
    ["Qty", p.quantity, null],
    ["Entry time", formatTime(p.entry_time), null],
    ["Exit time", formatTime(p.exit_time), null],
    ["Entry price", p.entry_price.toFixed(2), null],
    ["Exit price", p.exit_price !== null ? p.exit_price.toFixed(2) : "—", null],
    ["Points P&L", p.points_pnl !== null ? p.points_pnl.toFixed(2) : "—", p.points_pnl],
    ["$ P&L", formatDollars(p.dollars_pnl).text, p.dollars_pnl],
    ["Commission", `$${p.commission.toFixed(2)}`, null],
    ["Duration", p.duration_minutes !== null ? p.duration_minutes.toFixed(1) + " m" : "—", null],
  ];
  headerDl.innerHTML = "";
  for (const [label, value, pnlValue] of rows) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    setText(dt, label);
    setText(dd, value);
    if (pnlValue !== null && pnlValue !== undefined) {
      if (pnlValue > 0) dd.classList.add("pnl-pos");
      else if (pnlValue < 0) dd.classList.add("pnl-neg");
    }
    headerDl.appendChild(dt);
    headerDl.appendChild(dd);
  }
}
```

- [ ] **Step 4.2 — Update `renderExecutions()` to show per-exit P&L columns**

In `static/js/position_detail.js`, replace the `renderExecutions` function (lines 103–139):

```js
function renderExecutions(executions, detail) {
  executionsRoot.innerHTML = "";
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  thead.innerHTML = `
    <tr><th>ID</th><th>Time</th><th>Side</th><th>Qty</th><th>Price</th><th>Avg Entry</th><th>Pts P&L</th><th>$ P&L (net)</th><th>Commission</th><th>Action</th></tr>`;
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  for (const e of executions) {
    const tr = document.createElement("tr");
    tr.dataset.executionId = e.nt_execution_id;
    tr.style.cursor = "pointer";
    tr.addEventListener("click", () => {
      document.dispatchEvent(
        new CustomEvent("executions-table:row-clicked", {
          detail: { executionId: e.nt_execution_id },
        }),
      );
    });
    const td = (text, cssClass) => {
      const c = document.createElement("td");
      setText(c, text);
      if (cssClass) c.className = cssClass;
      return c;
    };
    const pnlClass = (val) => {
      if (val === null || val === undefined) return null;
      if (val > 0) return "pnl-pos";
      if (val < 0) return "pnl-neg";
      return null;
    };
    tr.appendChild(td(e.nt_execution_id));
    tr.appendChild(td(formatTime(e.timestamp)));
    tr.appendChild(td(e.side));
    tr.appendChild(td(e.quantity));
    tr.appendChild(td(e.price.toFixed(2)));
    tr.appendChild(td(e.avg_entry_price !== null ? e.avg_entry_price.toFixed(2) : "—"));
    tr.appendChild(td(e.pnl_points !== null ? e.pnl_points.toFixed(2) : "—", pnlClass(e.pnl_points)));
    tr.appendChild(td(e.pnl_dollars_net !== null ? `$${e.pnl_dollars_net.toFixed(2)}` : "—", pnlClass(e.pnl_dollars_net)));
    tr.appendChild(td(`$${e.commission.toFixed(2)}`));
    tr.appendChild(td(e.original_action));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  executionsRoot.appendChild(table);
}
```

- [ ] **Step 4.3 — Run full test suite**

```
pytest -x -q
```

Expected: all PASS (no Python tests cover this JS; the suite should be clean).

- [ ] **Step 4.4 — Validate in browser using Claude-in-chrome**

Start the app:
```bash
docker compose up -d --build
```

Open http://localhost:8000, navigate to a closed position's detail page, and verify:
- Position header: Points P&L and $ P&L are green (winner) or red (loser)
- Executions table: exit rows show Avg Entry, Pts P&L, $ P&L (net) with color; entry rows show `—`
- Instruments settings (http://localhost:8000/settings/instruments): "Commission/ct" column visible; edit dialog has the new field with readable (white) text on dark background

- [ ] **Step 4.5 — Commit**

```bash
git add static/js/position_detail.js
git commit -m "feat: color-code position header P&L and add per-exit P&L columns to executions table"
```
