const panel = document.getElementById("nt-connection-panel");
if (panel) {
  const endpoint = panel.dataset.endpoint;
  const installEndpoint = panel.dataset.installEndpoint;

  function fmtTimestamp(unix) {
    if (!unix) return "never";
    return new Date(unix * 1000).toLocaleString();
  }

  async function refresh() {
    const resp = await fetch(endpoint);
    const data = await resp.json();
    panel.querySelector('[data-field="nt_found"]').textContent =
      data.nt_found ? "yes" : "no";
    panel.querySelector('[data-field="indicators_path"]').textContent =
      data.indicators_path || "(not found)";
    panel.querySelector('[data-field="indicator_installed_at"]').textContent =
      fmtTimestamp(data.indicator_installed_at);
    const csv = data.inbox.last_csv_name
      ? `${data.inbox.last_csv_name} @ ${fmtTimestamp(data.inbox.last_csv_mtime)}`
      : "(nothing yet)";
    panel.querySelector('[data-field="last_csv"]').textContent = csv;
    return data;
  }

  async function reinstall() {
    const data = await refresh();
    if (!data.nt_found) {
      alert("NinjaTrader wasn't detected - install the indicator manually.");
      return;
    }
    const resp = await fetch(installEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dest_dir: data.indicators_path,
        on_conflict: "backup_replace",
      }),
    });
    const result = await resp.json();
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
