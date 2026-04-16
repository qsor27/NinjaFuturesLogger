import {
  fetchJSON,
  formatDollars,
  formatTime,
  patchJSON,
  postJSON,
  setText,
} from "./api.js";
import { PriceChart } from "./PriceChart.js";
import { mountCustomFields } from "./custom_fields_detail.js";

const root = document.getElementById("detail-root");
const { account, instrument, entryExecutionId } = root.dataset;
const title = document.getElementById("detail-title");
const headerDl = document.getElementById("detail-header");
const chartRoot = document.getElementById("chart-root");
const notesPanel = document.getElementById("notes-panel");
const reviewedToggle = document.getElementById("reviewed-toggle");
const executionsRoot = document.getElementById("executions-root");
const deleteBtn = document.getElementById("delete-button");

const ENTRY_KEY = `${account}/${instrument}/${entryExecutionId}`;
const DETAIL_URL = `/api/positions/${encodeURIComponent(account)}/${encodeURIComponent(instrument)}/${encodeURIComponent(entryExecutionId)}`;
const EXECUTIONS_URL = `${DETAIL_URL}/executions`;

function stripSuffix(eid) {
  for (const suf of ["#close", "#open"]) {
    if (eid.endsWith(suf)) return eid.slice(0, -suf.length);
  }
  return eid;
}

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

function renderReviewedToggle(detail) {
  const reviewed = Boolean(detail.reviewed[stripSuffix(entryExecutionId)]);
  reviewedToggle.innerHTML = "";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.id = "reviewed-checkbox";
  checkbox.checked = reviewed;
  checkbox.addEventListener("change", async () => {
    await patchJSON(
      `/api/executions/${encodeURIComponent(stripSuffix(entryExecutionId))}/reviewed`,
      { reviewed: checkbox.checked },
    );
  });
  const label = document.createElement("label");
  label.htmlFor = "reviewed-checkbox";
  setText(label, "Reviewed");
  reviewedToggle.appendChild(checkbox);
  reviewedToggle.appendChild(label);
}

function renderNotesPanel(detail) {
  const noteText = detail.notes[stripSuffix(entryExecutionId)] || "";
  notesPanel.innerHTML = "";
  const h = document.createElement("h3");
  setText(h, "Notes on entry execution");
  const ta = document.createElement("textarea");
  ta.value = noteText;
  const btn = document.createElement("button");
  setText(btn, "Save note");
  btn.addEventListener("click", async () => {
    await patchJSON(
      `/api/executions/${encodeURIComponent(stripSuffix(entryExecutionId))}/note`,
      { note: ta.value },
    );
    btn.textContent = "Saved";
    setTimeout(() => (btn.textContent = "Save note"), 1000);
  });
  notesPanel.appendChild(h);
  notesPanel.appendChild(ta);
  notesPanel.appendChild(btn);
}

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

function flashRow(executionId) {
  const tr = executionsRoot.querySelector(`tr[data-execution-id="${CSS.escape(executionId)}"]`);
  if (!tr) return;
  tr.scrollIntoView({ behavior: "smooth", block: "center" });
  const prev = tr.style.background;
  tr.style.background = "#FFD700";
  setTimeout(() => {
    tr.style.background = prev;
  }, 1500);
}

document.addEventListener("chart:execution-clicked", (ev) => {
  const id = ev?.detail?.executionId;
  if (id) flashRow(id);
});

deleteBtn.addEventListener("click", async () => {
  const detail = await fetchJSON(DETAIL_URL);
  const realIds = [...new Set(detail.position.execution_ids.map(stripSuffix))];
  if (!confirm(`This will delete ${realIds.length} executions and cannot be undone. Continue?`)) return;
  await postJSON("/api/executions/rollback", { execution_ids: realIds });
  window.location.href = "/positions";
});

(async () => {
  try {
    const [detail, execs] = await Promise.all([
      fetchJSON(DETAIL_URL),
      fetchJSON(EXECUTIONS_URL),
    ]);
    renderHeader(detail);
    renderReviewedToggle(detail);
    renderNotesPanel(detail);
    const cfContainer = document.getElementById("custom-fields-block");
    if (cfContainer) {
      mountCustomFields(cfContainer, detail, detail.position.entry_execution_id);
    }
    renderExecutions(execs.executions, detail);

    // Mount the chart. PriceChart.init does its own fetches for markers,
    // bars, available timeframes, and source snapshots. It is fire-and-forget
    // from this script's perspective — the page renders fully even if the
    // chart errors out.
    PriceChart.init({
      container: chartRoot,
      account,
      instrument,
      entryExecutionId,
    }).catch((e) => {
      console.error("PriceChart failed to init", e);
    });
  } catch (e) {
    setText(title, `Error loading ${ENTRY_KEY}: ${e.message}`);
  }
})();
