let autoRefreshInterval = null;

initSystemHealth();

async function initSystemHealth() {
  await renderHealthz();
  await renderHealth();
  setupAutoRefresh();
}

async function renderHealthz() {
  const el = document.getElementById("healthz-section");
  if (!el) return;
  el.innerHTML = `
    <button id="healthz-btn">Run Healthz Check</button>
    <span id="healthz-result" style="margin-left:12px"></span>`;
  document.getElementById("healthz-btn").addEventListener("click", async () => {
    const result = document.getElementById("healthz-result");
    result.textContent = "Checking…";
    const resp = await fetch("/healthz");
    const body = await resp.json();
    const ok = resp.status === 200;
    result.style.color = ok ? "#0a7f0a" : "#b00020";
    result.textContent = ok
      ? "✓ Healthy"
      : `✗ Unhealthy: ${Object.entries(body).filter(([, v]) => !v).map(([k]) => k).join(", ")}`;
  });
}

async function renderHealth() {
  const resp = await fetch("/api/system/health");
  const body = await resp.json();
  renderJobs(body.jobs);
  renderPool(body.pool);
  renderWatchdog(body.watchdog);
  renderUptime(body);
}

function renderJobs(jobs) {
  const el = document.getElementById("jobs-table");
  if (!jobs.length) {
    el.innerHTML = "<p>No scheduled jobs.</p>";
    return;
  }
  const rows = jobs.map((j) => {
    const next = j.next_run_time ? new Date(j.next_run_time * 1000).toLocaleString() : "—";
    const last = j.last_run_at ? new Date(j.last_run_at * 1000).toLocaleString() : "—";
    const statusColor = j.last_run_status === "error" ? "#b00020" : j.last_run_status === "success" ? "#0a7f0a" : "#888";
    const avgMs = j.avg_duration_ms != null ? `${j.avg_duration_ms} ms` : "—";
    return `<tr>
      <td>${escHtml(j.job_id)}</td>
      <td>${escHtml(j.trigger)}</td>
      <td>${last}</td>
      <td style="color:${statusColor}">${j.last_run_status ?? "—"}</td>
      <td>${next}</td>
      <td>${avgMs}</td>
      <td><button class="run-now-btn" data-job-id="${j.job_id}">Run Now</button></td>
    </tr>`;
  });
  el.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Job ID</th><th>Trigger</th><th>Last Run</th><th>Status</th>
          <th>Next Run</th><th>Avg Duration</th><th>Action</th>
        </tr>
      </thead>
      <tbody>${rows.join("")}</tbody>
    </table>`;

  el.querySelectorAll(".run-now-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.textContent = "Running…";
      btn.disabled = true;
      const resp = await fetch(`/api/system/run-job/${btn.dataset.jobId}`, { method: "POST" });
      if (resp.ok) {
        btn.textContent = "Done";
        setTimeout(() => renderHealth(), 500);
      } else {
        btn.textContent = "Error";
        btn.disabled = false;
      }
    });
  });
}

function renderPool(pool) {
  const el = document.getElementById("pool-section");
  if (!el) return;
  el.innerHTML = `
    <dl class="detail-header">
      <dt>Max Workers</dt><dd>${pool.max_workers}</dd>
      <dt>Spawned Threads</dt><dd>${pool.spawned_threads ?? "—"}</dd>
      <dt>Pending Queue</dt><dd>${pool.pending_queue ?? "—"}</dd>
    </dl>`;
}

function renderWatchdog(watchdog) {
  const el = document.getElementById("watchdog-section");
  if (!el) return;
  const aliveColor = watchdog.alive ? "#0a7f0a" : "#b00020";
  el.innerHTML = `
    <dl class="detail-header">
      <dt>Status</dt><dd style="color:${aliveColor}">${watchdog.alive ? "Alive" : "Dead"}</dd>
      <dt>Watching</dt><dd>${escHtml(watchdog.path)}</dd>
    </dl>`;
}

function renderUptime(body) {
  const el = document.getElementById("uptime-section");
  if (!el) return;
  const startedAt = body.started_at ? new Date(body.started_at * 1000).toLocaleString() : "—";
  const uptime = formatDuration(body.uptime_seconds ?? 0);
  el.innerHTML = `
    <dl class="detail-header">
      <dt>Process Started</dt><dd>${startedAt}</dd>
      <dt>Uptime</dt><dd>${uptime}</dd>
      <dt>Python Version</dt><dd>${escHtml(body.python_version ?? "—")}</dd>
    </dl>`;
}

function setupAutoRefresh() {
  const container = document.querySelector("h1");
  if (!container) return;
  const toggle = document.createElement("label");
  toggle.style.cssText = "margin-left:16px;font-size:14px;font-weight:normal;cursor:pointer";
  toggle.innerHTML = `<input type="checkbox" id="auto-refresh"> Auto-refresh (10s)`;
  container.after(toggle);
  document.getElementById("auto-refresh").addEventListener("change", (e) => {
    if (e.target.checked) {
      autoRefreshInterval = setInterval(renderHealth, 10000);
    } else {
      clearInterval(autoRefreshInterval);
      autoRefreshInterval = null;
    }
  });
}

function formatDuration(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return [h && `${h}h`, m && `${m}m`, `${s}s`].filter(Boolean).join(" ");
}

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
