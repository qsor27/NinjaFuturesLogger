// Data Health / Coverage tab: completeness matrix, per-cell detail panel,
// delete-and-refetch, stuck-gaps panel.

initCoverage();

async function initCoverage() {
  await renderMatrix();
  await renderGapsPanel();
}

async function renderMatrix() {
  const el = document.getElementById("completeness-matrix");
  if (!el) return;
  const urlDays = new URLSearchParams(window.location.search).get("days");
  const days = document.getElementById("days-input")?.value ?? urlDays;
  el.innerHTML = "<p>Loading…</p>";

  if (days) {
    const next = new URL(window.location.href);
    next.searchParams.set("days", days);
    window.history.replaceState(null, "", next);
  }

  const url = days
    ? `/api/data-health/completeness?days=${encodeURIComponent(days)}`
    : "/api/data-health/completeness";
  const resp = await fetch(url);
  const body = await resp.json();

  if (!body.instruments.length) {
    el.innerHTML = "<p>No instruments with executions in the last 90 days.</p>";
    return;
  }

  const statusStyle = {
    complete: "background:#d4edda;color:#155724",
    partial: "background:#fff3cd;color:#856404",
    missing: "background:#f8d7da;color:#721c24",
    out_of_reach: "background:#e2e3e5;color:#6c757d",
    pending: "background:#cce5ff;color:#004085",
    session_closed: "background:#e2e3e5;color:#383d41",
  };

  const headerCells = body.timeframes.map((tf) => `<th>${tf}</th>`).join("");
  const dataRows = body.instruments.map((inst) => {
    const cells = body.timeframes.map((tf) => {
      const status = body.cells[inst]?.[tf] ?? "missing";
      const style = statusStyle[status] ?? "";
      return `<td style="${style};text-align:center;cursor:pointer;padding:6px 10px"
               data-inst="${inst}" data-tf="${tf}" class="cell-btn"
               title="${status}">${status}</td>`;
    }).join("");
    return `<tr><td><strong>${escHtml(inst)}</strong></td>${cells}</tr>`;
  }).join("");

  el.innerHTML = `
    <div style="margin-bottom:8px">
      <label>Lookback days: <input type="number" id="days-input" value="${body.days}" min="1" max="365" style="width:60px"></label>
      <button id="reload-btn">Reload</button>
    </div>
    <table>
      <thead><tr><th>Instrument</th>${headerCells}</tr></thead>
      <tbody>${dataRows}</tbody>
    </table>`;

  el.querySelectorAll(".cell-btn").forEach((btn) => {
    btn.addEventListener("click", () => openDetailPanel(btn.dataset.inst, btn.dataset.tf, body.window_start, body.window_end));
  });
  document.getElementById("reload-btn").addEventListener("click", async () => {
    await renderMatrix();
  });
  const daysInput = document.getElementById("days-input");
  daysInput.addEventListener("change", async () => {
    await renderMatrix();
  });
  daysInput.addEventListener("keydown", async (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      await renderMatrix();
    }
  });
}

