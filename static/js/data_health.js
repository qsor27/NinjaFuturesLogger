initDataHealth();

async function initDataHealth() {
  await renderSourcesBand();
  await renderMaintainerPanel();
  await renderMatrix();
  await renderAttemptsPanel();
  await renderGapsPanel();
}

async function renderMaintainerPanel() {
  const el = document.getElementById("maintainer-panel");
  if (!el) return;
  const resp = await fetch("/api/data-health/maintainer");
  const body = await resp.json();
  const next = body.next_run_at ? new Date(body.next_run_at * 1000).toLocaleString() : "—";
  const last = body.last_run_at ? new Date(body.last_run_at * 1000).toLocaleString() : "—";
  const lastStatus = body.last_run_status ?? "—";
  const tb = body.token_bucket || {};
  el.innerHTML = `
    <h3 style="margin-top:1em">Coverage Maintainer</h3>
    <table>
      <tr><th>Next run</th><td>${next}</td></tr>
      <tr><th>Last run</th><td>${last} (${escHtml(lastStatus)})</td></tr>
      <tr><th>Tokens available</th><td>${tb.available ?? "—"} / ${tb.capacity ?? "—"}</td></tr>
      <tr><th>Acquired (lifetime)</th><td>${tb.acquired_total ?? 0}</td></tr>
      <tr><th>Timeouts (lifetime)</th><td>${tb.timeouts_total ?? 0}</td></tr>
    </table>`;
}

async function renderSourcesBand() {
  const el = document.getElementById("sources-band");
  if (!el) return;
  const resp = await fetch("/api/ohlc/sources");
  const { sources } = await resp.json();
  const hasOpen = sources.some((s) => s.state === "open");
  let banner = "";
  if (hasOpen) {
    const openSources = sources.filter((s) => s.state === "open");
    banner = openSources.map((s) =>
      `<div class="alert-banner">
        OHLC source <strong>${escHtml(s.name)}</strong> is currently unavailable
        (since ${s.opened_at ? new Date(s.opened_at * 1000).toLocaleString() : "unknown"},
        reason: ${escHtml(s.last_error ?? "unknown")}).
        Falling back to next available source. The rest of the app continues to work normally.
      </div>`
    ).join("");
  }
  const rows = sources.map((s) => {
    const stateColor = s.state === "closed" ? "#0a7f0a" : s.state === "open" ? "#b00020" : "#c07000";
    const lastSuccess = s.last_success_at ? new Date(s.last_success_at * 1000).toLocaleString() : "—";
    const lastFail = s.last_failure_at ? new Date(s.last_failure_at * 1000).toLocaleString() : "—";
    // Plan 18: breaker reports next_retry_at directly (adaptive cooldown).
    const nextRetry = s.next_retry_at
      ? new Date(s.next_retry_at * 1000).toLocaleString()
      : "—";
    const tripsSuffix = s.consecutive_trips > 1 ? ` (trip ${s.consecutive_trips})` : "";
    const errTooltip = s.last_failure_class
      ? ` title="${escHtml(s.last_failure_class)}"`
      : "";
    const noteSuffix = s.name === "stooq"
      ? ' <span style="color:#6c757d;font-size:0.9em">(daily bars only — used as fallback for 1d when yfinance is unavailable)</span>'
      : '';
    return `<tr>
      <td>${escHtml(s.name)}${noteSuffix}</td>
      <td style="color:${stateColor};font-weight:600">${escHtml(s.state)}${tripsSuffix}</td>
      <td>${lastSuccess}</td>
      <td>${lastFail}</td>
      <td${errTooltip}>${escHtml(s.last_error ?? "—")}</td>
      <td>${nextRetry}</td>
    </tr>`;
  });
  el.innerHTML = `
    ${banner}
    <h3 style="margin-top:0">OHLC Sources</h3>
    <table>
      <thead><tr><th>Source</th><th>State</th><th>Last Success</th><th>Last Failure</th><th>Last Error</th><th>Next Retry</th></tr></thead>
      <tbody>${rows.join("")}</tbody>
    </table>`;
}

async function renderMatrix() {
  const el = document.getElementById("completeness-matrix");
  const urlDays = new URLSearchParams(window.location.search).get("days");
  const days = document.getElementById("days-input")?.value ?? urlDays;
  el.innerHTML = "<p>Loading…</p>";

  if (days) {
    const next = new URL(window.location.href);
    next.searchParams.set("days", days);
    window.history.replaceState(null, "", next);
  }

  const url = days ? `/api/data-health/completeness?days=${encodeURIComponent(days)}` : "/api/data-health/completeness";
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
    <div style="margin:0.5em 0;padding:0.5em;border:1px solid #ddd">
      <strong>Delete bars in window</strong>
      <div style="font-size:0.9em;color:#6c757d;margin:0.25em 0">
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

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// --- Recent fetch attempts ------------------------------------------------

async function renderAttemptsPanel() {
  const el = document.getElementById("attempts-panel");
  if (!el) return;
  const resp = await fetch("/api/ohlc/attempts?limit=40");
  const { attempts } = await resp.json();
  if (!attempts.length) {
    el.innerHTML = `<h3>Recent fetch attempts</h3><div class="notice">No attempts recorded yet.</div>`;
    return;
  }
  const rows = attempts.map((a) => {
    const started = a.started_at ? new Date(a.started_at * 1000).toLocaleString() : "—";
    const dur = a.completed_at && a.started_at
      ? `${a.completed_at - a.started_at}s` : "—";
    const status = a.final_status ?? "running";
    const color =
      status === "ok" ? "#0a7f0a"
      : status === "cached" ? "#6c757d"
      : status === "partial" ? "#c07000"
      : status === "interrupted" ? "#b00020"
      : status === "all_sources_unavailable" ? "#b00020" : "#333";
    const sources = (a.sources || []).map((s) => {
      const sc = s.outcome === "ok" ? "#0a7f0a"
        : s.outcome === "empty" ? "#6c757d"
        : s.outcome.startsWith("skipped") ? "#c07000" : "#b00020";
      const errTxt = s.error ? ` — ${escHtml(s.error)}` : "";
      return `<div style="padding-left:1em">
        <span style="color:${sc}">${escHtml(s.source)}</span>
        ${escHtml(s.outcome)} · ${s.bars_returned} bars · ${s.duration_ms ?? "—"}ms${errTxt}
      </div>`;
    }).join("");
    return `<tr>
      <td>${started}</td>
      <td>${escHtml(a.trigger)}</td>
      <td>${escHtml(a.instrument)} ${escHtml(a.timeframe)}</td>
      <td style="color:${color}">${escHtml(status)}</td>
      <td>${a.bars_written}</td>
      <td>${dur}</td>
    </tr>
    <tr class="source-detail"><td colspan="6">${sources}</td></tr>`;
  }).join("");
  el.innerHTML = `
    <h3>Recent fetch attempts</h3>
    <table>
      <thead><tr>
        <th>Time</th><th>Trigger</th><th>Target</th>
        <th>Status</th><th>Bars</th><th>Duration</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// --- Open gaps ------------------------------------------------------------

async function renderGapsPanel() {
  const el = document.getElementById("gaps-panel");
  if (!el) return;
  const [openResp, abandonedResp] = await Promise.all([
    fetch("/api/ohlc/gaps?state=open").then((r) => r.json()),
    fetch("/api/ohlc/gaps?state=abandoned").then((r) => r.json()),
  ]);
  const open = openResp.gaps || [];
  const abandoned = abandonedResp.gaps || [];
  el.innerHTML = `<h3>Open gaps (${open.length})</h3>` + renderGapTable(open, "open")
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
