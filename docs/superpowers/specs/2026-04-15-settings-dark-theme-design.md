# Settings Pages Dark Theme — Design Spec

**Date:** 2026-04-15

## Goal

Restyle the three settings pages (Instruments, Chart Defaults, Custom Fields) to match the dark fintech theme already used on the Statistics and Reports pages. Also add a settings sub-navigation so users can jump between the three sections without returning to the settings index.

## What's Changing

- **Visual theme only** — no route changes, no JS logic changes, no API changes.
- **Separate URLs kept** — `/settings/instruments`, `/settings/chart`, `/settings/custom-fields` remain independent pages. The sub-nav uses plain `<a>` links.
- The settings index page (`/settings`) gets the same dark treatment.

## Design Tokens (re-use from `stats.css`)

Same CSS variables already defined in `stats.css`:
- `--bg-page: #0f1419`, `--bg-card: #1e293b`, `--border-card: #334155`
- `--text-primary`, `--text-secondary`, `--text-muted`
- `--accent: #8b5cf6`, `--accent-soft`
- `--pos`, `--neg` for danger/success states

## Layout

### All three pages share:
- `.settings-shell` — max-width 1100px, centered, padding 28px 24px
- `.settings-tabs` — `<nav>` of `<a>` links; active page gets purple underline
- Dark `body` background via `body:has(.settings-shell)` selector (same pattern as stats page)

### Cards
Each logical section sits in a `.card`:
- `background: var(--bg-card)`, `border: 1px solid var(--border-card)`, `border-radius: 10px`
- `.card-header` — flex row with `.card-title` (uppercase label) + optional action button
- `.card-body` — zero-padding container; table or form rows sit flush

### Instruments page (`/settings/instruments`)
- Two cards: **Instruments** (table + Add button) and **Coverage** (table)
- Table: `.dark-table` — dark header row, monospace number cells, hover highlight
- Buttons: `.btn-ghost` for Edit, `.btn-danger` for Delete/Retire, `.btn-accent` for Add instrument

### Chart Defaults page (`/settings/chart`)
- One card with a two-column form grid (200px label column, 1fr control column)
- Each row: label text + small description hint on left; input/select/checkbox on right
- `.card-footer` holds the Save button + status message

### Custom Fields page (`/settings/custom-fields`)
- **Add field** card with inline form row (name input + type select + Add button)
- **Defined fields** card with field rows: name | type badge | Edit options + Delete

### Settings index page (`/settings`)
- Single card listing the three links with descriptions

## Files to Change

| File | Change |
|------|--------|
| `static/css/settings.css` | Full rewrite with dark-theme styles |
| `templates/base.html` | Add `body:has(.settings-shell)` selector to apply dark bg (avoids touching stats.css) OR put it in settings.css which is already loaded globally |
| `templates/settings_instruments.html` | Add sub-nav, wrap in `.settings-shell`, add card markup |
| `templates/settings_chart.html` | Add sub-nav, wrap in `.settings-shell`, restructure form into card |
| `templates/settings_custom_fields.html` | Add sub-nav, wrap in `.settings-shell`, add cards |
| `templates/settings_index.html` | Wrap in `.settings-shell`, style as card |

## What Is NOT Changing

- All JS files (`settings_instruments.js`, `settings_chart.js`, `settings_custom_fields.js`) — unchanged. IDs and class hooks they rely on are preserved.
- The `<dialog>` element in instruments — gets dark styling via CSS only, no markup change.
- Routes, API endpoints, backend logic — untouched.

## Acceptance Criteria

1. All settings pages have `#0f1419` background and card-based layout matching the mockup.
2. Sub-nav shows on all three sub-pages; current page tab has purple underline.
3. Settings index page is styled consistently (no white flash).
4. The instrument dialog (Edit/Add) is dark-themed.
5. Statistics and Reports pages are visually unchanged.
6. No JS errors in browser console after changes.
