// Shared fetch helpers. All API calls in the browsing UI go through these.
// Every URL is absolute-from-root; no relative paths. Transport only —
// formatting/escaping helpers live in format.js.

// Thrown by every helper on a non-2xx response. `body` is the parsed JSON
// error payload when the server sent one (e.g. {error: "out_of_reach"}),
// the raw text otherwise, or null for an empty body. Callers that branch on
// status codes (409 confirmations, 503 healthz) catch this and inspect
// .status / .body instead of keeping raw fetch calls.
export class HttpError extends Error {
  constructor(method, url, status, rawText, body) {
    super(`${method} ${url} failed: ${status} ${rawText}`);
    this.name = "HttpError";
    this.status = status;
    this.body = body;
  }
}

async function request(method, url, body) {
  const opts = { method, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(url, opts);
  const text = await resp.text();
  let parsed = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }
  if (!resp.ok) throw new HttpError(method, url, resp.status, text, parsed);
  return parsed; // null for 204 / empty bodies
}

export function fetchJSON(url) {
  return request("GET", url);
}

export function postJSON(url, body) {
  return request("POST", url, body);
}

export function putJSON(url, body) {
  return request("PUT", url, body);
}

export function patchJSON(url, body) {
  return request("PATCH", url, body);
}

export function deleteJSON(url) {
  return request("DELETE", url);
}

// Build a query string from an object, skipping null/empty values.
// Array values are serialized as repeated params (e.g. {account: ["A","B"]}
// -> "account=A&account=B"). Strings and numbers serialize as single values.
export function buildQuery(params) {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) {
      for (const v of value) {
        if (v === null || v === undefined || v === "") continue;
        usp.append(key, String(v));
      }
    } else {
      usp.set(key, String(value));
    }
  }
  const s = usp.toString();
  return s ? "?" + s : "";
}

// Format a unix-seconds timestamp in the configured display timezone.
// Reads `document.body.dataset.displayTz` (set by base.html from the server
// config) so every page renders times in the trader's exchange timezone
// instead of whatever the browser happens to be set to.
export function formatTime(unixSeconds) {
  if (unixSeconds === null || unixSeconds === undefined) return "—";
  const d = new Date(unixSeconds * 1000);
  const tz = document.body?.dataset?.displayTz || undefined;
  return d.toLocaleString(undefined, {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

// Format a dollars number with sign, two decimals, and a CSS class hint.
export function formatDollars(value) {
  if (value === null || value === undefined) return { text: "—", cls: "" };
  const fixed = value.toFixed(2);
  const sign = value >= 0 ? "" : "";
  return {
    text: `${sign}$${fixed}`,
    cls: value > 0 ? "pnl-pos" : value < 0 ? "pnl-neg" : "",
  };
}

// Safe text setter — always use this when the value came from user input.
export function setText(el, value) {
  el.textContent = value === null || value === undefined ? "" : String(value);
}
