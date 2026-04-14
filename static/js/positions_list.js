import { buildQuery, fetchJSON, formatDollars, formatTime, setText } from "./api.js";

const form = document.getElementById("filter-form");
const listRoot = document.getElementById("list-root");
const paginationRoot = document.getElementById("pagination-root");

let currentPage = 1;
const PAGE_SIZE = 50;

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
  return {
    account: data.get("account") || "",
    instrument: data.get("instrument") || "",
    side: data.get("side") || "",
    outcome: data.get("outcome") || "",
  };
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

function renderRows(positions) {
  if (positions.length === 0) {
    listRoot.innerHTML = "<p>No positions match the current filters.</p>";
    return;
  }
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  thead.innerHTML = `
    <tr>
      <th>Entry</th>
      <th>Account</th>
      <th>Instrument</th>
      <th>Side</th>
      <th>Qty</th>
      <th>Entry price</th>
      <th>Exit price</th>
      <th>$ P&L</th>
      <th>Duration</th>
    </tr>`;
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  for (const p of positions) {
    const tr = document.createElement("tr");
    tr.addEventListener("click", () => {
      const url = `/positions/${encodeURIComponent(p.account)}/${encodeURIComponent(p.instrument)}/${encodeURIComponent(p.entry_execution_id)}`;
      window.location.href = url;
    });
    const td = (text, cls) => {
      const c = document.createElement("td");
      setText(c, text);
      if (cls) c.className = cls;
      return c;
    };
    tr.appendChild(td(formatTime(p.entry_time)));
    tr.appendChild(td(p.account));
    tr.appendChild(td(p.instrument));
    tr.appendChild(td(p.side));
    tr.appendChild(td(p.quantity));
    tr.appendChild(td(p.entry_price.toFixed(2)));
    tr.appendChild(td(p.exit_price !== null ? p.exit_price.toFixed(2) : "—"));
    const dollars = formatDollars(p.dollars_pnl);
    tr.appendChild(td(dollars.text, dollars.cls));
    tr.appendChild(td(p.duration_minutes !== null ? p.duration_minutes.toFixed(1) + " m" : "—"));
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
  for (const name of ["account", "instrument", "side", "outcome"]) {
    const value = params.get(name);
    if (value !== null) {
      const el = form.querySelector(`[name="${name}"]`);
      if (el) el.value = value;
    }
  }
  const page = parseInt(params.get("page") || "1", 10);
  currentPage = isNaN(page) ? 1 : Math.max(1, page);
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  currentPage = 1;
  load();
});

(async () => {
  await populateFilterOptions();
  restoreFiltersFromUrl();
  await load();
})();
