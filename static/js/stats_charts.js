// Plan 15 — chart wrappers. Two real chart helpers delegate to the vendored
// Lightweight Charts global (loaded via <script src> in the page templates).
// The third (mountCalendarHeatmap) is hand-rolled CSS Grid.

const CHART_DEFAULTS = {
  layout: { background: { color: "#1e293b" }, textColor: "#94a3b8" },
  grid: { vertLines: { color: "#334155" }, horzLines: { color: "#334155" } },
  rightPriceScale: { borderColor: "#334155" },
  timeScale: { borderColor: "#334155", timeVisible: true, secondsVisible: false },
};

export function mountLineChart(container, points, opts = {}) {
  container.innerHTML = "";
  if (!points.length) {
    container.innerHTML = '<div class="empty-state">No data for this filter</div>';
    return null;
  }
  const wrap = document.createElement("div");
  wrap.className = "chart-container";
  container.appendChild(wrap);
  const chart = window.LightweightCharts.createChart(wrap, {
    ...CHART_DEFAULTS,
    width: wrap.clientWidth,
    height: wrap.clientHeight,
  });
  const series = chart.addLineSeries({
    color: opts.color || "#8b5cf6",
    lineWidth: 2,
  });
  series.setData(points.map((p) => ({ time: p.time, value: p.cumulative_pnl })));
  chart.timeScale().fitContent();
  new ResizeObserver(() => {
    chart.applyOptions({ width: wrap.clientWidth, height: wrap.clientHeight });
  }).observe(wrap);
  return chart;
}

export function mountHistogramChart(container, buckets, opts = {}) {
  container.innerHTML = "";
  if (!buckets.length) {
    container.innerHTML = '<div class="empty-state">No data for this filter</div>';
    return null;
  }
  const wrap = document.createElement("div");
  wrap.className = "chart-container";
  container.appendChild(wrap);
  const chart = window.LightweightCharts.createChart(wrap, {
    ...CHART_DEFAULTS,
    width: wrap.clientWidth,
    height: wrap.clientHeight,
    timeScale: {
      ...CHART_DEFAULTS.timeScale,
      timeVisible: opts.kind === "hour" ? false : true,
    },
  });
  const series = chart.addHistogramSeries({});
  // Convert each bucket into a Lightweight Charts time/value pair.
  // For day/week/month buckets, key is a date-ish string -> map to a synthetic
  // sequential int (Lightweight Charts accepts integer time values).
  // For hour buckets, key is 0..23.
  // For distribution buckets, key is the bucket index.
  const data = buckets.map((b, i) => {
    const value = b.total_pnl !== undefined ? b.total_pnl : b.count;
    return {
      time: i,
      value: value,
      color: value >= 0 ? "#10b981" : "#f43f5e",
    };
  });
  series.setData(data);
  chart.timeScale().fitContent();
  new ResizeObserver(() => {
    chart.applyOptions({ width: wrap.clientWidth, height: wrap.clientHeight });
  }).observe(wrap);
  return chart;
}

// ---- Calendar heatmap (hand-rolled, no chart library) -------------------

const SUNDAY_FIRST_HEADERS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function mountCalendarHeatmap(container, dailyBuckets, opts = {}) {
  container.innerHTML = "";
  const heading = document.createElement("p");
  heading.className = "section-label";
  heading.textContent = opts.title || "Daily P&L Calendar";
  container.appendChild(heading);

  if (!dailyBuckets.length) {
    container.innerHTML += '<div class="empty-state">No data for this filter</div>';
    return;
  }

  // Group buckets by month (YYYY-MM) and render one calendar per month.
  const byMonth = new Map();
  for (const b of dailyBuckets) {
    const month = b.bucket.slice(0, 7);
    if (!byMonth.has(month)) byMonth.set(month, []);
    byMonth.get(month).push(b);
  }
  for (const [month, days] of byMonth) {
    container.appendChild(_renderMonth(month, days));
  }
}

function _renderMonth(monthKey, days) {
  const wrap = document.createElement("div");
  wrap.style.marginBottom = "16px";

  const title = document.createElement("p");
  title.className = "section-label";
  title.textContent = monthKey;
  wrap.appendChild(title);

  const grid = document.createElement("div");
  grid.className = "calendar";

  for (const h of SUNDAY_FIRST_HEADERS) {
    const cell = document.createElement("div");
    cell.className = "cal-header";
    cell.textContent = h;
    grid.appendChild(cell);
  }

  const [year, month] = monthKey.split("-").map(Number);
  const firstOfMonth = new Date(Date.UTC(year, month - 1, 1));
  const startWeekday = firstOfMonth.getUTCDay(); // 0=Sun..6=Sat
  for (let i = 0; i < startWeekday; i++) {
    const blank = document.createElement("div");
    blank.className = "cal-day empty";
    grid.appendChild(blank);
  }

  const byDate = new Map(days.map((d) => [d.bucket, d]));
  const maxAbs = Math.max(
    1e-9,
    ...days.map((d) => Math.abs(d.total_pnl)),
  );
  const daysInMonth = new Date(year, month, 0).getDate();
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const bucket = byDate.get(dateStr);
    const cell = document.createElement("div");
    cell.className = "cal-day";
    if (!bucket || bucket.position_count === 0) {
      cell.classList.add("empty");
      cell.innerHTML = `<span class="day-num">${d}</span>`;
    } else {
      cell.classList.add(_levelClass(bucket.total_pnl, maxAbs));
      cell.innerHTML = `
        <span class="day-num">${d}</span>
        <span class="pnl ${bucket.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${_formatPnl(bucket.total_pnl)}</span>
        <span class="count">${bucket.position_count} trade${bucket.position_count === 1 ? "" : "s"}</span>
      `;
      cell.addEventListener("click", () => {
        window.location.href = `/positions?session_date=${dateStr}`;
      });
    }
    grid.appendChild(cell);
  }
  wrap.appendChild(grid);
  return wrap;
}

function _levelClass(pnl, maxAbs) {
  const frac = Math.abs(pnl) / maxAbs;
  if (pnl >= 0) {
    if (frac > 0.75) return "win-4";
    if (frac > 0.50) return "win-3";
    if (frac > 0.25) return "win-2";
    return "win-1";
  } else {
    if (frac > 0.66) return "loss-3";
    if (frac > 0.33) return "loss-2";
    return "loss-1";
  }
}

function _formatPnl(pnl) {
  const sign = pnl >= 0 ? "+" : "-";
  const abs = Math.abs(pnl);
  return `${sign}$${abs.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
