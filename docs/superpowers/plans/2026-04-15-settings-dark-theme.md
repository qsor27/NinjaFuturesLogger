# Settings Dark Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the statistics-page dark fintech theme to all settings pages, add a settings sub-navigation, and clean up the settings forms visually.

**Architecture:** Pure CSS/HTML change — no JS logic, no route changes, no API changes. `settings.css` (already loaded globally via `base.html`) is rewritten with dark-theme variables and all settings-specific component styles. Each settings template gets a `.settings-shell` wrapper and a sub-nav. The existing JS files are left completely untouched — all their DOM `getElementById`/`querySelector` targets are preserved.

**Tech Stack:** Jinja2 templates, plain CSS, no build step.

---

## File Map

| File | Change |
|------|--------|
| `static/css/settings.css` | Full rewrite — dark variables, all component styles |
| `templates/settings_index.html` | Add `.settings-shell`, card-style list |
| `templates/settings_instruments.html` | Add sub-nav + `.settings-shell`, wrap table in cards |
| `templates/settings_chart.html` | Add sub-nav + `.settings-shell`, restructure form into card |
| `templates/settings_custom_fields.html` | Add sub-nav + `.settings-shell`, wrap in cards |

No other files change. The JS files `settings_instruments.js`, `settings_chart.js`, `settings_custom_fields.js` are **not touched**.

---

### Task 1: Rewrite `settings.css` with full dark theme

**Files:**
- Modify: `static/css/settings.css`

- [ ] **Step 1: Replace the entire contents of `static/css/settings.css`**

