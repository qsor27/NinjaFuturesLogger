import { deleteJSON, fetchJSON, putJSON } from "./api.js";

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
  try {
    return await fetchJSON("/api/filter-defaults");
  } catch {
    return { accounts: [], positions: null, stats: null };
  }
}

export async function saveDefault(scope, filter) {
  try {
    await putJSON(`/api/filter-defaults/${encodeURIComponent(scope)}`, filter);
    return true;
  } catch {
    return false;
  }
}

export async function clearDefault(scope) {
  try {
    await deleteJSON(`/api/filter-defaults/${encodeURIComponent(scope)}`);
    return true;
  } catch {
    return false;
  }
}

export async function clearAllDefaults() {
  try {
    await deleteJSON("/api/filter-defaults");
    return true;
  } catch {
    return false;
  }
}
