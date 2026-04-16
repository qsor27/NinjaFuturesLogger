import {
  parseFilterFromUrl,
  filterToQueryString,
  renderFilterBar,
} from "./stats_filter.js";
import { mountLineChart } from "./stats_charts.js";

const ENDPOINTS = [
  "summary",
  "by-side",
  "equity-curve",
  "by-instrument",
  "by-day",             // drives summary avg win-day / avg loss-day
  "by-hour",
  "by-day-of-week",
  "by-trades-per-day",
];

// Browser-local IANA timezone — forwarded to /api/stats/by-hour so hour
// buckets reflect the viewer's clock, not the exchange (or a configured
// default). Harmless for endpoints that ignore it.
function browserTz() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

async function fetchAll(filter) {
  let qs = filterToQueryString(filter);
  const tz = browserTz();
  if (tz) {
    qs += qs ? `&display_tz=${encodeURIComponent(tz)}` : `?display_tz=${encodeURIComponent(tz)}`;
  }
  const responses = await Promise.all(
    ENDPOINTS.map((name) => fetch(`/api/stats/${name}${qs}`).then((r) => r.json())),
  );
  return Object.fromEntries(ENDPOINTS.map((n, i) => [n, responses[i]]));
}

function fmtMoney(v) {
  if (v === null || v === undefined) return "—";
  const sign = v >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function fmtPercent(v) {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtNum(v, digits = 1) {
  if (v === null || v === undefined) return "—";
  return Number(v).toFixed(digits);
}

function _avgDayPnl(dayBuckets, positive) {
  const days = dayBuckets.filter(
    (b) => b.position_count > 0 && (positive ? b.total_pnl > 0 : b.total_pnl < 0),
  );
  if (!days.length) return null;
  return days.reduce((s, b) => s + b.total_pnl, 0) / days.length;
}

function renderSummary(container, summary, dayBuckets) {
  const avgWinDay = _avgDayPnl(dayBuckets, true);
  const avgLossDay = _avgDayPnl(dayBuckets, false);

  container.innerHTML = `
    <p class="section-label">Summary</p>
    <p class="big-number ${summary.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(summary.total_pnl)}</p>
    <div class="summary-grid">
      <div><div class="stat-label">Trades</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Win Rate</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Profit Factor</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Avg Hold (min)</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Median Hold (min)</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Avg Win</div><div class="stat-value pnl-pos"></div></div>
      <div><div class="stat-label">Avg Loss</div><div class="stat-value pnl-neg"></div></div>
      <div><div class="stat-label">Largest Win</div><div class="stat-value pnl-pos"></div></div>
      <div><div class="stat-label">Largest Loss</div><div class="stat-value pnl-neg"></div></div>
      <div><div class="stat-label">Wins</div><div class="stat-value pnl-pos"></div></div>
      <div><div class="stat-label">Losses</div><div class="stat-value pnl-neg"></div></div>
      <div><div class="stat-label">Scratch</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Win Streak</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Loss Streak</div><div class="stat-value pnl-neg"></div></div>
      <div><div class="stat-label">Avg Size</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Open</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Avg Win Day</div><div class="stat-value pnl-pos"></div></div>
      <div><div class="stat-label">Avg Loss Day</div><div class="stat-value pnl-neg"></div></div>
    </div>
  `;
  const values = container.querySelectorAll(".summary-grid .stat-value");
  values[0].textContent = String(summary.total_positions);
  values[1].textContent = fmtPercent(summary.win_rate);
  values[2].textContent = fmtNum(summary.profit_factor, 2);
  values[3].textContent = fmtNum(summary.avg_hold_minutes, 1);
  values[4].textContent = fmtNum(summary.median_hold_minutes, 1);
  values[5].textContent = fmtMoney(summary.avg_win);
  values[6].textContent = fmtMoney(summary.avg_loss);
  values[7].textContent = fmtMoney(summary.largest_win);
  values[8].textContent = fmtMoney(summary.largest_loss);
  values[9].textContent = String(summary.wins ?? 0);
  values[10].textContent = String(summary.losses ?? 0);
  values[11].textContent = String(summary.scratches ?? 0);
  values[12].textContent = String(summary.longest_win_streak);
  values[13].textContent = String(summary.longest_loss_streak);
  values[14].textContent = fmtNum(summary.avg_position_size, 1);
  values[15].textContent = String(summary.open_positions);
  values[16].textContent = fmtMoney(avgWinDay);
  values[17].textContent = fmtMoney(avgLossDay);

  if (summary.skipped_no_multiplier > 0) {
    const warn = document.createElement("div");
    warn.className = "warning-row";
    warn.textContent = `${summary.skipped_no_multiplier} positions excluded — add their instruments to the multiplier registry.`;
    container.appendChild(warn);
  }
}

function renderBySide(container, breakdown) {
  function sideCol(label, s) {
    return `
      <div class="side-col">
        <div class="side-col-header">
          ${label}<span class="side-count">${s.position_count} trades</span>
        </div>
        <div class="side-stat">
          <span class="side-stat-label">Total P&L</span>
          <span class="side-stat-value ${s.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(s.total_pnl)}</span>
        </div>
        <div class="side-stat">
          <span class="side-stat-label">Win Rate</span>
          <span class="side-stat-value">${fmtPercent(s.win_rate)}</span>
        </div>
        <div class="side-stat">
          <span class="side-stat-label">Avg Win</span>
          <span class="side-stat-value pnl-pos">${fmtMoney(s.avg_win)}</span>
        </div>
        <div class="side-stat">
          <span class="side-stat-label">Avg Loss</span>
          <span class="side-stat-value pnl-neg">${fmtMoney(s.avg_loss)}</span>
        </div>
        <div class="side-stat">
          <span class="side-stat-label">Profit Factor</span>
          <span class="side-stat-value">${fmtNum(s.profit_factor, 2)}</span>
        </div>
      </div>
    `;
  }
  container.innerHTML = `
    <p class="section-label">Long vs Short</p>
    <div class="side-grid">
      ${sideCol("Long", breakdown.long)}
      ${sideCol("Short", breakdown.short)}
    </div>
  `;
}

function renderInstrumentTable(container, breakdown) {
  if (!breakdown.rows.length) {
    container.innerHTML =
      '<p class="section-label">By Instrument</p><div class="empty-state">No data</div>';
    return;
  }
  const rowsHtml = breakdown.rows
    .map(
      (r) => `
    <tr>
      <td>${r.instrument}</td>
      <td>${r.position_count}</td>
      <td class="${r.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(r.total_pnl)}</td>
      <td>${fmtPercent(r.win_rate)}</td>
      <td class="${r.avg_pnl_per_position >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(r.avg_pnl_per_position)}</td>
    </tr>
  `,
    )
    .join("");
  container.innerHTML = `
    <p class="section-label">By Instrument</p>
    <table class="instrument-table">
      <thead><tr><th>Instr</th><th>Trades</th><th>P&amp;L</th><th>Win %</th><th>Avg P&amp;L</th></tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>
  `;
}

function renderDayOfWeek(container, dowData) {
  if (!dowData.buckets || dowData.buckets.every((b) => b.trades === 0)) {
    container.innerHTML =
      '<p class="section-label">By Day of Week</p><div class="empty-state">No data for this filter</div>';
    return;
  }
  const rowsHtml = dowData.buckets
    .map(
      (b) => `
    <tr>
      <td>${b.day_name}</td>
      <td>${b.trades}</td>
      <td class="${b.avg_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(b.avg_pnl)}</td>
      <td>${fmtPercent(b.win_rate)}</td>
      <td class="${b.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(b.total_pnl)}</td>
    </tr>
  `,
    )
    .join("");
  container.innerHTML = `
    <p class="section-label">By Day of Week</p>
    <table class="instrument-table">
      <thead><tr><th>Day</th><th>Trades</th><th>Avg P&amp;L</th><th>Win Rate</th><th>Total P&amp;L</th></tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>
  `;
}

function renderByHour(container, hourData) {
  const active = (hourData.buckets || []).filter((b) => b.position_count > 0);
  const header = `<p class="section-label">By Hour (${hourData.timezone})</p>`;
  if (!active.length) {
    container.innerHTML = `${header}<div class="empty-state">No data for this filter</div>`;
    return;
  }
  const rowsHtml = active
    .map((b) => {
      const avgPnl = b.position_count > 0 ? b.total_pnl / b.position_count : 0;
      return `
    <tr>
      <td>${String(b.hour).padStart(2, "0")}:00</td>
      <td>${b.position_count}</td>
      <td class="${avgPnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(avgPnl)}</td>
      <td>${fmtPercent(b.win_rate)}</td>
      <td class="${b.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(b.total_pnl)}</td>
    </tr>
  `;
    })
    .join("");
  container.innerHTML = `
    ${header}
    <table class="instrument-table">
      <thead><tr><th>Hour</th><th>Trades</th><th>Avg P&amp;L</th><th>Win Rate</th><th>Total P&amp;L</th></tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>
  `;
}

function renderTradesPerDay(container, tpdData) {
  if (!tpdData.buckets || !tpdData.buckets.length) {
    container.innerHTML =
      '<p class="section-label">Trades per Day</p><div class="empty-state">No data for this filter</div>';
    return;
  }
  const rowsHtml = tpdData.buckets
    .map(
      (b) => `
    <tr>
      <td>${b.trades_per_day}</td>
      <td>${b.days}</td>
      <td class="${b.avg_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(b.avg_pnl)}</td>
      <td>${fmtPercent(b.win_rate)}</td>
      <td class="${b.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(b.total_pnl)}</td>
    </tr>
  `,
    )
    .join("");
  container.innerHTML = `
    <p class="section-label">Trades per Day</p>
    <table class="instrument-table">
      <thead><tr><th>Trades/Day</th><th>Days</th><th>Avg P&amp;L</th><th>Win Rate</th><th>Total P&amp;L</th></tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>
  `;
}

async function refresh(filter) {
  document.querySelectorAll(".bento-cell").forEach((c) => (c.style.opacity = "0.5"));
  const data = await fetchAll(filter);

  renderSummary(
    document.getElementById("stats-summary"),
    data["summary"],
    data["by-day"].buckets,
  );
  renderBySide(document.getElementById("stats-by-side"), data["by-side"]);
  renderInstrumentTable(document.getElementById("stats-by-instrument"), data["by-instrument"]);
  renderDayOfWeek(document.getElementById("stats-by-dow"), data["by-day-of-week"]);
  renderByHour(document.getElementById("stats-by-hour"), data["by-hour"]);
  renderTradesPerDay(
    document.getElementById("stats-trades-per-day"),
    data["by-trades-per-day"],
  );

  const equityCard = document.getElementById("stats-equity");
  equityCard.innerHTML = '<p class="section-label">Equity Curve</p>';
  const equityHost = document.createElement("div");
  equityCard.appendChild(equityHost);
  mountLineChart(equityHost, data["equity-curve"].series);

  document.querySelectorAll(".bento-cell").forEach((c) => (c.style.opacity = "1"));
}

const initial = parseFilterFromUrl();
renderFilterBar(document.getElementById("stats-filter-bar"), initial, refresh);
refresh(initial);
