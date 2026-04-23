// Plan 15 — shared filter bar module. URL query params are the source of truth.
// Both /statistics and /calendar import this and pass onApply.

import { renderPresetSelect } from "./date_presets.js";
import { createMultiSelect } from "./MultiSelect.js";

export function parseFilterFromUrl() {
  const url = new URL(window.location.href);
  const accounts = url.searchParams.getAll("account").filter((s) => s !== "");
  const from = url.searchParams.get("from") || null;
  const to = url.searchParams.get("to") || null;
  const side = url.searchParams.get("side") || null;
  return { accounts, from, to, side };
}

export function writeFilterToUrl(filter) {
  const url = new URL(window.location.href);
  url.searchParams.delete("account");
  for (const a of filter.accounts || []) {
    url.searchParams.append("account", a);
  }
  for (const k of ["from", "to", "side"]) {
    if (filter[k]) url.searchParams.set(k, filter[k]);
    else url.searchParams.delete(k);
  }
  window.history.pushState({}, "", url.toString());
}

export function filterToQueryString(filter) {
  const parts = [];
  for (const a of filter.accounts || []) {
    parts.push(`account=${encodeURIComponent(a)}`);
  }
  if (filter.from) parts.push(`from=${encodeURIComponent(filter.from)}`);
  if (filter.to) parts.push(`to=${encodeURIComponent(filter.to)}`);
  if (filter.side) parts.push(`side=${encodeURIComponent(filter.side)}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

export function isAnyFilterActive(filter, totalAccountCount) {
  const n = (filter.accounts || []).length;
  const accountsActive =
    n > 0 && (totalAccountCount == null || n < totalAccountCount);
  return Boolean(accountsActive || filter.from || filter.to || filter.side);
}

export async function fetchAccountOptions() {
  const resp = await fetch("/api/positions/filters");
  if (!resp.ok) return [];
  const body = await resp.json();
  return body.accounts || [];
}

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
    <label>Preset
      <select id="filter-date-preset"></select>
    </label>
    <label>From
      <input type="date" id="filter-from">
    </label>
    <label>To
      <input type="date" id="filter-to">
    </label>
    <button id="filter-apply">Apply</button>
    <button id="filter-clear">Clear</button>
  `;

  const accountHost = container.querySelector("#filter-account-host");
  const sideSelect = container.querySelector("#filter-side");
  const presetSelect = container.querySelector("#filter-date-preset");
  const fromInput = container.querySelector("#filter-from");
  const toInput = container.querySelector("#filter-to");
  const applyBtn = container.querySelector("#filter-apply");
  const clearBtn = container.querySelector("#filter-clear");

  if (filter.from) fromInput.value = filter.from;
  if (filter.to) toInput.value = filter.to;
  if (filter.side) sideSelect.value = filter.side;

  // Widget created empty; populated once /api/positions/filters resolves.
  let currentAccounts = [...(filter.accounts || [])];
  let totalAccountCount = null;
  const multi = createMultiSelect(accountHost, {
    options: [],
    selected: currentAccounts,
    label: "Account",
    allLabel: "All accounts",
    onChange: (sel) => { currentAccounts = sel; updateApplyHighlight(); },
  });

  const updateApplyHighlight = () => {
    const snapshot = {
      accounts: currentAccounts,
      side: sideSelect.value || null,
      from: fromInput.value || null,
      to: toInput.value || null,
    };
    if (isAnyFilterActive(snapshot, totalAccountCount)) applyBtn.classList.add("active");
    else applyBtn.classList.remove("active");
  };

  fetchAccountOptions().then((accounts) => {
    totalAccountCount = accounts.length;
    multi.setOptions(accounts);
    multi.setSelected(currentAccounts);
    currentAccounts = multi.getSelected();
    updateApplyHighlight();
  });

  updateApplyHighlight();

  const doApply = () => {
    const next = {
      accounts: [...currentAccounts],
      side: sideSelect.value || null,
      from: fromInput.value || null,
      to: toInput.value || null,
    };
    writeFilterToUrl(next);
    updateApplyHighlight();
    onApply(next);
  };

  renderPresetSelect(presetSelect, "", (_preset, range) => {
    if (!range) return;
    fromInput.value = range.fromISO;
    toInput.value = range.toISO;
    doApply();
  });

  const resetPreset = () => { presetSelect.value = ""; };
  fromInput.addEventListener("input", resetPreset);
  toInput.addEventListener("input", resetPreset);

  applyBtn.addEventListener("click", doApply);

  clearBtn.addEventListener("click", () => {
    multi.setSelected([]);
    currentAccounts = [];
    sideSelect.value = "";
    fromInput.value = "";
    toInput.value = "";
    presetSelect.value = "";
    const cleared = { accounts: [], side: null, from: null, to: null };
    writeFilterToUrl(cleared);
    updateApplyHighlight();
    onApply(cleared);
  });

  window.addEventListener("popstate", () => {
    const reread = parseFilterFromUrl();
    multi.setSelected(reread.accounts || []);
    currentAccounts = multi.getSelected();
    sideSelect.value = reread.side || "";
    fromInput.value = reread.from || "";
    toInput.value = reread.to || "";
    presetSelect.value = "";
    updateApplyHighlight();
    onApply(reread);
  });
}
