// filter_defaults — fetch / save / clear the user's saved filter defaults.
// Pure helper at top is DOM- and fetch-free so a future JS runner can import
// it standalone.

export function isUrlEmpty(url, keys) {
  const params = new URL(url).searchParams;
  for (const k of keys) {
    if (params.has(k)) return false;
  }
  return true;
}

export async function fetchDefaults() {
  const resp = await fetch("/api/filter-defaults");
  if (!resp.ok) return { accounts: [], positions: null, stats: null };
  return await resp.json();
}

export async function saveDefault(scope, filter) {
  const resp = await fetch(`/api/filter-defaults/${encodeURIComponent(scope)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(filter),
  });
  return resp.ok;
}

export async function clearDefault(scope) {
  const resp = await fetch(`/api/filter-defaults/${encodeURIComponent(scope)}`, {
    method: "DELETE",
  });
  return resp.ok;
}

export async function clearAllDefaults() {
  const resp = await fetch("/api/filter-defaults", { method: "DELETE" });
  return resp.ok;
}
