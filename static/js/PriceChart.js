// PriceChart.js — the one chart implementation in the app.
//
// Plan 13 load-bearing rules:
//   1. Exactly one chart implementation. This file. No SimpleChart.js, no
//      ChartComponentManager, no alternates.
//   2. The chart endpoint never fetches. The chart calls /api/chart/...
//      (read-only). If the response is empty the user sees the no-data
//      placeholder and a Fetch data now button that triggers an explicit
//      fetch via /api/chart/{instrument}/fetch + /api/ohlc/jobs/{job_id}
//      polling.
//   4. No auto-fallback. If the user's selected timeframe has no data, show
//      the no-data placeholder. Do NOT auto-switch to a "best" timeframe.
//
// Pure helpers are exported at the top of the file. They are intentionally
// free of DOM, LightweightCharts, and fetch references so they remain
// testable in principle (Plan 13 ships no JS test runner; a future plan can
// add one without rewriting).

import { fetchJSON, postJSON } from "./api.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const POLL_INTERVAL_MS = 2000;
export const POLL_TIMEOUT_MS = 120000;

export const CANONICAL_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];

const TIMEFRAME_SECONDS = {
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "1h": 3600,
  "4h": 14400,
  "1d": 86400,
};

const COLORS = {
  background: "#1a1a1a",
  grid: "#333",
  text: "#e5e5e5",
  upCandle: "#4CAF50",
  downCandle: "#F44336",
  buyMarker: "#4CAF50",
  sellMarker: "#F44336",
  flash: "#FFD700",
};

const FETCH_BUFFER_BARS = 200; // request this many bars on each side of entry

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function timeframeSeconds(tf) {
  const s = TIMEFRAME_SECONDS[tf];
  if (!s) throw new Error(`unknown timeframe: ${tf}`);
  return s;
}

// Compute the (start, end) unix-second window to request from the chart API.
// We center on entry_time and request enough bars on each side to comfortably
// fill the visible viewport once it's measured. The actual visible range is
// applied later via timeScale().setVisibleRange — this is just the data
// window. Bars outside the visible range are still loaded and panable.
export function computeFetchRange(entryTime, timeframe, bufferBars = FETCH_BUFFER_BARS) {
  const span = timeframeSeconds(timeframe) * bufferBars;
  return { start: entryTime - span, end: entryTime + span };
}

// Compute the visible-range (start, end) in unix seconds, centered on
// entry_time, for a chart of the given pixel width and a given bar pixel
// spacing. AC 7: "as many bars as fit on screen, centered on entry_time".
export function computeVisibleRange(entryTime, timeframe, pixelWidth, barSpacingPx) {
  const barCount = Math.max(10, Math.floor(pixelWidth / Math.max(1, barSpacingPx)));
  const half = Math.floor(barCount / 2);
  const stride = timeframeSeconds(timeframe);
  return { start: entryTime - half * stride, end: entryTime + half * stride };
}

// Pick the initial timeframe per AC 10. The configured default wins if it is
// available; otherwise the first available timeframe in canonical order.
// Returns null if no timeframe is available at all (caller renders no-data).
export function pickInitialTimeframe(availableSet, configured) {
  if (availableSet.has(configured)) return configured;
  for (const tf of CANONICAL_TIMEFRAMES) {
    if (availableSet.has(tf)) return tf;
  }
  return null;
}

// Convert API marker objects (from /api/positions/.../markers) into
// LightweightCharts createSeriesMarkers() input shape.
export function buildMarkersFromApi(apiMarkers) {
  return apiMarkers.map((m) => ({
    time: m.time,
    position: m.side === "Buy" ? "belowBar" : "aboveBar",
    color: m.side === "Buy" ? COLORS.buyMarker : COLORS.sellMarker,
    shape: m.side === "Buy" ? "arrowUp" : "arrowDown",
    text: "",
    id: m.label,
  }));
}

// Build the price-line definitions per AC 14. One dashed line per execution
// (colored by side) plus one solid thicker line for the position's average
// entry price (colored by long/short side).
export function buildPriceLines(executions, avgEntryPrice, positionSide) {
  const dashed = executions.map((e) => ({
    price: e.price,
    color: e.side === "Buy" ? COLORS.buyMarker : COLORS.sellMarker,
    lineStyle: 2, // LightweightCharts.LineStyle.Dashed
    lineWidth: 1,
    axisLabelVisible: true,
    title: `${e.side} ${e.quantity}`,
  }));
  const avg = {
    price: avgEntryPrice,
    color: positionSide === "Long" ? COLORS.buyMarker : COLORS.sellMarker,
    lineStyle: 0, // LightweightCharts.LineStyle.Solid
    lineWidth: 2,
    axisLabelVisible: true,
    title: `avg ${avgEntryPrice.toFixed(2)}`,
  };
  return [...dashed, avg];
}

