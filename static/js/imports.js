const isDetail = document.getElementById("tick-detail") !== null;

if (isDetail) {
  initDetail();
} else {
  initList();
}

// ------------------------------------------------------------------ //
// List page                                                           //
// ------------------------------------------------------------------ //

async function initList() {
  await renderCursorsBand();
  renderFilters();
  await loadRuns();
  document.getElementById("scan-btn")?.addEventListener("click", onScanNow);
}

async function renderCursorsBand() {
  const band = document.getElementById("cursors-band");
  if (!band) return;
  const resp = await fetch("/api/imports/cursors");
  const { cursors } = await resp.json();
  if (!cursors.length) {
    band.innerHTML = "<p style='color:#888'>No active inbox files.</p>";
    return;
  }
  const rows = cursors.map((c) => {
    const cursor = c.byte_offset.toLocaleString();
    const modified = c.last_modified
      ? new Date(c.last_modified * 1000).toLocaleString()
      : "—";
    return `<tr>
      <td>${escHtml(c.filename)}</td>
      <td>${cursor} bytes</td>
      <td>${modified}</td>
    </tr>`;
  });
  band.innerHTML = `
    <h3 style="margin-top:0">Active Inbox Files</h3>
    <button id="scan-btn" style="margin-bottom:8px">Scan Now</button>
    <table>
      <thead><tr><th>File</th><th>Cursor Position</th><th>Last Modified</th></tr></thead>
      <tbody>${rows.join("")}</tbody>
    </table>`;
}

function renderFilters() {
  const bar = document.getElementById("filters-bar");
  if (!bar) return;
  const sevenDaysAgo = Math.floor(Date.now() / 1000) - 7 * 86400;
  bar.innerHTML = `
    <label>From<input type="date" id="f-start" value="${epochToDateInput(sevenDaysAgo)}"></label>
    <label>To<input type="date" id="f-end"></label>
    <label>Filename<input type="text" id="f-filename" placeholder="partial match"></label>
    <label>Status
      <select id="f-status">
        <option value="">All</option>
        <option value="ok">ok</option>
        <option value="partial">partial</option>
        <option value="failed">failed</option>
      </select>
    </label>
    <button id="apply-btn">Apply</button>`;
  document.getElementById("apply-btn").addEventListener("click", () => {
    currentOffset = 0;
    loadRuns();
  });
}

let currentOffset = 0;
const PAGE_SIZE = 50;

async function loadRuns() {
  const start = document.getElementById("f-start")?.value;
  const end = document.getElementById("f-end")?.value;
  const filename = document.getElementById("f-filename")?.value || "";
  const status = document.getElementById("f-status")?.value || "";

  const params = new URLSearchParams({ limit: PAGE_SIZE, offset: currentOffset });
  if (start) params.set("start_ts", dateInputToEpoch(start));
  if (end) params.set("end_ts", dateInputToEpoch(end) + 86399);
  if (filename) params.set("filename", filename);
  if (status) params.set("status", status);

  const resp = await fetch(`/api/imports/runs?${params}`);
  const body = await resp.json();
  renderRunsTable(body.runs, body.total);
}

function renderRunsTable(runs, total) {
  const container = document.getElementById("runs-table");
  if (!runs.length) {
    container.innerHTML = "<p>No import ticks found.</p>";
    return;
  }
  const rows = runs.map((r) => {
    const started = new Date(r.started_at * 1000).toLocaleString();
    const duration = r.finished_at && r.started_at
      ? ((r.finished_at - r.started_at) * 1000).toFixed(0) + " ms"
      : "—";
    const cursor = `${r.cursor_before} → ${r.cursor_after}`;
    return `<tr style="cursor:pointer" data-tid="${r.tick_id}">
      <td>${r.tick_id}</td>
      <td>${escHtml(r.filename)}</td>
      <td>${started}</td>
      <td>${duration}</td>
      <td>${escHtml(r.status)}</td>
      <td>${r.rows_inserted}</td>
      <td>${r.rows_skipped_duplicate}</td>
      <td>${r.rows_rejected}</td>
      <td>${escHtml(cursor)}</td>
    </tr>`;
  });
  container.innerHTML = `
    <p style="color:#666">${total} total</p>
    <table>
      <thead>
        <tr>
          <th>ID</th><th>File</th><th>Started</th><th>Duration</th>
          <th>Status</th><th>Inserted</th><th>Dups</th><th>Rejected</th><th>Cursor</th>
        </tr>
      </thead>
      <tbody>${rows.join("")}</tbody>
    </table>
    <div class="pagination">
      <button id="prev-btn" ${currentOffset === 0 ? "disabled" : ""}>Previous</button>
      <span>Showing ${currentOffset + 1}–${Math.min(currentOffset + PAGE_SIZE, total)} of ${total}</span>
      <button id="next-btn" ${currentOffset + PAGE_SIZE >= total ? "disabled" : ""}>Next</button>
    </div>`;

  container.querySelectorAll("tbody tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      window.location.href = `/imports/${tr.dataset.tid}`;
    });
  });
  document.getElementById("prev-btn")?.addEventListener("click", () => {
    currentOffset = Math.max(0, currentOffset - PAGE_SIZE);
    loadRuns();
  });
  document.getElementById("next-btn")?.addEventListener("click", () => {
    currentOffset += PAGE_SIZE;
    loadRuns();
  });
}