```css
/* Settings pages — dark fintech theme, mirrors stats.css variables */

/* Re-declare the same tokens so settings.css is self-contained.
   stats.css also declares these; last-load wins but values are identical. */
:root {
  --bg-page:    #0f1419;
  --bg-card:    #1e293b;
  --bg-card-hover: #243044;
  --border-card: #334155;
  --text-primary:   #f1f5f9;
  --text-secondary: #94a3b8;
  --text-muted:     #64748b;
  --accent:      #8b5cf6;
  --accent-soft: rgba(139, 92, 246, 0.15);
  --accent-border: rgba(139, 92, 246, 0.4);
  --pos: #10b981;
  --neg: #f43f5e;
}

/* ── Page background ── */
body:has(.settings-shell) {
  background: var(--bg-page);
  color: var(--text-primary);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

/* ── Shell / page layout ── */
.settings-shell {
  max-width: 1100px;
  margin: 0 auto;
  padding: 28px 24px;
}
.settings-page-header {
  margin-bottom: 20px;
}
.settings-page-header h1 {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 4px;
}
.settings-page-header p {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
}

/* ── Sub-navigation tabs ── */
.settings-tabs {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--border-card);
  margin-bottom: 24px;
}
.settings-tab {
  display: inline-block;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 10px 18px;
  margin-bottom: -1px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  text-decoration: none;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.settings-tab:hover { color: var(--text-primary); }
.settings-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

/* ── Cards ── */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 10px;
  margin-bottom: 16px;
  overflow: hidden;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border-card);
}
.card-title {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
}
.card-footer {
  padding: 14px 20px;
  border-top: 1px solid var(--border-card);
  display: flex;
  align-items: center;
  gap: 12px;
}

/* ── Buttons ── */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: none;
  border-radius: 6px;
  padding: 7px 14px;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  text-decoration: none;
  transition: opacity 0.1s;
}
.btn:hover { opacity: 0.85; }
.btn-accent { background: var(--accent); color: #fff; }
.btn-ghost {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-card);
}
.btn-ghost:hover { color: var(--text-primary); border-color: var(--text-muted); }
.btn-danger {
  background: rgba(244, 63, 94, 0.12);
  color: #fda4af;
  border: 1px solid rgba(244, 63, 94, 0.35);
}
.btn-danger:hover { background: rgba(244, 63, 94, 0.20); }
.btn-sm { padding: 4px 10px; font-size: 12px; }

/* ── Dark table ── */
.dark-table {
  width: 100%;
  border-collapse: collapse;
}
.dark-table th {
  text-align: left;
  padding: 10px 16px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border-card);
  background: transparent;
}
.dark-table td {
  padding: 11px 16px;
  border-bottom: 1px solid rgba(51, 65, 85, 0.5);
  color: var(--text-primary);
  font-size: 13px;
}
.dark-table tbody tr:last-child td { border-bottom: none; }
.dark-table tbody tr:hover { background: var(--bg-card-hover); }
.dark-table td.mono {
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  color: var(--text-secondary);
}
.dark-table td.muted { color: var(--text-muted); font-size: 12px; }

.row-actions { display: flex; gap: 6px; }

/* ── Badges ── */
.badge {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  background: var(--accent-soft);
  color: var(--accent);
  border: 1px solid var(--accent-border);
}
.badge-green {
  background: rgba(16, 185, 129, 0.12);
  color: #6ee7b7;
  border-color: rgba(16, 185, 129, 0.3);
}
.badge-gray {
  background: rgba(100, 116, 139, 0.15);
  color: var(--text-muted);
  border-color: rgba(100, 116, 139, 0.25);
}

/* ── Coverage status dot ── */
.coverage-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}
.dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.dot-green { background: var(--pos); }
.dot-gray  { background: var(--text-muted); }

/* ── Chart-defaults form grid ── */
.form-grid {
  display: grid;
  grid-template-columns: 210px 1fr;
}
.form-row { display: contents; }
.form-label {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 13px 20px;
  border-bottom: 1px solid rgba(51, 65, 85, 0.5);
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}
.form-label small {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 400;
  margin-top: 3px;
}
.form-control {
  display: flex;
  align-items: center;
  padding: 11px 20px;
  border-bottom: 1px solid rgba(51, 65, 85, 0.5);
  gap: 10px;
}
.form-row:last-child .form-label,
.form-row:last-child .form-control { border-bottom: none; }

/* ── Form inputs (scoped to settings-shell to avoid touching global styles) ── */
.settings-shell input[type=text],
.settings-shell input[type=number],
.settings-shell select {
  background: rgba(15, 20, 25, 0.6);
  color: var(--text-primary);
  border: 1px solid var(--border-card);
  border-radius: 6px;
  padding: 7px 10px;
  font-size: 13px;
  font-family: inherit;
  min-width: 220px;
}
.settings-shell input[type=text]:focus,
.settings-shell input[type=number]:focus,
.settings-shell select:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}
.settings-shell input[type=checkbox] {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
  cursor: pointer;
}

/* ── Status message (chart defaults save feedback) ── */
.status { font-size: 12px; color: var(--pos); margin: 0; }

/* ── Inline add-field form (custom fields) ── */
.inline-add-form {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 14px 20px;
}
.inline-add-form input,
.inline-add-form select { min-width: 0; flex: 1; }
.inline-add-form select { flex: 0 0 140px; }

/* ── Custom field rows ── */
.field-row {
  display: flex;
  align-items: center;
  padding: 11px 20px;
  border-bottom: 1px solid rgba(51, 65, 85, 0.5);
  gap: 12px;
}
.field-row:last-child { border-bottom: none; }
.field-name { font-weight: 500; flex: 1; font-size: 13px; }

/* ── Settings index list ── */
.settings-index-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.settings-index-list li {
  padding: 14px 20px;
  border-bottom: 1px solid rgba(51, 65, 85, 0.5);
  font-size: 14px;
  color: var(--text-secondary);
}
.settings-index-list li:last-child { border-bottom: none; }
.settings-index-list a {
  color: var(--accent);
  text-decoration: none;
  font-weight: 500;
}
.settings-index-list a:hover { text-decoration: underline; }

/* ── Instrument dialog ── */
dialog {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 12px;
  color: var(--text-primary);
  padding: 24px;
  max-width: 500px;
  width: 100%;
}
dialog::backdrop { background: rgba(0, 0, 0, 0.65); }
dialog h2 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 20px;
  color: var(--text-primary);
}
dialog label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 14px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
}
dialog input {
  background: rgba(15, 20, 25, 0.6);
  color: var(--text-primary);
  border: 1px solid var(--border-card);
  border-radius: 6px;
  padding: 7px 10px;
  font-size: 13px;
  font-family: inherit;
  text-transform: none;
  letter-spacing: normal;
}
dialog input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}
dialog fieldset {
  border: 1px solid var(--border-card);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 14px;
}
dialog legend {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  padding: 0 6px;
}
.dialog-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--border-card);
}

/* ── Backward-compat shim — JS still emits .muted on some elements ── */
.muted { color: var(--text-muted); }
```

- [ ] **Step 2: Verify the CSS is valid — no parse errors**

Open browser devtools on any settings page and confirm no CSS errors in the console.

- [ ] **Step 3: Commit**

```bash
git add static/css/settings.css
git commit -m "style(settings): rewrite settings.css with dark fintech theme"
```

---

### Task 2: Update `settings_index.html`

**Files:**
- Modify: `templates/settings_index.html`

- [ ] **Step 1: Replace the template**