// Decide what state to render after a chart-data fetch. Inputs are the bars
// array returned by GET /api/chart/{instrument} and the per-source breaker
// snapshots from GET /api/ohlc/sources. Returns one of: 'ok', 'no-data',
// 'delayed'. The 'delayed' state is "we have *some* bars but every source
// is currently down" — the user should see the bars but also see a banner.
export function summarizeFetchResult(bars, sourceSnapshots) {
  const allOpen =
    Array.isArray(sourceSnapshots) &&
    sourceSnapshots.length > 0 &&
    sourceSnapshots.every((s) => s.state === "open");
  if (bars.length === 0) {
    return allOpen ? "delayed" : "no-data";
  }
  return allOpen ? "delayed" : "ok";
}

// Polling delay schedule for fetch-job polling. Returns POLL_INTERVAL_MS
// while elapsed < POLL_TIMEOUT_MS, otherwise null (caller stops polling).
export function nextPollDelay(elapsedMs) {
  if (elapsedMs >= POLL_TIMEOUT_MS) return null;
  return POLL_INTERVAL_MS;
}

// Timezone helper — reads `document.body.dataset.displayTz` (set by base.html).
// Empty string = use the browser's local timezone.
function _displayTz() {
  return (typeof document !== "undefined" && document.body?.dataset?.displayTz) || undefined;
}

// Format a unix-seconds timestamp as "YYYY-MM-DD HH:mm" in the display tz.
// Used for the chart crosshair overlay and the timeScale time formatter.
function _formatChartDateTime(unixSeconds) {
  const parts = new Intl.DateTimeFormat(undefined, {
    timeZone: _displayTz(),
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(unixSeconds * 1000));
  const g = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return `${g.year}-${g.month}-${g.day} ${g.hour}:${g.minute}`;
}

// Tick mark formatter for TradingView Lightweight Charts timeScale. The
// library calls this for every visible tick with a tickMarkType enum:
// 0=Year 1=Month 2=DayOfMonth 3=Time 4=TimeWithSeconds. Return a short label
// in the display tz for each bucket.
function _formatTickMark(unixSeconds, tickMarkType) {
  const d = new Date(unixSeconds * 1000);
  const tz = _displayTz();
  if (tickMarkType === 0) {
    return new Intl.DateTimeFormat(undefined, { timeZone: tz, year: "numeric" }).format(d);
  }
  if (tickMarkType === 1) {
    return new Intl.DateTimeFormat(undefined, { timeZone: tz, month: "short" }).format(d);
  }
  if (tickMarkType === 2) {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: tz,
      month: "short",
      day: "2-digit",
    }).format(d);
  }
  const opts = {
    timeZone: tz,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  };
  if (tickMarkType === 4) opts.second = "2-digit";
  return new Intl.DateTimeFormat(undefined, opts).format(d);
}

// Format the OHLC overlay box (AC 15). Returns a string with newlines.
export function formatOhlcOverlay(bar) {
  if (!bar) return "";
  const change = bar.close - bar.open;
  const pct = bar.open !== 0 ? (change / bar.open) * 100 : 0;
  const sign = change >= 0 ? "+" : "";
  const time = _formatChartDateTime(bar.time);
  return [
    time,
    `O ${bar.open.toFixed(2)}`,
    `H ${bar.high.toFixed(2)}`,
    `L ${bar.low.toFixed(2)}`,
    `C ${bar.close.toFixed(2)}`,
    `V ${bar.volume}`,
    `${sign}${change.toFixed(2)} (${sign}${pct.toFixed(2)}%)`,
  ].join("\n");
}

// ---------------------------------------------------------------------------
// PriceChart class
// ---------------------------------------------------------------------------

export class PriceChart {
  static async init({ container, account, instrument, entryExecutionId }) {
    const chart = new PriceChart({ container, account, instrument, entryExecutionId });
    await chart._boot();
    return chart;
  }

