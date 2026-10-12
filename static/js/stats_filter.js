// Plan 15 — shared filter bar module. URL query params are the source of truth.
// Both /statistics and /calendar import this and pass onApply.

import { buildQuery, fetchJSON } from "./api.js";
import { renderPresetSelect } from "./date_presets.js";
import { createMultiSelect } from "./MultiSelect.js";
import {
  clearAllDefaults,
  fetchDefaults,
  isUrlEmpty,
  saveDefault,
} from "./filter_defaults.js";

export function parseFilterFromUrl() {
  const url = new URL(window.location.href);
  const accounts = url.searchParams.getAll("account").filter((s) => s !== "");
  const from = url.searchParams.get("from") || null;
  const to = url.searchParams.get("to") || null;
  const side = url.searchParams.get("side") || null;
  const entry_method = url.searchParams.get("entry_method") || null;
  return { accounts, from, to, side, entry_method };
}

export function writeFilterToUrl(filter) {
  const url = new URL(window.location.href);
  url.searchParams.delete("account");
  for (const a of filter.accounts || []) {
    url.searchParams.append("account", a);
  }
  for (const k of ["from", "to", "side", "entry_method"]) {
    if (filter[k]) url.searchParams.set(k, filter[k]);
    else url.searchParams.delete(k);
  }
  window.history.pushState({}, "", url.toString());
}

// Serialize a stats filter (plus optional extra params) via the shared
// buildQuery helper. extras win on key collisions.
export function filterToQueryString(filter, extras = {}) {
  return buildQuery({
    account: filter.accounts || [],
    from: filter.from,
    to: filter.to,
    side: filter.side,
    entry_method: filter.entry_method,
    ...extras,
  });
}

export function isAnyFilterActive(filter, totalAccountCount) {
  const n = (filter.accounts || []).length;
  const accountsActive =
    n > 0 && (totalAccountCount == null || n < totalAccountCount);
  return Boolean(
    accountsActive || filter.from || filter.to || filter.side || filter.entry_method,
  );
}

export async function fetchAccountOptions() {
  try {
    const body = await fetchJSON("/api/positions/filters");
    return body.accounts || [];
  } catch {
    return [];
  }
}

const STATS_URL_KEYS = ["account", "side", "entry_method", "from", "to"];

// Stats-filter key → /positions query param. The single source of truth for
// the stats↔positions drilldown round-trip: statistics.js positionsUrl writes
// with it, positions_list.js renderBackToStats reads with it. `account` is
// handled separately (repeated param, same name on both pages).
export const STATS_TO_POSITIONS_PARAMS = {
  side: "side",
  entry_method: "entry_method",
  from: "session_date_from",
  to: "session_date_to",
};