```html
{% extends "base.html" %}
{% block content %}
<div class="settings-shell">
  <div class="settings-page-header">
    <h1>Settings</h1>
    <p>Configure instruments, chart defaults, and custom trade fields.</p>
  </div>
  <div class="card">
    <ul class="settings-index-list">
      <li><a href="/settings/instruments">Instruments</a> — multipliers, tick sizes, and per-source symbol mapping.</li>
      <li><a href="/settings/chart">Chart defaults</a> — default timeframe, volume toggle, and display timezone.</li>
      <li><a href="/settings/custom-fields">Custom fields</a> — user-defined tags on trades.</li>
    </ul>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Load `http://localhost:8000/settings` and verify**

Expect: dark background, card with three links.

- [ ] **Step 3: Commit**

```bash
git add templates/settings_index.html
git commit -m "style(settings): dark theme for settings index page"
```

---

### Task 3: Update `settings_instruments.html`

**Files:**
- Modify: `templates/settings_instruments.html`

- [ ] **Step 1: Replace the template**

All existing `id=` attributes must be preserved exactly — the JS file depends on them.

```html
{% extends "base.html" %}
{% block content %}
<div class="settings-shell" id="settings-instruments" data-endpoint="/api/config/instruments">

  <div class="settings-page-header">
    <h1>Settings</h1>
  </div>

  <nav class="settings-tabs">
    <a href="/settings/instruments" class="settings-tab active">Instruments</a>
    <a href="/settings/chart" class="settings-tab">Chart Defaults</a>
    <a href="/settings/custom-fields" class="settings-tab">Custom Fields</a>
  </nav>

  <div class="card">
    <div class="card-header">
      <span class="card-title">Instruments</span>
      <button id="new-instrument-btn" type="button" class="btn btn-accent btn-sm">+ Add instrument</button>
    </div>
    <table class="dark-table instruments-table">
      <thead>
        <tr>
          <th>Symbol</th><th>Display name</th><th>Multiplier</th><th>Tick</th>
          <th>yfinance</th><th>stooq</th><th>Session</th><th></th>
        </tr>
      </thead>
      <tbody id="instruments-tbody"></tbody>
    </table>
  </div>

  <div class="card">
    <div class="card-header">
      <span class="card-title">Coverage</span>
    </div>
    <div id="coverage-rows"></div>
  </div>

  <dialog id="instrument-dialog">
    <form id="instrument-form" method="dialog">
      <h2 id="dialog-title">Edit instrument</h2>
      <label>Symbol <input name="symbol" required></label>
      <label>Display name <input name="display_name" required></label>
      <label>Multiplier <input name="multiplier" type="number" step="any" required></label>
      <label>Tick size <input name="tick_size" type="number" step="any" required></label>
      <label>yfinance continuous <input name="yfinance_continuous"></label>
      <label>stooq continuous <input name="stooq_continuous"></label>
      <fieldset>
        <legend>Session</legend>
        <label>Timezone <input name="session_timezone" required></label>
        <label>Open <input name="session_open" placeholder="HH:MM"></label>
        <label>Close <input name="session_close" placeholder="HH:MM"></label>
        <label>Break start <input name="session_break_start" placeholder="HH:MM"></label>
        <label>Break end <input name="session_break_end" placeholder="HH:MM"></label>
      </fieldset>
      <div class="dialog-actions">
        <button type="button" id="dialog-cancel" class="btn btn-ghost">Cancel</button>
        <button type="submit" class="btn btn-accent">Save</button>
      </div>
    </form>
  </dialog>

</div>
<script type="module" src="{{ url_for('static', filename='js/settings_instruments.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: Update the coverage table JS output to use dark classes**

The coverage table is built entirely in `settings_instruments.js` by `renderCoverage()`. That function calls `document.createElement` and doesn't use CSS classes — so the coverage table rows won't pick up `.dark-table` styles unless we either:

a) Add `dark-table` class to the table in JS, or  
b) Target the coverage table via a CSS selector in `settings.css`

Use option (b) — add this rule at the bottom of `static/css/settings.css` so JS doesn't need changing:

```css
/* Coverage table is generated by JS without CSS classes — target it structurally */
#coverage-rows table {
  width: 100%;
  border-collapse: collapse;
}
#coverage-rows th {
  text-align: left;
  padding: 10px 16px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border-card);
}
#coverage-rows td {
  padding: 11px 16px;
  border-bottom: 1px solid rgba(51, 65, 85, 0.5);
  color: var(--text-primary);
  font-size: 13px;
}
#coverage-rows tbody tr:last-child td { border-bottom: none; }
#coverage-rows tbody tr:hover { background: var(--bg-card-hover); }
```

Also, the coverage JS creates plain `<button>` elements. Add this rule too:

```css
#coverage-rows button {
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  font-family: inherit;
  border-radius: 6px;
  cursor: pointer;
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-card);
  margin-right: 4px;
  transition: opacity 0.1s;
}
#coverage-rows button:hover { color: var(--text-primary); }
```

Also, the instruments table `Edit`/`Delete` buttons are created in JS without classes. Add:

```css
#instruments-tbody button {
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  font-family: inherit;
  border-radius: 6px;
  cursor: pointer;
  margin-right: 4px;
  transition: opacity 0.1s;
}
#instruments-tbody button:hover { opacity: 0.85; }
/* "Edit" button — match ghost style (JS sets data-act="edit") */
#instruments-tbody button[data-act="edit"] {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-card);
}
#instruments-tbody button[data-act="edit"]:hover { color: var(--text-primary); }
/* "Delete" button — match danger style (JS sets data-act="del") */
#instruments-tbody button[data-act="del"] {
  background: rgba(244, 63, 94, 0.12);
  color: #fda4af;
  border: 1px solid rgba(244, 63, 94, 0.35);
}
```

Append all three rule blocks to the end of `static/css/settings.css`.

- [ ] **Step 3: Load `http://localhost:8000/settings/instruments` and verify**

