// Shared preset-range logic. Pure math on a Date (browser local tz).
// Returns { fromISO, toISO } with ISO YYYY-MM-DD strings, or null for "custom".

export const PRESETS = [
  { value: "", label: "Custom" },
  { value: "this_week", label: "This week" },
  { value: "this_month", label: "This month" },
  { value: "last_30_days", label: "Last 30 days" },
  { value: "this_quarter", label: "This quarter" },
  { value: "this_year", label: "This year" },
];

function toISO(d) {
  // Build from local Y/M/D to avoid UTC shift near midnight.
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function startOfDay(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function mondayOf(d) {
  // ISO week: Monday = start. getDay(): Sun=0, Mon=1, ..., Sat=6.
  const dow = d.getDay();
  const offset = dow === 0 ? 6 : dow - 1; // days since Monday
  const m = startOfDay(d);
  m.setDate(m.getDate() - offset);
  return m;
}

export function computePresetRange(preset, today = new Date()) {
  if (!preset) return null; // "Custom" -> caller leaves inputs untouched
  const t = startOfDay(today);
  const toISOStr = toISO(t);
  let from;
  switch (preset) {
    case "this_week":
      from = mondayOf(t);
      break;
    case "this_month":
      from = new Date(t.getFullYear(), t.getMonth(), 1);
      break;
    case "last_30_days":
      from = new Date(t.getFullYear(), t.getMonth(), t.getDate() - 29);
      break;
    case "this_quarter": {
      const qMonth = Math.floor(t.getMonth() / 3) * 3; // 0, 3, 6, 9
      from = new Date(t.getFullYear(), qMonth, 1);
      break;
    }
    case "this_year":
      from = new Date(t.getFullYear(), 0, 1);
      break;
    default:
      return null;
  }
  return { fromISO: toISO(from), toISO: toISOStr };
}

// Builds a <select> populated with PRESETS. Caller supplies the container
// (a wrapper <label> or <div>), the initial preset value, and a change handler
// that receives (preset, range|null).
export function renderPresetSelect(selectEl, initialValue, onChange) {
  selectEl.innerHTML = "";
  for (const p of PRESETS) {
    const o = document.createElement("option");
    o.value = p.value;
    o.textContent = p.label;
    selectEl.appendChild(o);
  }
  selectEl.value = initialValue || "";
  selectEl.addEventListener("change", () => {
    const v = selectEl.value;
    onChange(v, computePresetRange(v));
  });
}
