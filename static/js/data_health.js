initDataHealth();

async function initDataHealth() {
  await renderSourcesBand();
  await renderMatrix();
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
    const nextRetry = s.state === "open" && s.opened_at
      ? new Date((s.opened_at + 600) * 1000).toLocaleString()
      : "—";
    return `<tr>
      <td>${escHtml(s.name)}</td>
      <td style="color:${stateColor};font-weight:600">${escHtml(s.state)}</td>
      <td>${lastSuccess}</td>
      <td>${lastFail}</td>
      <td>${escHtml(s.last_error ?? "—")}</td>
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
  el.innerHTML = "<p>Loading…</p>";

  const resp = await fetch("/api/data-health/completeness");
  const body = await resp.json();

  if (!body.instruments.length) {
    el.innerHTML = "<p>No instruments with executions in the last 90 days.</p>";
    return;
  }

  const statusStyle = {
    complete: "background:#d4edda;color:#155724",
    partial: "background:#fff3cd;color:#856404",
    missing: "background:#f8d7da;color:#721c24",
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
}

async function openDetailPanel(instrument, timeframe, start, end) {
  const panel = document.getElementById("detail-panel");
  panel.style.display = "block";
  panel.innerHTML = `<h3>${escHtml(instrument)} / ${escHtml(timeframe)} — gaps</h3><p>Loading…</p>`;

  const resp = await fetch(`/api/data-health/missing/${instrument}/${timeframe}?start=${start}&end=${end}`);
  const body = await resp.json();

  if (!body.gaps.length) {
    panel.innerHTML = `<h3>${escHtml(instrument)} / ${escHtml(timeframe)}</h3>
      <p>No gaps in this window. ${body.present_bars} of ${body.expected_slots} expected bars present.</p>
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
      <button id="close-panel">Close</button>`;

    panel.querySelectorAll(".fetch-gap-btn").forEach((btn) => {
      btn.addEventListener("click", () => fetchGap(btn.dataset.inst, btn.dataset.tf, btn.dataset.start, btn.dataset.end, btn));
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
