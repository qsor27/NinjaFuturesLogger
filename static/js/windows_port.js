import { fetchJSON, putJSON } from "./api.js";

const panel = document.getElementById("windows-port-panel");
if (panel) {
  const endpoint = panel.dataset.endpoint;
  const portDisplay = panel.querySelector('[data-field="port"]');
  const portInput = panel.querySelector('[data-field="port-input"]');
  const status = panel.querySelector('[data-region="status"]');

  async function refresh() {
    let data;
    try {
      data = await fetchJSON(endpoint);
    } catch {
      portDisplay.textContent = "(could not load)";
      return;
    }
    portDisplay.textContent = data.port;
    portInput.value = data.port;
  }

  async function save() {
    const value = parseInt(portInput.value, 10);
    if (Number.isNaN(value) || value < 1024 || value > 65535) {
      status.textContent = "Port must be 1024-65535.";
      status.style.color = "var(--danger, #c33)";
      return;
    }
    status.textContent = "Saving…";
    status.style.color = "var(--text-secondary)";
    let body;
    try {
      body = await putJSON(endpoint, { port: value });
    } catch (e) {
      status.textContent = (e.body && e.body.error) || "Save failed.";
      status.style.color = "var(--danger, #c33)";
      return;
    }
    portDisplay.textContent = body.port;
    status.textContent = body.restart_required
      ? "Saved. Restart the app for the new port to take effect."
      : "Saved.";
    status.style.color = "var(--text-secondary)";
  }

  panel.addEventListener("click", (e) => {
    if (e.target?.dataset?.action === "save") save();
  });

  refresh();
}
