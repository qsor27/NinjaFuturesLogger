initValidation();

async function initValidation() {
  renderFilters();
  await loadIssues();
}

function renderFilters() {
  const bar = document.getElementById("filters-bar");
  if (!bar) return;
  bar.innerHTML = `
    <label>Status
      <select id="f-status">
        <option value="open">Open</option>
        <option value="resolved">Resolved</option>
        <option value="ignored">Ignored</option>
        <option value="all">All</option>
      </select>
    </label>
    <label>Severity
      <select id="f-severity">
        <option value="">All</option>
        <option value="high">High</option>
        <option value="medium">Medium</option>
        <option value="low">Low</option>
      </select>
    </label>
    <label>Account<input type="text" id="f-account" placeholder="account name"></label>
    <label>Instrument<input type="text" id="f-instrument" placeholder="e.g. MNQ"></label>
    <button id="apply-btn">Apply</button>`;
  document.getElementById("apply-btn").addEventListener("click", loadIssues);
  document.getElementById("f-status").addEventListener("change", loadIssues);
}

async function loadIssues() {
  const status = document.getElementById("f-status")?.value || "open";
  const severity = document.getElementById("f-severity")?.value || "";
  const account = document.getElementById("f-account")?.value || "";
  const instrument = document.getElementById("f-instrument")?.value || "";

  const params = new URLSearchParams({ status });
  if (severity) params.set("severity", severity);
  if (account) params.set("account", account);
  if (instrument) params.set("instrument", instrument);

  const resp = await fetch(`/api/integrity-issues?${params}`);
  const { issues } = await resp.json();
  renderIssues(issues, status);
}

function renderIssues(issues, status) {
  const el = document.getElementById("issues-table");
  if (!issues.length) {
    el.innerHTML = `<p>No ${status} integrity issues.</p>`;
    return;
  }
  const rows = issues.map((i) => {
    const age = Math.floor((Date.now() / 1000 - i.detected_at) / 3600);
    const detected = new Date(i.detected_at * 1000).toLocaleString();
    const execLink = i.execution_id
      ? `<a href="/positions?q=${encodeURIComponent(i.execution_id)}">${escHtml(i.execution_id)}</a>`
      : "—";
    const noteCell = i.resolution_note
      ? `<span style="color:#666;font-style:italic">${escHtml(i.resolution_note)}</span>`
      : i.ignore_note
      ? `<span style="color:#666;font-style:italic">${escHtml(i.ignore_note)}</span>`
      : "";
    const actionCell = i.resolved_at || i.ignored
      ? noteCell
      : `<button class="resolve-btn" data-id="${i.issue_id}">Resolve</button>
         <button class="ignore-btn" data-id="${i.issue_id}">Ignore</button>`;

    const sevColor = i.severity === "high" ? "#b00020" : i.severity === "medium" ? "#c07000" : "#555";
    return `<tr>
      <td style="color:${sevColor};font-weight:600">${escHtml(i.severity)}</td>
      <td>${escHtml(i.type)}</td>
      <td>${escHtml(i.account)}</td>
      <td>${escHtml(i.instrument)}</td>
      <td>${execLink}</td>
      <td>${escHtml(i.description)}</td>
      <td>${detected}</td>
      <td>${age}h</td>
      <td>${actionCell}</td>
    </tr>`;
  });
  el.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Severity</th><th>Type</th><th>Account</th><th>Instrument</th>
          <th>Execution</th><th>Description</th><th>Detected</th><th>Age</th><th>Action</th>
        </tr>
      </thead>
      <tbody>${rows.join("")}</tbody>
    </table>`;

  el.querySelectorAll(".resolve-btn").forEach((btn) => {
    btn.addEventListener("click", () => resolveIssue(btn.dataset.id));
  });
  el.querySelectorAll(".ignore-btn").forEach((btn) => {
    btn.addEventListener("click", () => ignoreIssue(btn.dataset.id));
  });
}

async function resolveIssue(id) {
  const note = prompt("Resolution note (optional):") ?? "";
  const resp = await fetch(`/api/integrity-issues/${id}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note: note || null }),
  });
  if (resp.ok) await loadIssues();
  else alert("Failed to resolve issue.");
}

async function ignoreIssue(id) {
  const note = prompt("Why are you ignoring this issue? (required):");
  if (!note) return;
  const resp = await fetch(`/api/integrity-issues/${id}/ignore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
  if (resp.ok) await loadIssues();
  else alert("Failed to ignore issue.");
}

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
