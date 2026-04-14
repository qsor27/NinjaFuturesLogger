// Shared fetch helpers. All API calls in the browsing UI go through these.
// Every URL is absolute-from-root; no relative paths.

export async function fetchJSON(url) {
  const resp = await fetch(url, { headers: { Accept: "application/json" } });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`GET ${url} failed: ${resp.status} ${text}`);
  }
  return await resp.json();
}

export async function patchJSON(url, body) {
  const resp = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`PATCH ${url} failed: ${resp.status} ${text}`);
  }
  return await resp.json();
}

export async function postJSON(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`POST ${url} failed: ${resp.status} ${text}`);
  }
  return await resp.json();
}

export async function deleteJSON(url) {
  const resp = await fetch(url, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`DELETE ${url} failed: ${resp.status} ${text}`);
  }
  return await resp.json();
}

// Build a query string from an object, skipping null/empty values.
export function buildQuery(params) {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    usp.set(key, String(value));
  }
  const s = usp.toString();
  return s ? "?" + s : "";
}

// Format a unix-seconds timestamp as a local datetime string.
export function formatTime(unixSeconds) {
  if (unixSeconds === null || unixSeconds === undefined) return "—";
  const d = new Date(unixSeconds * 1000);
  return d.toLocaleString();
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