Expect:
- Dark background, sub-nav with Instruments tab active (purple underline)
- Instruments card with dark table, styled Edit/Delete buttons
- Coverage card below with dark table and styled buttons
- Clicking "Edit" opens a dark dialog with dark inputs

- [ ] **Step 4: Commit**

```bash
git add templates/settings_instruments.html static/css/settings.css
git commit -m "style(settings): dark theme for instruments settings page"
```

---

### Task 4: Update `settings_chart.html`

**Files:**
- Modify: `templates/settings_chart.html`

- [ ] **Step 1: Replace the template**

All existing `name=` attributes and element `id=` values must be preserved — the JS depends on them.

```html
{% extends "base.html" %}
{% block content %}
<div class="settings-shell" id="settings-chart" data-endpoint="/api/config/chart-defaults">

  <div class="settings-page-header">
    <h1>Settings</h1>
  </div>

  <nav class="settings-tabs">
    <a href="/settings/instruments" class="settings-tab">Instruments</a>
    <a href="/settings/chart" class="settings-tab active">Chart Defaults</a>
    <a href="/settings/custom-fields" class="settings-tab">Custom Fields</a>
  </nav>

  <form id="chart-defaults-form">
    <div class="card">
      <div class="card-header">
        <span class="card-title">Chart Defaults</span>
      </div>
      <div class="form-grid">
        <div class="form-row">
          <div class="form-label">
            Default timeframe
            <small>Used when opening a chart for the first time</small>
          </div>
          <div class="form-control">
            <select name="default_timeframe">
              <option>1m</option><option>5m</option><option>15m</option>
              <option>1h</option><option>4h</option><option>1d</option>
            </select>
          </div>
        </div>
        <div class="form-row">
          <div class="form-label">
            Show volume by default
            <small>Volume histogram below the price chart</small>
          </div>
          <div class="form-control">
            <input type="checkbox" name="volume_visible_default">
          </div>
        </div>
        <div class="form-row">
          <div class="form-label">
            Display timezone
            <small>Blank = your browser's local timezone</small>
          </div>
          <div class="form-control">
            <input type="text" name="display_timezone" placeholder="e.g. America/Chicago or Asia/Tokyo">
          </div>
        </div>
        <div class="form-row">
          <div class="form-label">
            NinjaTrader source timezone
            <small>Timezone the NT machine exports CSVs in</small>
          </div>
          <div class="form-control">
            <input type="text" name="source_timezone" placeholder="e.g. America/Los_Angeles">
          </div>
        </div>
      </div>
      <div class="card-footer">
        <button type="submit" class="btn btn-accent">Save changes</button>
        <p class="status" id="chart-defaults-status"></p>
      </div>
    </div>
  </form>

</div>
<script type="module" src="{{ url_for('static', filename='js/settings_chart.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: Load `http://localhost:8000/settings/chart` and verify**

Expect:
- Dark background, sub-nav with Chart Defaults tab active
- Single card with four form rows (timeframe select, volume checkbox, two timezone inputs)
- Clicking Save shows "Saved." message in green below the button
- Values load from API (the JS `load()` call populates them on page load)

- [ ] **Step 3: Commit**

```bash
git add templates/settings_chart.html
git commit -m "style(settings): dark theme for chart defaults settings page"
```

---

### Task 5: Update `settings_custom_fields.html`