  constructor({ container, account, instrument, entryExecutionId }) {
    this.container = container;
    this.account = account;
    this.instrument = instrument;
    this.entryExecutionId = entryExecutionId;

    this.position = null;
    this.markers = [];
    this.executions = [];
    this.timeframe = null;
    this.volumeVisible = true;
    this.availableTimeframes = new Set();
    this.defaultTimeframe = "1m";

    this.state = "loading";
    this.abortCtrl = null;
    this.lwChart = null;
    this.candleSeries = null;
    this.volumeSeries = null;
    this.priceLines = [];
    this.lwMarkers = null;
    this.resizeObserver = null;

    this._onTableRowClick = this._onTableRowClick.bind(this);
  }

  async _boot() {
    this._renderShell();
    document.addEventListener("executions-table:row-clicked", this._onTableRowClick);
    try {
      // Fetch the position detail, executions, available timeframes, and
      // markers in parallel. None of these calls touch OHLC.
      const [detail, execs, tfs, markers] = await Promise.all([
        fetchJSON(this._detailUrl()),
        fetchJSON(this._executionsUrl()),
        fetchJSON(this._timeframesUrl()),
        fetchJSON(this._markersUrl()),
      ]);
      this.position = detail.position;
      this.executions = execs.executions;
      this.markers = markers.markers;
      this.availableTimeframes = new Set(
        tfs.timeframes.filter((t) => t.available).map((t) => t.timeframe),
      );
      this.defaultTimeframe = tfs.default_timeframe;
      this.volumeVisible = tfs.volume_visible_default ?? true;

      this.timeframe = pickInitialTimeframe(this.availableTimeframes, this.defaultTimeframe);
      this._renderControls();
      if (this.timeframe === null) {
        const tf = this.defaultTimeframe;
        const { start, end } = computeFetchRange(this.position.entry_time, tf);
        this._renderPlaceholder({
          message: `No chart data available for this position.`,
          ctaLabel: "Fetch data now",
          onCta: () => this._fetchOnDemand(start, end),
        });
        this._setState("no-data");
        return;
      }
      await this._loadBars();
    } catch (e) {
      this._setError(e);
    }
  }

  _detailUrl() {
    return `/api/positions/${encodeURIComponent(this.account)}/${encodeURIComponent(this.instrument)}/${encodeURIComponent(this.entryExecutionId)}`;
  }
  _executionsUrl() {
    return `${this._detailUrl()}/executions`;
  }
  _markersUrl() {
    return `${this._detailUrl()}/markers`;
  }
  _timeframesUrl() {
    return `/api/chart/${encodeURIComponent(this.instrument)}/timeframes-available`;
  }
  _barsUrl(timeframe, start, end) {
    const qs = new URLSearchParams({
      timeframe,
      start: String(start),
      end: String(end),
    }).toString();
    return `/api/chart/${encodeURIComponent(this.instrument)}?${qs}`;
  }
  _sourcesUrl() {
    return "/api/ohlc/sources";
  }
  _fetchJobUrl() {
    return `/api/chart/${encodeURIComponent(this.instrument)}/fetch`;
  }
  _jobUrl(jobId) {
    return `/api/ohlc/jobs/${encodeURIComponent(jobId)}`;
  }

