import {
  parseFilterFromUrl,
  filterToQueryString,
  renderFilterBar,
} from "./stats_filter.js";
import {
  mountHistogramChart,
  mountLineChart,
} from "./stats_charts.js";

const ENDPOINTS = [
  "summary",
  "by-side",
  "equity-curve",
  "by-instrument",
  "by-day",
  "by-hour",
];

async function fetchAll(filter) {
  const qs = filterToQueryString(filter);
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

function renderSummary(container, summary) {
  container.innerHTML = `
    <p class="section-label">Summary</p>
    <p class="big-number ${summary.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(summary.total_pnl)}</p>
    <div class="summary-grid">
      <div><div class="stat-label">Trades</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Win Rate</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Profit Factor</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Avg Hold (min)</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Avg Win</div><div class="stat-value pnl-pos"></div></div>
      <div><div class="stat-label">Avg Loss</div><div class="stat-value pnl-neg"></div></div>
      <div><div class="stat-label">Largest Win</div><div class="stat-value pnl-pos"></div></div>
      <div><div class="stat-label">Largest Loss</div><div class="stat-value pnl-neg"></div></div>
      <div><div class="stat-label">Win Streak</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Loss Streak</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Avg Size</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Open</div><div class="stat-value"></div></div>
    </div>
  `;
  const values = container.querySelectorAll(".summary-grid .stat-value");
  values[0].textContent = String(summary.total_positions);
  values[1].textContent = fmtPercent(summary.win_rate);
  values[2].textContent = fmtNum(summary.profit_factor, 2);
  values[3].textContent = fmtNum(summary.avg_hold_minutes, 1);
  values[4].textContent = fmtMoney(summary.avg_win);
  values[5].textContent = fmtMoney(summary.avg_loss);
  values[6].textContent = fmtMoney(summary.largest_win);
  values[7].textContent = fmtMoney(summary.largest_loss);
  values[8].textContent = String(summary.longest_win_streak);
  values[9].textContent = String(summary.longest_loss_streak);
  values[10].textContent = fmtNum(summary.avg_position_size, 1);
  values[11].textContent = String(summary.open_positions);

  if (summary.skipped_no_multiplier > 0) {
    const warn = document.createElement("div");
    warn.className = "warning-row";
    warn.textContent = `${summary.skipped_no_multiplier} positions excluded — add their instruments to the multiplier registry.`;
    container.appendChild(warn);
  }
}

function renderBySide(container, breakdown) {
  container.innerHTML = `
    <p class="section-label">Long vs Short</p>
    <div class="summary-grid" style="grid-template-columns:1fr 1fr;">
      <div><div class="stat-label">Long</div>
        <div class="stat-value ${breakdown.long.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(breakdown.long.total_pnl)}</div>
        <div class="stat-label" style="margin-top:8px;">${breakdown.long.position_count} trades · ${fmtPercent(breakdown.long.win_rate)}</div>
      </div>
      <div><div class="stat-label">Short</div>
        <div class="stat-value ${breakdown.short.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(breakdown.short.total_pnl)}</div>
        <div class="stat-label" style="margin-top:8px;">${breakdown.short.position_count} trades · ${fmtPercent(breakdown.short.win_rate)}</div>
      </div>
    </div>
  `;
}

function renderInstrumentTable(container, breakdown) {
  if (!breakdown.rows.length) {
    container.innerHTML = '<p class="section-label">By Instrument</p><div class="empty-state">No data</div>';
    return;
  }
  const rowsHtml = breakdown.rows.map((r) => `
    <tr>
      <td>${r.instrument}</td>
      <td>${r.position_count}</td>
      <td class="${r.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(r.total_pnl)}</td>
      <td>${fmtPercent(r.win_rate)}</td>
    </tr>
  `).join("");
  container.innerHTML = `
    <p class="section-label">By Instrument</p>
    <table class="instrument-table">
      <thead><tr><th>Instr</th><th>Trades</th><th>P&amp;L</th><th>Win %</th></tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>
  `;
}

async function refresh(filter) {
  document.querySelectorAll(".bento-cell").forEach((c) => (c.style.opacity = "0.5"));
  const data = await fetchAll(filter);
  renderSummary(document.getElementById("stats-summary"), data["summary"]);
  renderBySide(document.getElementById("stats-by-side"), data["by-side"]);
  renderInstrumentTable(document.getElementById("stats-by-instrument"), data["by-instrument"]);

  const equityCard = document.getElementById("stats-equity");
  equityCard.innerHTML = '<p class="section-label">Equity Curve</p>';
  const equityHost = document.createElement("div");
  equityCard.appendChild(equityHost);
  mountLineChart(equityHost, data["equity-curve"].points);

  const dayCard = document.getElementById("stats-by-day");
  dayCard.innerHTML = '<p class="section-label">By Day</p>';
  const dayHost = document.createElement("div");
  dayCard.appendChild(dayHost);
  mountHistogramChart(dayHost, data["by-day"].buckets, { kind: "day" });

  const hourCard = document.getElementById("stats-by-hour");
  hourCard.innerHTML = `<p class="section-label">By Hour (${data["by-hour"].timezone})</p>`;
  const hourHost = document.createElement("div");
  hourCard.appendChild(hourHost);
  mountHistogramChart(hourHost, data["by-hour"].buckets, { kind: "hour" });

  document.querySelectorAll(".bento-cell").forEach((c) => (c.style.opacity = "1"));
}

const initial = parseFilterFromUrl();
renderFilterBar(document.getElementById("stats-filter-bar"), initial, refresh);
refresh(initial);
