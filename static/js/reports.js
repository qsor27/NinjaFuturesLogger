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
  mountLineChart(equityHost, data["equity-curve"].points);

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
  distCard.innerHTML = '<p class="section-label">P&L Distribution</p>';
  const distHost = document.createElement("div");
  distCard.appendChild(distHost);
  mountHistogramChart(distHost, data["distribution"].buckets, { kind: "distribution" });
}

const initial = parseFilterFromUrl();
renderFilterBar(document.getElementById("stats-filter-bar"), initial, refresh);
refresh(initial);
