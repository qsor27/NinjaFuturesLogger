import { fetchJSON, postJSON } from "./api.js";
import { formatTime } from "./format.js";

const panel = document.getElementById("nt-connection-panel");
if (panel) {
  const endpoint = panel.dataset.endpoint;
  const installEndpoint = panel.dataset.installEndpoint;

  async function refresh() {
    let data;
    try {
      data = await fetchJSON(endpoint);
    } catch {
      panel.querySelector('[data-field="nt_found"]').textContent = "(could not load)";
      return null;
    }
    panel.querySelector('[data-field="nt_found"]').textContent =
      data.nt_found ? "yes" : "no";
    panel.querySelector('[data-field="indicators_path"]').textContent =
      data.indicators_path || "(not found)";
    panel.querySelector('[data-field="indicator_installed_at"]').textContent =
      data.indicator_installed_at ? formatTime(data.indicator_installed_at) : "never";
    const csv = data.inbox.last_csv_name
      ? `${data.inbox.last_csv_name} @ ${data.inbox.last_csv_mtime ? formatTime(data.inbox.last_csv_mtime) : "never"}`
      : "(nothing yet)";
    panel.querySelector('[data-field="last_csv"]').textContent = csv;
    return data;
  }

  async function reinstall() {
    const data = await refresh();
    if (!data) return;
    if (!data.nt_found) {
      alert("NinjaTrader wasn't detected - install the indicator manually.");
      return;
    }
    let result;
    try {
      result = await postJSON(installEndpoint, {
        dest_dir: data.indicators_path,
        on_conflict: "backup_replace",
      });
    } catch (e) {
      alert(`Install failed: ${(e.body && e.body.error) || e.message}`);
      return;
    }
    if (!result.success) {
      alert(`Install failed: ${result.error || "unknown"}`);
      return;
    }
    await refresh();
  }

  panel.addEventListener("click", (e) => {
    const action = e.target?.dataset?.action;
    if (!action) return;
    if (action === "refresh") refresh();
    if (action === "reinstall") reinstall();
  });

  refresh();
}
