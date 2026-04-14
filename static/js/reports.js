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

const ENDPOINTS = ["by-day", "equity-curve", "by-week", "by-month", "distribution"];

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