export function renderFilterBar(container, filter, onApply) {
  container.classList.add("filter-bar");
  container.innerHTML = `
    <label>Account
      <div id="filter-account-host"></div>
    </label>
    <label>Side
      <select id="filter-side">
        <option value="">All</option>
        <option value="Long">Long</option>
        <option value="Short">Short</option>
      </select>
    </label>
    <label>Entry
      <select id="filter-entry-method">
        <option value="">All</option>
        <option value="market_next_open">Market on next open</option>
        <option value="limit_next_open">Limit on next open</option>
        <option value="manual">Manual</option>
        <option value="unknown">Unknown</option>
      </select>
    </label>
    <label>Preset
      <select id="filter-date-preset"></select>
    </label>
    <label>From
      <input type="date" id="filter-from">
    </label>
    <label>To
      <input type="date" id="filter-to">
    </label>
    <button id="filter-clear" type="button">Clear</button>
    <button id="filter-save-default" type="button">Save as default</button>
    <button id="filter-clear-default" type="button" hidden>Clear default</button>
  `;

  const accountHost = container.querySelector("#filter-account-host");
  const sideSelect = container.querySelector("#filter-side");
  const entrySelect = container.querySelector("#filter-entry-method");
  const presetSelect = container.querySelector("#filter-date-preset");
  const fromInput = container.querySelector("#filter-from");
  const toInput = container.querySelector("#filter-to");
  const clearBtn = container.querySelector("#filter-clear");
  const saveDefaultBtn = container.querySelector("#filter-save-default");
  const clearDefaultBtn = container.querySelector("#filter-clear-default");

  if (filter.from) fromInput.value = filter.from;
  if (filter.to) toInput.value = filter.to;
  if (filter.side) sideSelect.value = filter.side;
  if (filter.entry_method) entrySelect.value = filter.entry_method;

  let currentAccounts = [...(filter.accounts || [])];
  let totalAccountCount = null;
  // Suppresses auto-apply during programmatic mutations (default-load, clear,
  // popstate). Without this the onChange callback of the widget would fire a
  // duplicate load while we're mid-setup.
  let suppressAutoApply = false;

  const doApply = () => {
    if (suppressAutoApply) return;
    const next = {
      accounts: [...currentAccounts],
      side: sideSelect.value || null,
      entry_method: entrySelect.value || null,
      from: fromInput.value || null,
      to: toInput.value || null,
    };
    writeFilterToUrl(next);
    onApply(next);
  };

  const multi = createMultiSelect(accountHost, {
    options: [],
    selected: currentAccounts,
    label: "Account",
    allLabel: "All accounts",
    onChange: (sel) => { currentAccounts = sel; doApply(); },
  });

  let hasDefault = false;
  const setClearDefaultVisible = (visible) => {
    clearDefaultBtn.hidden = !visible;
  };

  Promise.all([fetchAccountOptions(), fetchDefaults()]).then(([accounts, defaults]) => {
    totalAccountCount = accounts.length;
    suppressAutoApply = true;
    multi.setOptions(accounts);
    suppressAutoApply = false;

    const savedAccounts = Array.isArray(defaults.accounts) ? defaults.accounts : [];
    const savedStats = defaults.stats;
    hasDefault = savedAccounts.length > 0 || savedStats != null;
    setClearDefaultVisible(hasDefault);

    const urlIsEmpty = isUrlEmpty(window.location.href, STATS_URL_KEYS);

    if (hasDefault && urlIsEmpty) {
      suppressAutoApply = true;
      multi.setSelected(savedAccounts);
      suppressAutoApply = false;
      currentAccounts = multi.getSelected();
      if (savedStats && savedStats.side) sideSelect.value = savedStats.side;
      doApply();
    } else {
      suppressAutoApply = true;
      multi.setSelected(currentAccounts);
      suppressAutoApply = false;
      currentAccounts = multi.getSelected();
    }
  });

  renderPresetSelect(presetSelect, "", (_preset, range) => {
    if (!range) return;
    fromInput.value = range.fromISO;
    toInput.value = range.toISO;
    doApply();
  });

  const resetPreset = () => { presetSelect.value = ""; };
  fromInput.addEventListener("input", resetPreset);
  toInput.addEventListener("input", resetPreset);

  sideSelect.addEventListener("change", doApply);
  entrySelect.addEventListener("change", doApply);
  fromInput.addEventListener("change", doApply);
  toInput.addEventListener("change", doApply);

  const resetFilterBar = () => {
    suppressAutoApply = true;
    multi.setSelected([]);
    suppressAutoApply = false;
    currentAccounts = [];
    sideSelect.value = "";
    entrySelect.value = "";
    fromInput.value = "";
    toInput.value = "";
    presetSelect.value = "";
    const cleared = { accounts: [], side: null, entry_method: null, from: null, to: null };
    writeFilterToUrl(cleared);
    onApply(cleared);
  };

  clearBtn.addEventListener("click", resetFilterBar);

  saveDefaultBtn.addEventListener("click", async () => {
    const [okA, okS] = await Promise.all([
      saveDefault("accounts", { accounts: [...currentAccounts] }),
      saveDefault("stats", { side: sideSelect.value || "" }),
    ]);
    if (okA && okS) {
      hasDefault = true;
      setClearDefaultVisible(true);
    }
  });

  clearDefaultBtn.addEventListener("click", async () => {
    const ok = await clearAllDefaults();
    if (ok) {
      hasDefault = false;
      setClearDefaultVisible(false);
      resetFilterBar();
    }
  });

  window.addEventListener("popstate", () => {
    const reread = parseFilterFromUrl();
    suppressAutoApply = true;
    multi.setSelected(reread.accounts || []);
    suppressAutoApply = false;
    currentAccounts = multi.getSelected();
    sideSelect.value = reread.side || "";
    entrySelect.value = reread.entry_method || "";
    fromInput.value = reread.from || "";
    toInput.value = reread.to || "";
    presetSelect.value = "";
    onApply(reread);
  });
}
