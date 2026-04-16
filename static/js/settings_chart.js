const endpoint = "/api/config/chart-defaults";
const form = document.getElementById("chart-defaults-form");
const status = document.getElementById("chart-defaults-status");

async function load() {
  const res = await fetch(endpoint);
  const body = await res.json();
  form.elements.default_timeframe.value = body.default_timeframe;
  form.elements.volume_visible_default.checked = Boolean(body.volume_visible_default);
  form.elements.display_timezone.value = body.display_timezone || "";
  form.elements.source_timezone.value = body.source_timezone || "";
}

async function save(event) {
  event.preventDefault();
  status.textContent = "Saving…";
  const payload = {
    default_timeframe: form.elements.default_timeframe.value,
    volume_visible_default: form.elements.volume_visible_default.checked,
    display_timezone: form.elements.display_timezone.value || null,
    source_timezone: form.elements.source_timezone.value || null,
  };
  const res = await fetch(endpoint, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json();
    status.textContent = `Error: ${err.error || res.status}`;
    return;
  }
  status.textContent = "Saved.";
}

form.addEventListener("submit", save);
load();
