import {
  parseFilterFromUrl,
  filterToQueryString,
  renderFilterBar,
} from "./stats_filter.js";
import {
  mountCalendarHeatmap,
  mountHistogramChart,
  mountLineChart,
} from "./stats_charts.js";

const ENDPOINTS = ["by-day", "equity-curve", "by-week", "by-month", "distribution", "by-instrument", "summary"];

const fmtMoney = (v) => { if (v == null) return "—"; const s = v >= 0 ? "+" : "-"; return `${s}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`; };
const fmtPercent = (v) => v == null ? "—" : `${(v * 100).toFixed(1)}%`;
const fmtNum = (v, d = 1) => v == null ? "—" : Number(v).toFixed(d);

async function fetchAll(filter) {
  const qs = filterToQueryString(filter);
  const responses = await Promise.all(
    ENDPOINTS.map((name) => fetch(`/api/stats/${name}${qs}`).then((r) => r.json())),
  );
  return Object.fromEntries(ENDPOINTS.map((n, i) => [n, responses[i]]));
}

async function refresh(filter) {
  const data = await fetchAll(filter);

  mountCalendarHeatmap(
    document.getElementById("reports-calendar"),
    data["by-day"].buckets,
    { title: "Daily P&L Calendar" },
  );

  const equityCard = document.getElementById("reports-equity");
  equityCard.innerHTML = '<p class="section-label">Cumulative Equity</p>';
  const equityHost = document.createElement("div");
  equityCard.appendChild(equityHost);
  mountLineChart(equityHost, data["equity-curve"].series);

  const weekCard = document.getElementById("reports-by-week");
  weekCard.innerHTML = '<p class="section-label">By Week</p>';
  const weekHost = document.createElement("div");
  weekCard.appendChild(weekHost);
  mountHistogramChart(weekHost, data["by-week"].buckets, { kind: "week" });

  const monthCard = document.getElementById("reports-by-month");
  monthCard.innerHTML = '<p class="section-label">By Month</p>';
  const monthHost = document.createElement("div");
  monthCard.appendChild(monthHost);
  mountHistogramChart(monthHost, data["by-month"].buckets, { kind: "month" });

  const distCard = document.getElementById("reports-distribution");
  distCard.innerHTML = '<p class="section-label">P&L by Trades per Day</p>';
  const distHost = document.createElement("div");
  distCard.appendChild(distHost);
  mountHistogramChart(distHost, _tradeCountBuckets(data["by-day"].buckets), { kind: "day-count" });

  const instrCard = document.getElementById("reports-by-instrument");
  const instrRows = (data["by-instrument"].rows || []).map((r) => `
    <tr>
      <td>${r.instrument}</td>
      <td>${r.position_count}</td>
      <td class="${r.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(r.total_pnl)}</td>
      <td>${fmtPercent(r.win_rate)}</td>
      <td class="${r.avg_pnl_per_position >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(r.avg_pnl_per_position)}</td>
    </tr>`).join("");
  instrCard.innerHTML = `<p class="section-label">By Instrument</p>
    <table class="instrument-table">
      <thead><tr><th>Instr</th><th>Trades</th><th>P&amp;L</th><th>Win %</th><th>Avg P&amp;L</th></tr></thead>
      <tbody>${instrRows}</tbody>
    </table>`;

  const s = data["summary"];
  const summCard = document.getElementById("reports-summary");
  summCard.innerHTML = `<p class="section-label">Performance Summary</p>
    <div class="summary-grid">
      <div><div class="stat-label">Trades</div><div class="stat-value">${s.total_positions}</div></div>
      <div><div class="stat-label">Win Rate</div><div class="stat-value">${fmtPercent(s.win_rate)}</div></div>
      <div><div class="stat-label">Profit Factor</div><div class="stat-value">${fmtNum(s.profit_factor, 2)}</div></div>
      <div><div class="stat-label">Total P&amp;L</div><div class="stat-value ${s.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(s.total_pnl)}</div></div>
      <div><div class="stat-label">Avg Win</div><div class="stat-value pnl-pos">${fmtMoney(s.avg_win)}</div></div>
      <div><div class="stat-label">Avg Loss</div><div class="stat-value pnl-neg">${fmtMoney(s.avg_loss)}</div></div>
      <div><div class="stat-label">Largest Win</div><div class="stat-value pnl-pos">${fmtMoney(s.largest_win)}</div></div>
      <div><div class="stat-label">Largest Loss</div><div class="stat-value pnl-neg">${fmtMoney(s.largest_loss)}</div></div>
    </div>`;
}

// Group by-day data by trades-per-day count. Each bucket gets the sum P&L
// across all days in the selection that had exactly that many trades.
function _tradeCountBuckets(byDayBuckets) {
  const map = new Map();
  for (const b of byDayBuckets) {
    if (b.position_count === 0) continue;
    const k = b.position_count;
    if (!map.has(k)) map.set(k, { trades_per_day: k, total_pnl: 0, days: 0 });
    const entry = map.get(k);
    entry.total_pnl += b.total_pnl;
    entry.days += 1;
  }
  return [...map.values()].sort((a, b) => a.trades_per_day - b.trades_per_day);
}

const initial = parseFilterFromUrl();
renderFilterBar(document.getElementById("stats-filter-bar"), initial, refresh);
refresh(initial);
