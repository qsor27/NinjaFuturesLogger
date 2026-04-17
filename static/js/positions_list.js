import { buildQuery, fetchJSON, formatDollars, formatTime, setText } from "./api.js";
import { renderPresetSelect } from "./date_presets.js";

const form = document.getElementById("filter-form");
const listRoot = document.getElementById("list-root");
const paginationRoot = document.getElementById("pagination-root");

let currentPage = 1;
const PAGE_SIZE = 50;

const backToStats = document.getElementById("back-to-stats");

const FILTER_NAMES = [
  "account", "instrument", "side", "outcome",
  "session_date_from", "session_date_to",
  "day_of_week", "hour_of_day", "hour_tz", "trades_per_day",
];

// Column registry. Each entry builds the header label and the cell node.
const COLUMNS = {
  entry: {
    label: "Entry",
    cell: (p) => {
      const td = document.createElement("td");
      setText(td, formatTime(p.entry_time));
      return td;
    },
  },
  account: {
    label: "Account",
    cell: (p) => {
      const td = document.createElement("td");
      setText(td, p.account);
      return td;
    },
  },
  instrument: {
    label: "Instrument",
    cell: (p) => {
      const td = document.createElement("td");
      setText(td, p.instrument);
      return td;
    },
  },
  side: {
    label: "Side",
    cell: (p) => {
      const td = document.createElement("td");
      setText(td, p.side);
      return td;
    },
  },
  quantity: {
    label: "Qty",
    cell: (p) => {
      const td = document.createElement("td");
      setText(td, p.quantity);
      return td;
    },
  },
  entry_price: {
    label: "Entry price",
    cell: (p) => {
      const td = document.createElement("td");
      setText(td, p.entry_price.toFixed(2));
      return td;
    },
  },
  exit_price: {
    label: "Exit price",
    cell: (p) => {
      const td = document.createElement("td");
      setText(td, p.exit_price !== null ? p.exit_price.toFixed(2) : "—");
      return td;
    },
  },
  points_pnl: {
    label: "Pts P&L",
    cell: (p) => {
      const td = document.createElement("td");
      if (p.points_pnl === null || p.points_pnl === undefined) {
        setText(td, "—");
      } else {
        setText(td, p.points_pnl.toFixed(2));
        td.className = p.points_pnl > 0 ? "pnl-pos" : p.points_pnl < 0 ? "pnl-neg" : "";
      }
      return td;
    },
  },
  dollars_pnl: {
    label: "$ P&L",
    cell: (p) => {
      const td = document.createElement("td");
      const d = formatDollars(p.dollars_pnl);
      setText(td, d.text);
      if (d.cls) td.className = d.cls;
      return td;
    },
  },
  duration: {
    label: "Duration",
    cell: (p) => {
      const td = document.createElement("td");
      setText(td, p.duration_minutes !== null ? p.duration_minutes.toFixed(1) + " m" : "—");
      return td;
    },
  },
};

const DEFAULT_ORDER = [
  "entry",
  "account",
  "instrument",
  "side",
  "quantity",
  "entry_price",
  "exit_price",
  "points_pnl",
  "dollars_pnl",
  "duration",
];
const ORDER_KEY = "positions:columnOrder:v2";

function loadColumnOrder() {
  try {
    const raw = localStorage.getItem(ORDER_KEY);
    if (!raw) return [...DEFAULT_ORDER];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [...DEFAULT_ORDER];
    const kept = parsed.filter((k) => typeof k === "string" && k in COLUMNS);
    for (const k of DEFAULT_ORDER) {
      if (!kept.includes(k)) kept.push(k);
    }
    return kept;
  } catch {
    return [...DEFAULT_ORDER];
  }
}

function saveColumnOrder(order) {
  try {
    localStorage.setItem(ORDER_KEY, JSON.stringify(order));
  } catch {
    // Ignore quota / private-mode errors; ordering just won't persist.
  }
}

let columnOrder = loadColumnOrder();
let lastPositions = [];
let dragSourceKey = null;

async function populateFilterOptions() {
  const opts = await fetchJSON("/api/positions/filters");
  const accountSelect = form.querySelector('select[name="account"]');
  const instrumentSelect = form.querySelector('select[name="instrument"]');
  for (const a of opts.accounts) {
    const o = document.createElement("option");
    o.value = a;
    o.textContent = a;
    accountSelect.appendChild(o);
  }
  for (const i of opts.instruments) {
    const o = document.createElement("option");
    o.value = i;
    o.textContent = i;
    instrumentSelect.appendChild(o);
  }
}

function readFilters() {
  const data = new FormData(form);
  const out = {};
  for (const name of FILTER_NAMES) {
    out[name] = data.get(name) || "";
  }
  if (out.hour_of_day && !out.hour_tz) {
    try {
      out.hour_tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    } catch {
      out.hour_tz = "";
    }
    const hidden = form.querySelector('input[name="hour_tz"]');
    if (hidden) hidden.value = out.hour_tz;
  }
  return out;
}

function filtersToUrl(filters, page) {
  const params = { ...filters, page, page_size: PAGE_SIZE };
  return "/api/positions" + buildQuery(params);
}

function pushState(filters, page) {
  const url = new URL(window.location.href);
  for (const [k, v] of Object.entries({ ...filters, page })) {
    if (v === "" || v === null || v === undefined) {
      url.searchParams.delete(k);
    } else {
      url.searchParams.set(k, String(v));
    }
  }
  history.replaceState(null, "", url);
}

function onDragStart(e) {
  dragSourceKey = e.currentTarget.dataset.colKey;
  e.dataTransfer.effectAllowed = "move";
  try {
    e.dataTransfer.setData("text/plain", dragSourceKey);
  } catch {
    // Safari/Firefox sometimes reject this silently; the drag still works.
  }
  e.currentTarget.classList.add("col-dragging");
}