  _renderShell() {
    this.container.innerHTML = "";
    this.container.classList.add("price-chart");
    this.container.style.background = COLORS.background;
    this.container.style.color = COLORS.text;
    this.container.style.padding = "8px";

    this.headerEl = document.createElement("div");
    this.headerEl.className = "price-chart-header";
    this.headerEl.style.display = "flex";
    this.headerEl.style.alignItems = "center";
    this.headerEl.style.gap = "12px";
    this.headerEl.style.marginBottom = "6px";

    this.titleEl = document.createElement("strong");
    this.titleEl.textContent = `${this.instrument} Price Chart`;

    this.timeframeBarEl = document.createElement("div");
    this.timeframeBarEl.className = "price-chart-timeframes";

    this.volumeBtnEl = document.createElement("button");
    this.volumeBtnEl.type = "button";
    this.volumeBtnEl.textContent = "Volume: on";
    this.volumeBtnEl.addEventListener("click", () => this._toggleVolume());

    this.headerEl.appendChild(this.titleEl);
    this.headerEl.appendChild(this.timeframeBarEl);
    this.headerEl.appendChild(this.volumeBtnEl);
    this.container.appendChild(this.headerEl);

    this.canvasEl = document.createElement("div");
    this.canvasEl.className = "price-chart-canvas";
    this.canvasEl.style.position = "relative";
    this.canvasEl.style.height = "420px";
    this.canvasEl.style.width = "100%";
    this.container.appendChild(this.canvasEl);

    this.overlayEl = document.createElement("div");
    this.overlayEl.className = "price-chart-overlay";
    this.overlayEl.style.position = "absolute";
    this.overlayEl.style.top = "8px";
    this.overlayEl.style.right = "8px";
    this.overlayEl.style.padding = "6px 8px";
    this.overlayEl.style.background = "rgba(0,0,0,0.6)";
    this.overlayEl.style.color = COLORS.text;
    this.overlayEl.style.font = "12px monospace";
    this.overlayEl.style.whiteSpace = "pre";
    this.overlayEl.style.pointerEvents = "none";
    this.overlayEl.style.zIndex = "3"; // LWC canvases use z-index 2; must be higher
    this.overlayEl.style.display = "none";
    this.canvasEl.appendChild(this.overlayEl);

    this.bannerEl = document.createElement("div");
    this.bannerEl.className = "price-chart-banner";
    this.bannerEl.style.position = "absolute";
    this.bannerEl.style.top = "8px";
    this.bannerEl.style.left = "8px";
    this.bannerEl.style.padding = "6px 8px";
    this.bannerEl.style.background = "#7a4a00";
    this.bannerEl.style.color = "#fff";
    this.bannerEl.style.font = "12px sans-serif";
    this.bannerEl.style.display = "none";
    this.canvasEl.appendChild(this.bannerEl);

    this.loadingEl = document.createElement("div");
    this.loadingEl.className = "price-chart-loading";
    this.loadingEl.style.position = "absolute";
    this.loadingEl.style.inset = "0";
    this.loadingEl.style.display = "flex";
    this.loadingEl.style.alignItems = "center";
    this.loadingEl.style.justifyContent = "center";
    this.loadingEl.style.background = "rgba(0,0,0,0.4)";
    this.loadingEl.style.color = COLORS.text;
    this.loadingEl.textContent = "Loading…";
    this.canvasEl.appendChild(this.loadingEl);

    this.placeholderEl = document.createElement("div");
    this.placeholderEl.className = "price-chart-placeholder";
    this.placeholderEl.style.position = "absolute";
    this.placeholderEl.style.inset = "0";
    this.placeholderEl.style.display = "none";
    this.placeholderEl.style.flexDirection = "column";
    this.placeholderEl.style.alignItems = "center";
    this.placeholderEl.style.justifyContent = "center";
    this.placeholderEl.style.gap = "8px";
    this.placeholderEl.style.background = "rgba(0,0,0,0.5)";
    this.canvasEl.appendChild(this.placeholderEl);
  }

