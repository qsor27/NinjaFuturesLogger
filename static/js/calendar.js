import {
  parseFilterFromUrl,
  filterToQueryString,
  renderFilterBar,
} from "./stats_filter.js";
import { mountCalendarHeatmap, mountLcHistogram } from "./stats_charts.js";

const ENDPOINTS = ["by-day", "by-week", "by-month"];

async function fetchAll(filter) {
  const qs = filterToQueryString(filter);
  const responses = await Promise.all(
    ENDPOINTS.map((name) => fetch(`/api/stats/${name}${qs}`).then((r) => r.json())),
  );
  return Object.fromEntries(ENDPOINTS.map((n, i) => [n, responses[i]]));
}

// "2026-W16" → "2026-04-13" (Monday of that ISO week)
function isoWeekToDate(bucket) {
  const [yearStr, weekStr] = bucket.split("-W");
  const year = parseInt(yearStr, 10);
  const week = parseInt(weekStr, 10);
  // Jan 4 is always in ISO week 1; find Monday of W1, then offset.
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const jan4Dow = jan4.getUTCDay() || 7; // convert Sun=0 to 7
  const w1Monday = new Date(jan4.getTime() - (jan4Dow - 1) * 86400000);
  const monday = new Date(w1Monday.getTime() + (week - 1) * 7 * 86400000);
  return monday.toISOString().slice(0, 10);
}

async function refresh(filter) {
  const data = await fetchAll(filter);

  mountCalendarHeatmap(document.getElementById("calendar-heatmap"), data["by-day"].buckets, {
    title: "Daily P&L Calendar",
  });

  const weekCard = document.getElementById("calendar-by-week");
  weekCard.innerHTML = '<p class="section-label">By Week</p>';
  const weekHost = document.createElement("div");
  weekCard.appendChild(weekHost);
  mountLcHistogram(weekHost, data["by-week"].buckets, isoWeekToDate);

  const monthCard = document.getElementById("calendar-by-month");
  monthCard.innerHTML = '<p class="section-label">By Month</p>';
  const monthHost = document.createElement("div");
  monthCard.appendChild(monthHost);
  // "2026-04" → "2026-04-01"
  mountLcHistogram(monthHost, data["by-month"].buckets, (b) => b + "-01");
}

const initial = parseFilterFromUrl();
renderFilterBar(document.getElementById("stats-filter-bar"), initial, refresh);
refresh(initial);
