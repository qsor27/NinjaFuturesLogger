import {
  fetchJSON,
  formatDollars,
  formatTime,
  patchJSON,
  postJSON,
  setText,
} from "./api.js";

const root = document.getElementById("detail-root");
const { account, instrument, entryExecutionId } = root.dataset;
const title = document.getElementById("detail-title");
const headerDl = document.getElementById("detail-header");
const notesPanel = document.getElementById("notes-panel");
const reviewedToggle = document.getElementById("reviewed-toggle");
const executionsRoot = document.getElementById("executions-root");
const linksPanel = document.getElementById("links-panel");
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
    ["Account", p.account],
    ["Instrument", p.instrument],
    ["Side", p.side],
    ["Qty", p.quantity],
    ["Entry time", formatTime(p.entry_time)],
    ["Exit time", formatTime(p.exit_time)],
    ["Entry price", p.entry_price.toFixed(2)],
    ["Exit price", p.exit_price !== null ? p.exit_price.toFixed(2) : "—"],
    ["Points P&L", p.points_pnl !== null ? p.points_pnl.toFixed(2) : "—"],
    ["$ P&L", formatDollars(p.dollars_pnl).text],
    ["Commission", `$${p.commission.toFixed(2)}`],
    ["Duration", p.duration_minutes !== null ? p.duration_minutes.toFixed(1) + " m" : "—"],
  ];
  headerDl.innerHTML = "";
  for (const [label, value] of rows) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    setText(dt, label);
    setText(dd, value);
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
    <tr><th>ID</th><th>Time</th><th>Side</th><th>Qty</th><th>Price</th><th>Commission</th><th>Action</th><th>Reviewed</th></tr>`;
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  for (const e of executions) {
    const tr = document.createElement("tr");
    const td = (text) => {
      const c = document.createElement("td");
      setText(c, text);
      return c;
    };
    tr.appendChild(td(e.nt_execution_id));
    tr.appendChild(td(formatTime(e.timestamp)));
    tr.appendChild(td(e.side));
    tr.appendChild(td(e.quantity));
    tr.appendChild(td(e.price.toFixed(2)));
    tr.appendChild(td(`$${e.commission.toFixed(2)}`));
    tr.appendChild(td(e.original_action));
    tr.appendChild(td(detail.reviewed[e.nt_execution_id] ? "✓" : ""));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  executionsRoot.appendChild(table);
}

function renderLinksPanel() {
  linksPanel.innerHTML = "";
  const btn = document.createElement("button");
  setText(btn, "Add this position to a new link group");
  btn.addEventListener("click", async () => {
    const label = prompt("Link group label (optional):", "");
    const resp = await postJSON("/api/links", {
      label: label || null,
      members: [{ account, instrument, entry_execution_id: entryExecutionId }],
    });
    alert(`Created link group ${resp.link_group_id}. Edit members on /links/${resp.link_group_id}.`);
  });
  linksPanel.appendChild(btn);
}

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
    renderExecutions(execs.executions, detail);
    renderLinksPanel();
  } catch (e) {
    setText(title, `Error loading ${ENTRY_KEY}: ${e.message}`);
  }
})();