async function openDetailPanel(instrument, timeframe, start, end) {
  const panel = document.getElementById("detail-panel");
  panel.style.display = "block";
  panel.innerHTML = `<h3>${escHtml(instrument)} / ${escHtml(timeframe)} — gaps</h3><p>Loading…</p>`;

  const resp = await fetch(`/api/data-health/missing/${instrument}/${timeframe}?start=${start}&end=${end}`);
  const body = await resp.json();

  const deleteControls = `
    <div style="margin:0.5em 0;padding:0.5em;border:1px solid var(--border-card)">
      <strong>Delete bars in window</strong>
      <div style="font-size:0.9em;color:var(--text-muted);margin:0.25em 0">
        Removes all stored bars in this window. The next fetch (on-demand or self-heal) will repopulate.
      </div>
      <button id="delete-bars-btn"
        data-inst="${instrument}" data-tf="${timeframe}"
        data-start="${start}" data-end="${end}">Delete + refetch</button>
      <span id="delete-bars-status" style="margin-left:0.5em"></span>
    </div>`;

  if (!body.gaps.length) {
    panel.innerHTML = `<h3>${escHtml(instrument)} / ${escHtml(timeframe)}</h3>
      <p>No gaps in this window. ${body.present_bars} of ${body.expected_slots} expected bars present.</p>
      ${deleteControls}
      <button id="close-panel">Close</button>`;
  } else {
    const gapRows = body.gaps.map((g) =>
      `<tr>
        <td>${new Date(g.start * 1000).toLocaleString()}</td>
        <td>${new Date(g.end * 1000).toLocaleString()}</td>
        <td>
          <button class="fetch-gap-btn"
            data-inst="${instrument}" data-tf="${timeframe}"
            data-start="${g.start}" data-end="${g.end}">Fetch Missing</button>
        </td>
      </tr>`
    ).join("");
    panel.innerHTML = `
      <h3>${escHtml(instrument)} / ${escHtml(timeframe)}</h3>
      <p>${body.present_bars} of ${body.expected_slots} expected bars present. ${body.gaps.length} gap(s):</p>
      <table>
        <thead><tr><th>Gap Start</th><th>Gap End</th><th>Action</th></tr></thead>
        <tbody>${gapRows}</tbody>
      </table>
      ${deleteControls}
      <button id="close-panel">Close</button>`;

    panel.querySelectorAll(".fetch-gap-btn").forEach((btn) => {
      btn.addEventListener("click", () => fetchGap(btn.dataset.inst, btn.dataset.tf, btn.dataset.start, btn.dataset.end, btn));
    });
  }

  const delBtn = document.getElementById("delete-bars-btn");
  if (delBtn) {
    delBtn.addEventListener("click", async () => {
      const inst = delBtn.dataset.inst;
      const tf = delBtn.dataset.tf;
      const s = parseInt(delBtn.dataset.start);
      const e = parseInt(delBtn.dataset.end);
      const rangeLabel = `${new Date(s * 1000).toLocaleString()} – ${new Date(e * 1000).toLocaleString()}`;
      if (!window.confirm(`Delete all ${inst} ${tf} bars in\n${rangeLabel}?\n\nThis cannot be undone. A fetch will be triggered automatically afterwards.`)) {
        return;
      }
      const status = document.getElementById("delete-bars-status");
      delBtn.disabled = true;
      status.textContent = "Deleting…";
      const delResp = await fetch("/api/ohlc/bars/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instrument: inst, timeframe: tf, start: s, end: e }),
      });
      const delBody = await delResp.json();
      if (!delResp.ok) {
        status.textContent = `Error: ${delBody.error || "unknown"}`;
        delBtn.disabled = false;
        return;
      }
      status.textContent = `Deleted ${delBody.deleted} bars. Refetching…`;
      const fetchResp = await fetch(`/api/chart/${inst}/fetch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ timeframe: tf, start: s, end: e }),
      });
      const fetchBody = await fetchResp.json();
      if (fetchResp.status === 202) {
        status.textContent = `Deleted ${delBody.deleted} bars. Refetch job ${fetchBody.job_id} started.`;
      } else {
        status.textContent = `Deleted ${delBody.deleted} bars. Refetch error: ${fetchBody.error || fetchResp.status}`;
      }
    });
  }
  document.getElementById("close-panel")?.addEventListener("click", () => {
    panel.style.display = "none";
  });
}

async function fetchGap(instrument, timeframe, start, end, btn) {
  btn.textContent = "Fetching…";
  btn.disabled = true;
  const resp = await fetch(`/api/chart/${instrument}/fetch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ timeframe, start: parseInt(start), end: parseInt(end) }),
  });
  const body = await resp.json();
  if (resp.status === 202) {
    btn.textContent = `Job ${body.job_id} started`;
    pollJob(body.job_id, btn);
  } else if (resp.status === 409 && body.error === "out_of_reach") {
    btn.textContent = "Out of reach";
    btn.title = body.detail || "Provider does not serve this range";
    btn.disabled = true;
  } else {
    btn.textContent = "Error";
    btn.disabled = false;
  }
}

async function pollJob(jobId, btn) {
  const resp = await fetch(`/api/ohlc/jobs/${jobId}`);
  const body = await resp.json();
  if (body.state === "done") {
    btn.textContent = "Done — reload to see changes";
  } else if (body.state === "error") {
    btn.textContent = "Fetch failed";
    btn.disabled = false;
  } else {
    setTimeout(() => pollJob(jobId, btn), 1000);
  }
}

async function renderGapsPanel() {
  const el = document.getElementById("gaps-panel");
  if (!el) return;
  const [openResp, abandonedResp] = await Promise.all([
    fetch("/api/ohlc/gaps?state=open").then((r) => r.json()),
    fetch("/api/ohlc/gaps?state=abandoned").then((r) => r.json()),
  ]);
  const open = openResp.gaps || [];
  const abandoned = abandonedResp.gaps || [];
  el.innerHTML = `<div style="color:var(--text-muted);margin-bottom:0.5em">Open gaps (${open.length})</div>`
    + renderGapTable(open, "open")
    + (abandoned.length
        ? `<h4 style="margin-top:1em">Abandoned gaps (${abandoned.length})</h4>`
          + renderGapTable(abandoned, "abandoned")
        : "");

  el.querySelectorAll("button[data-retry-id]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-retry-id");
      btn.disabled = true;
      btn.textContent = "Retrying…";
      try {
        await fetch(`/api/ohlc/gaps/${id}/retry`, { method: "POST" });
        setTimeout(() => renderGapsPanel(), 2000);
      } catch (_e) {
        btn.textContent = "Retry (failed)";
      }
    });
  });
}

function renderGapTable(rows, variant) {
  if (!rows.length) {
    return `<div class="notice">No ${variant} gaps.</div>`;
  }
  const body = rows.map((g) => {
    const range = `${new Date(g.gap_start * 1000).toLocaleString()} – ${new Date(g.gap_end * 1000).toLocaleString()}`;
    const nextRetry = g.next_retry_at
      ? new Date(g.next_retry_at * 1000).toLocaleString() : "—";
    return `<tr>
      <td>${escHtml(g.instrument)}</td>
      <td>${escHtml(g.timeframe)}</td>
      <td>${range}</td>
      <td>${g.attempt_count}</td>
      <td>${nextRetry}</td>
      <td><button data-retry-id="${g.id}">${variant === "abandoned" ? "Try again" : "Retry now"}</button></td>
    </tr>`;
  }).join("");
  return `<table>
    <thead><tr>
      <th>Instrument</th><th>TF</th><th>Range</th>
      <th>Attempts</th><th>Next retry</th><th></th>
    </tr></thead>
    <tbody>${body}</tbody>
  </table>`;
}

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
