// Plan 15 — chart wrappers. Two real chart helpers delegate to the vendored
// Lightweight Charts global (loaded via <script src> in the page templates).
// The third (mountCalendarHeatmap) is hand-rolled CSS Grid.

const CHART_DEFAULTS = {
  layout: { background: { color: "#1e293b" }, textColor: "#94a3b8" },
  grid: { vertLines: { color: "#334155" }, horzLines: { color: "#334155" } },
  rightPriceScale: { borderColor: "#334155" },
  timeScale: { borderColor: "#334155", timeVisible: true, secondsVisible: false },
};

const LINE_COLOR_CYCLE = [
  "#8b5cf6", // purple (accent)
  "#14b8a6", // teal
  "#f59e0b", // amber
  "#ec4899", // pink
  "#6366f1", // indigo
  "#22d3ee", // cyan
];

// Multi-series line chart. `seriesList` is [{account, points: [...]}]; each
// points entry is {time, cumulative_pnl}. One LC line series per account
// with a color from LINE_COLOR_CYCLE, plus a legend chip row.
export function mountLineChart(container, seriesList, opts = {}) {
  container.innerHTML = "";
  const nonEmpty = (seriesList || []).filter((s) => s.points && s.points.length);
  if (!nonEmpty.length) {
    container.innerHTML = '<div class="empty-state">No data for this filter</div>';
    return null;
  }

  if (nonEmpty.length > 1) {
    const legend = document.createElement("div");
    legend.className = "chart-legend";
    nonEmpty.forEach((s, i) => {
      const chip = document.createElement("span");
      chip.className = "legend-chip";
      const swatch = document.createElement("span");
      swatch.className = "legend-swatch";
      swatch.style.background = LINE_COLOR_CYCLE[i % LINE_COLOR_CYCLE.length];
      chip.appendChild(swatch);
      const label = document.createElement("span");
      label.textContent = s.account;
      chip.appendChild(label);
      legend.appendChild(chip);
    });
    container.appendChild(legend);
  }

  const wrap = document.createElement("div");
  wrap.className = "chart-container";
  container.appendChild(wrap);
  const chart = window.LightweightCharts.createChart(wrap, {
    ...CHART_DEFAULTS,
    width: wrap.clientWidth,
    height: wrap.clientHeight,
  });
  nonEmpty.forEach((s, i) => {
    const lcSeries = chart.addLineSeries({
      color: opts.color || LINE_COLOR_CYCLE[i % LINE_COLOR_CYCLE.length],
      lineWidth: 2,
    });
    // Lightweight Charts requires strictly increasing time values. The API
    // now returns one point per session date (YYYY-MM-DD), so duplicates
    // cannot occur, but keep the guard for safety.
    const deduped = [];
    let lastTime = null;
    for (const p of s.points) {
      if (lastTime === p.time && deduped.length) {
        deduped[deduped.length - 1].value = p.cumulative_pnl;
      } else {
        deduped.push({ time: p.time, value: p.cumulative_pnl });
        lastTime = p.time;
      }
    }
    lcSeries.setData(deduped);
  });
  chart.timeScale().fitContent();
  new ResizeObserver(() => {
    chart.applyOptions({ width: wrap.clientWidth, height: wrap.clientHeight });
  }).observe(wrap);
  return chart;
}

// Hand-rolled CSS bar chart. Lightweight Charts' time-axis can't render
// category labels (day/week/month/hour/histogram-bucket), so we don't use it.
// See docs/superpowers/plans/2026-04-13-15-statistics.md — bug 2 fix.
export function mountHistogramChart(container, buckets, opts = {}) {
  container.innerHTML = "";
  if (!buckets.length) {
    container.innerHTML = '<div class="empty-state">No data for this filter</div>';
    return null;
  }

  const values = buckets.map((b) => (b.total_pnl !== undefined ? b.total_pnl : b.count));
  const hasNegative = values.some((v) => v < 0);
  const maxAbs = Math.max(1e-9, ...values.map(Math.abs));

  const kind = opts.kind || "";
  const wrap = document.createElement("div");
  wrap.className = "bar-chart" + (hasNegative ? " has-negative" : "") + (kind ? ` kind-${kind}` : "");
  container.appendChild(wrap);

  buckets.forEach((b, i) => {
    const value = values[i];
    const col = document.createElement("div");
    col.className = "bar-col";

    const label = _formatBucketLabel(b, kind, i);
    const valueStr = _formatBucketValue(value, kind);

    if (value === 0 && (b.position_count === 0 || b.count === 0)) {
      col.classList.add("bar-empty");
    } else {
      const fill = document.createElement("div");
      const heightPct = hasNegative
        ? (Math.abs(value) / maxAbs) * 50
        : (Math.abs(value) / maxAbs) * 100;
      fill.className = "bar-fill " + (value >= 0 ? "bar-pos" : "bar-neg");
      fill.style.height = `${heightPct}%`;
      col.appendChild(fill);

      // For distribution, show trade count just above the bar fill.
      if (kind === "distribution") {
        const topVal = document.createElement("div");
        topVal.className = "bar-top-value";
        topVal.textContent = value === 1 ? "1 trade" : `${value} trades`;
        topVal.style.bottom = `calc(${heightPct}% + 4px)`;
        col.appendChild(topVal);
      }
    }

    const labelEl = document.createElement("div");
    labelEl.className = "bar-label";
    labelEl.textContent = label;
    col.appendChild(labelEl);

    col.title = `${label}: ${valueStr}`;
    wrap.appendChild(col);
  });

  return null;
}

function _formatBucketLabel(b, kind, index) {
  if (kind === "hour") {
    const h = b.hour !== undefined ? b.hour : index;
    return `${String(h).padStart(2, "0")}:00`;
  }
  if (kind === "distribution") {
    return `${_formatMoneyCompact(b.bucket_min)}..${_formatMoneyCompact(b.bucket_max)}`;
  }
  return String(index);
}

function _formatBucketValue(value, kind) {
  if (kind === "distribution" || kind === "hour") {
    // These bars represent counts when viewed as a histogram; but hour also
    // carries total_pnl. Show whichever is non-zero meaningfully.
    return `${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  }
  return _formatPnl(value);
}

function _formatMoneyCompact(v) {
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(0)}`;
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
        window.location.href = `/positions?session_date_from=${dateStr}&session_date_to=${dateStr}`;
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

// LightweightCharts-based histogram for by-week and by-month on the Calendar
// page. `buckets` are TimeBucket objects ({bucket, position_count, total_pnl}).
// `toDateFn` converts the bucket key string to a "YYYY-MM-DD" date string.
export function mountLcHistogram(container, buckets, toDateFn) {
  container.innerHTML = "";
  const activeBuckets = (buckets || []).filter((b) => b.position_count > 0);
  if (!activeBuckets.length) {
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

  const series = chart.addHistogramSeries({
    priceFormat: { type: "price", precision: 0, minMove: 1 },
  });

  const data = activeBuckets
    .map((b) => ({
      time: toDateFn(b.bucket),
      value: b.total_pnl,
      color: b.total_pnl >= 0 ? "#22c55e" : "#f87171",
    }))
    .sort((a, b) => (a.time < b.time ? -1 : 1));

  series.setData(data);
  chart.timeScale().fitContent();

  new ResizeObserver(() => {
    chart.applyOptions({ width: wrap.clientWidth, height: wrap.clientHeight });
  }).observe(wrap);

  return chart;
}