async function onScanNow() {
  const btn = document.getElementById("scan-btn");
  btn.textContent = "Scanning…";
  btn.disabled = true;
  try {
    const resp = await fetch("/api/imports/scan", { method: "POST" });
    const body = await resp.json();
    alert(`Scan complete: ${body.ticked} file(s) ticked.`);
    await renderCursorsBand();
    await loadRuns();
  } finally {
    const newBtn = document.getElementById("scan-btn");
    if (newBtn) {
      newBtn.textContent = "Scan Now";
      newBtn.disabled = false;
      newBtn.addEventListener("click", onScanNow);
    }
  }
}

// ------------------------------------------------------------------ //
// Detail page                                                         //
// ------------------------------------------------------------------ //

async function initDetail() {
  const el = document.getElementById("tick-detail");
  const tickId = parseInt(el.dataset.tickId, 10);

  const resp = await fetch(`/api/imports/runs/${tickId}`);
  if (!resp.ok) {
    el.textContent = "Tick not found.";
    return;
  }
  const tick = await resp.json();
  renderTickDetail(tick);
  renderRejectsTable(tick.rejects || []);
  await renderRollbackSection(tickId, tick);
}

function renderTickDetail(tick) {
  const el = document.getElementById("tick-detail");
  const started = new Date(tick.started_at * 1000).toLocaleString();
  const finished = tick.finished_at ? new Date(tick.finished_at * 1000).toLocaleString() : "—";
  const duration = tick.finished_at
    ? ((tick.finished_at - tick.started_at) * 1000).toFixed(0) + " ms"
    : "—";
  el.innerHTML = `
    <dl class="detail-header">
      <dt>File</dt><dd>${escHtml(tick.filename)}</dd>
      <dt>Status</dt><dd>${escHtml(tick.status)}</dd>
      <dt>Started</dt><dd>${started}</dd>
      <dt>Finished</dt><dd>${finished}</dd>
      <dt>Duration</dt><dd>${duration}</dd>
      <dt>Inserted</dt><dd>${tick.rows_inserted}</dd>
      <dt>Duplicates</dt><dd>${tick.rows_skipped_duplicate}</dd>
      <dt>Rejected</dt><dd>${tick.rows_rejected}</dd>
      <dt>Cursor Before</dt><dd>${tick.cursor_before}</dd>
      <dt>Cursor After</dt><dd>${tick.cursor_after}</dd>
    </dl>`;
}

function renderRejectsTable(rejects) {
  const el = document.getElementById("rejects-table");
  if (!rejects.length) {
    el.innerHTML = "<p>No rejected rows.</p>";
    return;
  }
  const rows = rejects.map((r) =>
    `<tr>
      <td>${r.line_number}</td>
      <td>${escHtml(r.reason)}</td>
      <td><code>${escHtml(r.raw_line)}</code></td>
    </tr>`
  );
  el.innerHTML = `
    <h2>Rejected Rows (${rejects.length})</h2>
    <table>
      <thead><tr><th>Line</th><th>Reason</th><th>Raw</th></tr></thead>
      <tbody>${rows.join("")}</tbody>
    </table>`;
}

async function renderRollbackSection(tickId, tick) {
  const el = document.getElementById("rollback-section");
  const resp = await fetch(`/api/imports/runs/${tickId}/executions`);
  if (!resp.ok) {
    el.innerHTML = "";
    return;
  }
  const { execution_ids: ids } = await resp.json();
  if (!ids.length) {
    el.innerHTML = "<p>No executions found for this tick (already rolled back or nothing was inserted).</p>";
    return;
  }
  el.innerHTML = `
    <h2>Rollback</h2>
    <p>This tick inserted <strong>${ids.length}</strong> execution(s). Rolling back deletes them.</p>
    <button class="danger" id="rollback-btn">Roll Back This Tick</button>`;
  document.getElementById("rollback-btn").addEventListener("click", async () => {
    const preview = ids.slice(0, 5).join(", ") + (ids.length > 5 ? ` … +${ids.length - 5} more` : "");
    if (!confirm(`Delete ${ids.length} execution(s)?\n\n${preview}`)) return;
    const r = await fetch("/api/executions/rollback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ execution_ids: ids }),
    });
    const body = await r.json();
    alert(`Rolled back ${body.deleted} execution(s).`);
    window.location.href = "/imports";
  });
}

// ------------------------------------------------------------------ //
// Helpers                                                             //
// ------------------------------------------------------------------ //

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function epochToDateInput(ts) {
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

function dateInputToEpoch(s) {
  return Math.floor(new Date(s).getTime() / 1000);
}