function onDragOver(e) {
  if (!dragSourceKey) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "move";
  e.currentTarget.classList.add("col-drop-target");
}

function onDragLeave(e) {
  e.currentTarget.classList.remove("col-drop-target");
}

function onDrop(e) {
  e.preventDefault();
  e.currentTarget.classList.remove("col-drop-target");
  const targetKey = e.currentTarget.dataset.colKey;
  if (!dragSourceKey || dragSourceKey === targetKey) return;
  const fromIdx = columnOrder.indexOf(dragSourceKey);
  const toIdx = columnOrder.indexOf(targetKey);
  if (fromIdx < 0 || toIdx < 0) return;
  columnOrder.splice(fromIdx, 1);
  columnOrder.splice(toIdx, 0, dragSourceKey);
  saveColumnOrder(columnOrder);
  renderRows(lastPositions);
}

function onDragEnd(e) {
  e.currentTarget.classList.remove("col-dragging");
  document
    .querySelectorAll(".col-drop-target")
    .forEach((el) => el.classList.remove("col-drop-target"));
  dragSourceKey = null;
}

function renderRows(positions) {
  lastPositions = positions;
  if (positions.length === 0) {
    listRoot.innerHTML = "<p>No positions match the current filters.</p>";
    return;
  }
  const table = document.createElement("table");
  table.className = "positions-table";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const key of columnOrder) {
    const th = document.createElement("th");
    setText(th, COLUMNS[key].label);
    th.draggable = true;
    th.dataset.colKey = key;
    th.title = "Drag to reorder";
    th.addEventListener("dragstart", onDragStart);
    th.addEventListener("dragover", onDragOver);
    th.addEventListener("dragleave", onDragLeave);
    th.addEventListener("drop", onDrop);
    th.addEventListener("dragend", onDragEnd);
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const p of positions) {
    const tr = document.createElement("tr");
    tr.addEventListener("click", () => {
      const url = `/positions/${encodeURIComponent(p.account)}/${encodeURIComponent(p.instrument)}/${encodeURIComponent(p.entry_execution_id)}`;
      window.location.href = url;
    });
    for (const key of columnOrder) {
      tr.appendChild(COLUMNS[key].cell(p));
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  listRoot.innerHTML = "";
  listRoot.appendChild(table);
}

function renderPagination(pageMeta) {
  paginationRoot.innerHTML = "";
  const info = document.createElement("span");
  setText(info, `Page ${pageMeta.page} of ${pageMeta.total_pages} (${pageMeta.total} total)`);
  paginationRoot.appendChild(info);

  const prev = document.createElement("button");
  setText(prev, "Prev");
  prev.disabled = !pageMeta.has_prev;
  prev.addEventListener("click", () => {
    currentPage = Math.max(1, currentPage - 1);
    load();
  });
  paginationRoot.appendChild(prev);

  const next = document.createElement("button");
  setText(next, "Next");
  next.disabled = !pageMeta.has_next;
  next.addEventListener("click", () => {
    currentPage += 1;
    load();
  });
  paginationRoot.appendChild(next);
}

async function load() {
  const filters = readFilters();
  pushState(filters, currentPage);
  const data = await fetchJSON(filtersToUrl(filters, currentPage));
  renderRows(data.positions);
  renderPagination(data.page);
}

function restoreFiltersFromUrl() {
  const params = new URL(window.location.href).searchParams;
  for (const name of FILTER_NAMES) {
    const value = params.get(name);
    if (value !== null) {
      const el = form.querySelector(`[name="${name}"]`);
      if (el) el.value = value;
    }
  }
  const page = parseInt(params.get("page") || "1", 10);
  currentPage = isNaN(page) ? 1 : Math.max(1, page);
}

function renderBackToStats() {
  const params = new URL(window.location.href).searchParams;
  const hasDrilldown =
    params.has("day_of_week") ||
    params.has("hour_of_day") ||
    params.has("trades_per_day");
  if (!hasDrilldown) {
    backToStats.hidden = true;
    backToStats.textContent = "";
    return;
  }
  const statsParams = new URLSearchParams();
  const account = params.get("account");
  const side = params.get("side");
  const from = params.get("session_date_from");
  const to = params.get("session_date_to");
  if (account) statsParams.set("account", account);
  if (side) statsParams.set("side", side);
  if (from) statsParams.set("from", from);
  if (to) statsParams.set("to", to);
  const href = `/statistics${statsParams.toString() ? "?" + statsParams.toString() : ""}`;
  backToStats.hidden = false;
  backToStats.innerHTML = "";
  const a = document.createElement("a");
  a.href = href;
  a.textContent = "\u2190 Back to statistics";
  backToStats.appendChild(a);
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  currentPage = 1;
  load();
});

function wirePresetDropdown() {
  const presetSelect = form.querySelector("#filter-date-preset");
  if (!presetSelect) return;
  const fromInput = form.querySelector('input[name="session_date_from"]');
  const toInput = form.querySelector('input[name="session_date_to"]');

  renderPresetSelect(presetSelect, "", (_preset, range) => {
    if (!range) return;
    fromInput.value = range.fromISO;
    toInput.value = range.toISO;
    currentPage = 1;
    load();
  });

  const resetPreset = () => {
    presetSelect.value = "";
  };
  fromInput.addEventListener("input", resetPreset);
  toInput.addEventListener("input", resetPreset);
}

(async () => {
  await populateFilterOptions();
  restoreFiltersFromUrl();
  renderBackToStats();
  wirePresetDropdown();
  await load();
})();
