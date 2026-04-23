// Data Health / System tab: source breakers, coverage maintainer + rate
// limiter, full per-fetch activity log.

initSystem();

async function initSystem() {
  await renderSourcesBand();
  await renderMaintainerPanel();
  await renderAttemptsPanel();
}

async function renderSourcesBand() {
  const el = document.getElementById("sources-band");
  if (!el) return;
  const resp = await fetch("/api/ohlc/sources");
  const { sources } = await resp.json();
  const rows = sources.map((s) => {
    const stateColor = s.state === "closed" ? "#0a7f0a" : s.state === "open" ? "#b00020" : "#c07000";
    const lastSuccess = s.last_success_at ? new Date(s.last_success_at * 1000).toLocaleString() : "—";
    const lastFail = s.last_failure_at ? new Date(s.last_failure_at * 1000).toLocaleString() : "—";
    const nextRetry = s.next_retry_at
      ? new Date(s.next_retry_at * 1000).toLocaleString()
      : "—";
    const tripsSuffix = s.consecutive_trips > 1 ? ` (trip ${s.consecutive_trips})` : "";
    const errTooltip = s.last_failure_class
      ? ` title="${escHtml(s.last_failure_class)}"`
      : "";
    const noteSuffix = s.name === "stooq"
      ? ' <span style="color:var(--text-muted);font-size:0.9em">(daily bars only — used as fallback for 1d when yfinance is unavailable)</span>'
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
    <table>
      <thead><tr><th>Source</th><th>State</th><th>Last Success</th><th>Last Failure</th><th>Last Error</th><th>Next Retry</th></tr></thead>
      <tbody>${rows.join("")}</tbody>
    </table>`;
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
    <table>
      <tr><th>Next run</th><td>${next}</td></tr>
      <tr><th>Last run</th><td>${last} (${escHtml(lastStatus)})</td></tr>
      <tr><th>Tokens available</th><td>${tb.available ?? "—"} / ${tb.capacity ?? "—"}</td></tr>
      <tr><th>Acquired (lifetime)</th><td>${tb.acquired_total ?? 0}</td></tr>
      <tr><th>Timeouts (lifetime)</th><td>${tb.timeouts_total ?? 0}</td></tr>
    </table>`;
}

async function renderAttemptsPanel() {
  const el = document.getElementById("attempts-panel");
  if (!el) return;
  const resp = await fetch("/api/ohlc/attempts?limit=40");
  const { attempts } = await resp.json();
  if (!attempts.length) {
    el.innerHTML = `<div class="notice">No attempts recorded yet.</div>`;
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
    <table>
      <thead><tr>
        <th>Time</th><th>Trigger</th><th>Target</th>
        <th>Status</th><th>Bars</th><th>Duration</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
