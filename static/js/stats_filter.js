// Plan 15 — shared filter bar module. URL query params are the source of truth.
// Both /statistics and /reports import this and pass onApply.

export function parseFilterFromUrl() {
  const url = new URL(window.location.href);
  const account = url.searchParams.get("account") || null;
  const from = url.searchParams.get("from") || null;
  const to = url.searchParams.get("to") || null;
  const side = url.searchParams.get("side") || null;
  return { account, from, to, side };
}

export function writeFilterToUrl(filter) {
  const url = new URL(window.location.href);
  ["account", "from", "to", "side"].forEach((k) => {
    if (filter[k]) {
      url.searchParams.set(k, filter[k]);
    } else {
      url.searchParams.delete(k);
    }
  });
  window.history.pushState({}, "", url.toString());
}

export function filterToQueryString(filter) {
  const parts = [];
  if (filter.account) parts.push(`account=${encodeURIComponent(filter.account)}`);
  if (filter.from) parts.push(`from=${encodeURIComponent(filter.from)}`);
  if (filter.to) parts.push(`to=${encodeURIComponent(filter.to)}`);
  if (filter.side) parts.push(`side=${encodeURIComponent(filter.side)}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

export function isAnyFilterActive(filter) {
  return Boolean(filter.account || filter.from || filter.to || filter.side);
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
      <select id="filter-account">
        <option value="">All accounts</option>
      </select>
    </label>
    <label>Side
      <select id="filter-side">
        <option value="">All</option>
        <option value="Long">Long</option>
        <option value="Short">Short</option>
      </select>
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

  const accountSelect = container.querySelector("#filter-account");
  const sideSelect = container.querySelector("#filter-side");
  const fromInput = container.querySelector("#filter-from");
  const toInput = container.querySelector("#filter-to");
  const applyBtn = container.querySelector("#filter-apply");
  const clearBtn = container.querySelector("#filter-clear");

  if (filter.from) fromInput.value = filter.from;
  if (filter.to) toInput.value = filter.to;
  if (filter.side) sideSelect.value = filter.side;

  fetchAccountOptions().then((accounts) => {
    accounts.forEach((a) => {
      const opt = document.createElement("option");
      opt.value = a;
      opt.textContent = a;
      if (filter.account === a) opt.selected = true;
      accountSelect.appendChild(opt);
    });
  });

  if (isAnyFilterActive(filter)) applyBtn.classList.add("active");

  applyBtn.addEventListener("click", () => {
    const next = {
      account: accountSelect.value || null,
      side: sideSelect.value || null,
      from: fromInput.value || null,
      to: toInput.value || null,
    };
    writeFilterToUrl(next);
    if (isAnyFilterActive(next)) {
      applyBtn.classList.add("active");
    } else {
      applyBtn.classList.remove("active");
    }
    onApply(next);
  });

  clearBtn.addEventListener("click", () => {
    accountSelect.value = "";
    sideSelect.value = "";
    fromInput.value = "";
    toInput.value = "";
    const cleared = { account: null, side: null, from: null, to: null };
    writeFilterToUrl(cleared);
    applyBtn.classList.remove("active");
    onApply(cleared);
  });

  window.addEventListener("popstate", () => {
    const reread = parseFilterFromUrl();
    accountSelect.value = reread.account || "";
    sideSelect.value = reread.side || "";
    fromInput.value = reread.from || "";
    toInput.value = reread.to || "";
    onApply(reread);
  });
}
