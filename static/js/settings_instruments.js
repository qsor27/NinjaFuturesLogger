const endpoint = "/api/config/instruments";
const tbody = document.getElementById("instruments-tbody");
const dialog = document.getElementById("instrument-dialog");
const form = document.getElementById("instrument-form");
const titleEl = document.getElementById("dialog-title");
const newBtn = document.getElementById("new-instrument-btn");
const cancelBtn = document.getElementById("dialog-cancel");

let editingSymbol = null;

async function refresh() {
  const res = await fetch(endpoint);
  const body = await res.json();
  tbody.replaceChildren();
  for (const [symbol, cfg] of Object.entries(body.instruments).sort()) {
    const tr = document.createElement("tr");
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
    editBtn.textContent = "Edit";
    delBtn.textContent = "Delete";
    editBtn.addEventListener("click", () => openDialog(symbol, cfg));
    delBtn.addEventListener("click", () => deleteInstrument(symbol));
    tbody.appendChild(tr);
  }
}

function openDialog(symbol, cfg) {
  editingSymbol = symbol;
  titleEl.textContent = symbol ? `Edit ${symbol}` : "Add instrument";
  const elements = form.elements;
  elements.symbol.value = symbol || "";
  elements.symbol.disabled = Boolean(symbol);
  elements.display_name.value = cfg?.display_name || "";
  elements.multiplier.value = cfg?.multiplier ?? "";
  elements.tick_size.value = cfg?.tick_size ?? "";
  elements.yfinance_continuous.value = cfg?.sources?.yfinance?.continuous || "";
  elements.stooq_continuous.value = cfg?.sources?.stooq?.continuous || "";
  elements.session_timezone.value = cfg?.session?.timezone || "America/Chicago";
  elements.session_open.value = cfg?.session?.open || "17:00";
  elements.session_close.value = cfg?.session?.close || "16:00";
  elements.session_break_start.value = cfg?.session?.daily_break_start || "16:00";
  elements.session_break_end.value = cfg?.session?.daily_break_end || "17:00";
  dialog.showModal();
}

async function saveDialog(event) {
  event.preventDefault();
  const f = form.elements;
  const symbol = f.symbol.value.trim();
  const payload = {
    display_name: f.display_name.value,
    multiplier: parseFloat(f.multiplier.value),
    tick_size: parseFloat(f.tick_size.value),
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
  const res = await fetch(`${endpoint}/${symbol}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    alert(`Save failed: ${res.status}`);
    return;
  }
  dialog.close();
  await refresh();
}

async function deleteInstrument(symbol) {
  if (!confirm(`Delete ${symbol}?`)) return;
  const res = await fetch(`${endpoint}/${symbol}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    alert(`Delete failed: ${res.status}`);
    return;
  }
  await refresh();
}

newBtn.addEventListener("click", () => openDialog(null, null));
cancelBtn.addEventListener("click", () => dialog.close());
form.addEventListener("submit", saveDialog);

refresh();