**Files:**
- Modify: `templates/settings_custom_fields.html`

- [ ] **Step 1: Replace the template**

The JS adds rows to `#fields-list`. Preserve that id. The form `#new-field-form` is also referenced by JS.

```html
{% extends "base.html" %}
{% block content %}
<div class="settings-shell" id="settings-custom-fields" data-endpoint="/api/custom-fields">

  <div class="settings-page-header">
    <h1>Settings</h1>
  </div>

  <nav class="settings-tabs">
    <a href="/settings/instruments" class="settings-tab">Instruments</a>
    <a href="/settings/chart" class="settings-tab">Chart Defaults</a>
    <a href="/settings/custom-fields" class="settings-tab active">Custom Fields</a>
  </nav>

  <div class="card">
    <div class="card-header">
      <span class="card-title">Add field</span>
    </div>
    <form id="new-field-form" class="inline-add-form">
      <input type="text" name="name" placeholder="Field name (e.g. Setup)" required>
      <select name="field_type">
        <option value="text">Text</option>
        <option value="number">Number</option>
        <option value="dropdown">Dropdown</option>
        <option value="date">Date</option>
        <option value="boolean">Boolean</option>
      </select>
      <button type="submit" class="btn btn-accent">Add field</button>
    </form>
  </div>

  <div class="card">
    <div class="card-header">
      <span class="card-title">Defined fields</span>
    </div>
    <div id="fields-list"></div>
  </div>

</div>
<script type="module" src="{{ url_for('static', filename='js/settings_custom_fields.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: Check what `settings_custom_fields.js` renders into `#fields-list`**

Open `static/js/settings_custom_fields.js` and note the DOM structure it builds. We need to add CSS in `settings.css` to style whatever it generates. The file currently renders `.field-row` elements with children — add a structural fallback at the end of `settings.css` for any unstyled elements it produces (buttons, inputs inside `.field-row`):

```css
/* Custom fields JS-rendered rows — buttons without classes */
.field-row button {
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  font-family: inherit;
  border-radius: 6px;
  cursor: pointer;
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-card);
  margin-right: 4px;
  transition: opacity 0.1s;
}
.field-row button:hover { color: var(--text-primary); }
.field-row input[type=text],
.field-row textarea {
  background: rgba(15, 20, 25, 0.6);
  color: var(--text-primary);
  border: 1px solid var(--border-card);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 13px;
  font-family: inherit;
  width: 100%;
}
.field-row input[type=text]:focus,
.field-row textarea:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}
.options-editor textarea {
  background: rgba(15, 20, 25, 0.6);
  color: var(--text-primary);
  border: 1px solid var(--border-card);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 13px;
  font-family: inherit;
  width: 100%;
  margin-top: 8px;
}
```

Append these rules to the end of `static/css/settings.css`.

- [ ] **Step 3: Read `static/js/settings_custom_fields.js` to verify there are no other id/class hooks**

Open the file and confirm: the JS only uses `#new-field-form`, `#fields-list`, and the `name` attributes on the form inputs — all of which are still present in the new template.

- [ ] **Step 4: Load `http://localhost:8000/settings/custom-fields` and verify**

Expect:
- Dark background, sub-nav with Custom Fields tab active
- "Add field" card with inline form (name input, type select, Add button)
- "Defined fields" card below showing any existing fields

- [ ] **Step 5: Commit**

```bash
git add templates/settings_custom_fields.html static/css/settings.css
git commit -m "style(settings): dark theme for custom fields settings page"
```

---

### Task 6: Smoke test all pages

- [ ] **Step 1: Check all four settings pages load without white flash or console errors**

```
http://localhost:8000/settings
http://localhost:8000/settings/instruments
http://localhost:8000/settings/chart
http://localhost:8000/settings/custom-fields
```

For each: dark background, correct sub-nav tab active (or no tabs on index), no JS errors in devtools console.

- [ ] **Step 2: Verify Statistics and Reports pages are unchanged**

```
http://localhost:8000/statistics
http://localhost:8000/reports
```

Expect: visually identical to before — the `body:has(.settings-shell)` selector only fires on settings pages.

- [ ] **Step 3: Verify the instrument dialog**

On `/settings/instruments`, click Edit on any row. Expect: dark dialog with dark inputs and a dark backdrop.

- [ ] **Step 4: Verify save flow on chart defaults**

On `/settings/chart`, change the timeframe, click Save. Expect: "Saved." appears in green below the button.

- [ ] **Step 5: Final commit if any loose fixes were made**

```bash
git add -p
git commit -m "style(settings): final polish after smoke test"
```