  _renderControls() {
    this.timeframeBarEl.innerHTML = "";
    for (const tf of CANONICAL_TIMEFRAMES) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = tf;
      const available = this.availableTimeframes.has(tf);
      btn.disabled = !available;
      if (!available) btn.style.opacity = "0.4";
      if (tf === this.timeframe) btn.style.fontWeight = "bold";
      btn.addEventListener("click", () => this._switchTimeframe(tf));
      this.timeframeBarEl.appendChild(btn);
    }
    this.volumeBtnEl.textContent = `Volume: ${this.volumeVisible ? "on" : "off"}`;
  }

  async _loadBars() {
    if (this.abortCtrl) this.abortCtrl.abort();
    this.abortCtrl = new AbortController();
    const ctrl = this.abortCtrl;

    this._setState("loading");

    const { start, end } = computeFetchRange(this.position.entry_time, this.timeframe);

    let bars, sources;
    try {
      [bars, sources] = await Promise.all([
        this._fetchBars(this.timeframe, start, end, ctrl.signal),
        fetchJSON(this._sourcesUrl()),
      ]);
    } catch (e) {
      if (ctrl.signal.aborted) return;
      this._setError(e);
      return;
    }
    if (ctrl.signal.aborted) return;

    const next = summarizeFetchResult(bars, sources.sources);
    if (next === "no-data") {
      this._renderPlaceholder({
        message: `No ${this.timeframe} data for this range.`,
        ctaLabel: "Fetch data now",
        onCta: () => this._fetchOnDemand(start, end),
      });
      this._setState("no-data");
      return;
    }
    this._renderChart(bars);
    if (next === "delayed") {
      this.bannerEl.textContent = "Chart data is currently delayed";
      this.bannerEl.style.display = "block";
    } else {
      this.bannerEl.style.display = "none";
    }
    this._setState(next);
  }

  async _fetchBars(timeframe, start, end, signal) {
    const url = this._barsUrl(timeframe, start, end);
    const resp = await fetch(url, {
      headers: { Accept: "application/json" },
      signal,
    });
    if (!resp.ok) throw new Error(`GET ${url} failed: ${resp.status}`);
    const body = await resp.json();
    return body.bars;
  }

  _renderChart(bars) {
    this._teardownChart();
    const lc = window.LightweightCharts;
    if (!lc) {
      this._setError(new Error("LightweightCharts global not loaded"));
      return;
    }
    this.lwChart = lc.createChart(this.canvasEl, {
      layout: {
        background: { type: "solid", color: COLORS.background },
        textColor: COLORS.text,
      },
      grid: {
        vertLines: { color: COLORS.grid },
        horzLines: { color: COLORS.grid },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: _formatTickMark,
      },
      localization: {
        timeFormatter: _formatChartDateTime,
      },
      rightPriceScale: {
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      crosshair: {
        mode: 1, // magnet
      },
      autoSize: true,
    });

    this.candleSeries = this.lwChart.addCandlestickSeries({
      upColor: COLORS.upCandle,
      downColor: COLORS.downCandle,
      wickUpColor: COLORS.upCandle,
      wickDownColor: COLORS.downCandle,
      borderVisible: false,
    });
    this.candleSeries.setData(
      bars.map((b) => ({
        time: b.time,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );

    if (this.volumeVisible) {
      this._addVolumeSeries(bars);
    }

    // Markers
    const lwMarkers = buildMarkersFromApi(this.markers);
    this.candleSeries.setMarkers(lwMarkers);

    // Price lines
    const avg = this.position.entry_price;
    for (const line of buildPriceLines(this.executions, avg, this.position.side)) {
      this.priceLines.push(this.candleSeries.createPriceLine(line));
    }

    // Visible range: as many bars as fit on screen, centered on entry_time.
    // setVisibleRange throws on an empty series ("Value is null"), so only
    // apply it when there are bars to range over. Empty-bar path is reached
    // via the "delayed" state when all OHLC sources are open.
    if (bars.length > 0) {
      const width = this.canvasEl.clientWidth || 800;
      const visible = computeVisibleRange(this.position.entry_time, this.timeframe, width, 8);
      this.lwChart.timeScale().setVisibleRange({
        from: visible.start,
        to: visible.end,
      });
    }

    // Crosshair OHLC overlay (AC 15)
    this.lwChart.subscribeCrosshairMove((param) => {
      if (!param || !param.time || !param.seriesData) {
        this.overlayEl.style.display = "none";
        return;
      }
      const data = param.seriesData.get(this.candleSeries);
      if (!data) {
        this.overlayEl.style.display = "none";
        return;
      }
      const matching = bars.find((b) => b.time === data.time);
      this.overlayEl.textContent = formatOhlcOverlay({ ...data, volume: matching?.volume ?? 0 });
      this.overlayEl.style.display = "block";
    });

    // Marker click → custom event for the executions table (AC 16)
    this.canvasEl.addEventListener("click", (ev) => {
      const param = this.lwChart && this.lwChart.timeScale && this._lastClickHit;
      // Lightweight Charts does not expose marker hit-tests directly. We
      // emulate it by mapping the click x-coordinate to the nearest marker
      // by time and dispatching the custom event.
      const rect = this.canvasEl.getBoundingClientRect();
      const xTime = this.lwChart.timeScale().coordinateToTime(ev.clientX - rect.left);
      if (xTime == null) return;
      const m = this._nearestMarker(xTime);
      if (!m) return;
      document.dispatchEvent(
        new CustomEvent("chart:execution-clicked", { detail: { executionId: m.label } }),
      );
    });

    // ResizeObserver re-applies the visible range so the entry stays centered.
    this.resizeObserver = new ResizeObserver(() => {
      if (!this.lwChart) return;
      const w = this.canvasEl.clientWidth || 800;
      const v = computeVisibleRange(this.position.entry_time, this.timeframe, w, 8);
      this.lwChart.timeScale().setVisibleRange({ from: v.start, to: v.end });
    });
    this.resizeObserver.observe(this.canvasEl);
  }

  _addVolumeSeries(bars) {
    const lc = window.LightweightCharts;
    this.volumeSeries = this.lwChart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      color: "#888",
    });
    this.lwChart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    this.volumeSeries.setData(
      bars.map((b) => ({
        time: b.time,
        value: b.volume,
        color: b.close >= b.open ? COLORS.upCandle : COLORS.downCandle,
      })),
    );
  }

  _nearestMarker(time) {
    let best = null;
    let bestDelta = Infinity;
    for (const m of this.markers) {
      const d = Math.abs(m.time - time);
      if (d < bestDelta) {
        bestDelta = d;
        best = m;
      }
    }
    // 60s tolerance for click hit-testing
    return bestDelta <= 60 ? best : null;
  }

  _onTableRowClick(ev) {
    const id = ev?.detail?.executionId;
    if (!id || !this.lwChart) return;
    const m = this.markers.find((x) => x.label === id);
    if (!m) return;
    const stride = timeframeSeconds(this.timeframe);
    const half = 25; // ~50 bars wide
    this.lwChart.timeScale().setVisibleRange({
      from: m.time - half * stride,
      to: m.time + half * stride,
    });
    this._flashMarker(m);
  }

  _flashMarker(marker) {
    // We re-set markers with a gold-colored override on the matching one,
    // then revert after 2 seconds.
    const flashed = buildMarkersFromApi(this.markers).map((lwm) =>
      lwm.id === marker.label ? { ...lwm, color: COLORS.flash } : lwm,
    );
    this.candleSeries.setMarkers(flashed);
    setTimeout(() => {
      if (this.candleSeries) {
        this.candleSeries.setMarkers(buildMarkersFromApi(this.markers));
      }
    }, 2000);
  }

  _toggleVolume() {
    this.volumeVisible = !this.volumeVisible;
    this.volumeBtnEl.textContent = `Volume: ${this.volumeVisible ? "on" : "off"}`;
    if (this.state === "ok" || this.state === "delayed") {
      // Re-render with current bars; we re-fetch is unnecessary because the
      // toggle does not change the data window. We simply teardown + rebuild.
      this._loadBars();
    }
  }

  async _switchTimeframe(tf) {
    if (tf === this.timeframe) return;
    if (!this.availableTimeframes.has(tf)) return;
    this.timeframe = tf;
    this._renderControls();
    await this._loadBars();
  }

  async _fetchOnDemand(start, end) {
    this._setState("loading");
    try {
      const job = await postJSON(this._fetchJobUrl(), {
        timeframe: this.timeframe,
        start,
        end,
      });
      const ok = await this._pollJob(job.job_id);
      if (!ok) {
        this._renderPlaceholder({
          message: "Fetch did not complete. Try again later.",
          ctaLabel: "Retry",
          onCta: () => this._fetchOnDemand(start, end),
        });
        this._setState("no-data");
        return;
      }
      await this._loadBars();
    } catch (e) {
      this._setError(e);
    }
  }

  async _pollJob(jobId) {
    const startedAt = Date.now();
    while (true) {
      const elapsed = Date.now() - startedAt;
      const delay = nextPollDelay(elapsed);
      if (delay === null) return false;
      await new Promise((r) => setTimeout(r, delay));
      let snap;
      try {
        snap = await fetchJSON(this._jobUrl(jobId));
      } catch (_e) {
        // transient error; keep polling within the timeout window
        continue;
      }
      if (snap.state === "done") return true;
      if (snap.state === "failed") return false;
    }
  }

  _renderPlaceholder({ message, ctaLabel, onCta }) {
    this.placeholderEl.innerHTML = "";
    const msg = document.createElement("div");
    msg.textContent = message;
    msg.style.color = COLORS.text;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = ctaLabel;
    btn.addEventListener("click", onCta);
    this.placeholderEl.appendChild(msg);
    this.placeholderEl.appendChild(btn);
    this.placeholderEl.style.display = "flex";
  }

  _setError(error) {
    this._teardownChart();
    this.placeholderEl.innerHTML = "";
    const msg = document.createElement("div");
    msg.textContent = `Chart error: ${error?.message || error}`;
    msg.style.color = "#ff8080";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Retry";
    btn.addEventListener("click", () => this._loadBars());
    this.placeholderEl.appendChild(msg);
    this.placeholderEl.appendChild(btn);
    this.placeholderEl.style.display = "flex";
    this._setState("error");
  }

  _setState(next) {
    this.state = next;
    this.loadingEl.style.display = next === "loading" ? "flex" : "none";
    if (next !== "no-data" && next !== "error") {
      this.placeholderEl.style.display = "none";
    }
  }

  _teardownChart() {
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
      this.resizeObserver = null;
    }
    if (this.lwChart) {
      this.lwChart.remove();
      this.lwChart = null;
      this.candleSeries = null;
      this.volumeSeries = null;
      this.priceLines = [];
    }
  }
}
