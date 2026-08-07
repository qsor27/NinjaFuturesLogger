// static/js/format.js — shared formatting + escaping helpers.
// DOM access is limited to reading document.body.dataset.displayTz and the
// setText setter; no fetch, no chart library. Every page module imports its
// formatters from here — do not re-create local copies.

// HTML-escape for the innerHTML-building pages. Also escapes double quotes so
// the result is safe inside double-quoted attribute values (data-inst="...").
export function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Safe text setter — always use this when the value came from user input.
export function setText(el, value) {
  el.textContent = value === null || value === undefined ? "" : String(value);
}

// Browser-local IANA timezone, or null if the Intl API misbehaves.
export function browserTz() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

// Configured display timezone (base.html sets body[data-display-tz] from the
// server config). undefined = let toLocaleString use the browser tz.
export function displayTz() {
  return (typeof document !== "undefined" && document.body?.dataset?.displayTz) || undefined;
}

// Full date-time in the display timezone. "—" for null/undefined.
export function formatTime(unixSeconds) {
  if (unixSeconds === null || unixSeconds === undefined) return "—";
  return new Date(unixSeconds * 1000).toLocaleString(undefined, {
    timeZone: displayTz(),
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

// HH:MM:SS in the display timezone. "—" for null/undefined.
export function formatTimeOfDay(unixSeconds) {
  if (unixSeconds === null || unixSeconds === undefined) return "—";
  return new Date(unixSeconds * 1000).toLocaleTimeString(undefined, {
    timeZone: displayTz(),
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

// The one money formatter. ASCII "-" always. signed=true prefixes "+" on
// positive values (P&L style); signed=false omits the "+" (plain amounts).
export function fmtMoney(v, { decimals = 0, signed = true } = {}) {
  if (v === null || v === undefined) return "—";
  const sign = v < 0 ? "-" : signed ? "+" : "";
  const abs = Math.abs(v).toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return `${sign}$${abs}`;
}

// The one P&L CSS-class helper. Strict: exactly zero is unstyled.
export function pnlClass(v) {
  if (v === null || v === undefined) return "";
  if (v > 0) return "pnl-pos";
  if (v < 0) return "pnl-neg";
  return "";
}

// "1h 2m 3s" (leading zero units dropped, seconds always shown).
export function formatDuration(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return [h && `${h}h`, m && `${m}m`, `${s}s`].filter(Boolean).join(" ");
}

// <input type="date"> value helpers (UTC-based, matching the imports page).
export function epochToDateInput(ts) {
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

export function dateInputToEpoch(s) {
  return Math.floor(new Date(s).getTime() / 1000);
}
