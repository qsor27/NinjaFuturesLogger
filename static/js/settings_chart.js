import { fetchJSON, putJSON } from "./api.js";

const endpoint = "/api/config/chart-defaults";
const form = document.getElementById("chart-defaults-form");
const status = document.getElementById("chart-defaults-status");

async function load() {
  const body = await fetchJSON(endpoint);
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
  try {
    await putJSON(endpoint, payload);
    status.textContent = "Saved.";
  } catch (e) {
    status.textContent = `Error: ${(e.body && e.body.error) || e.status || e.message}`;
  }
}

form.addEventListener("submit", save);
load();
