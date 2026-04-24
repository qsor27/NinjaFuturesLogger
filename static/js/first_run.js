// Wizard controller - server-rendered shell, JSON API for logic.

const root = document.getElementById("first-run-root");
if (!root) throw new Error("first-run-root missing");

const endpoints = {
  detect: root.dataset.endpointDetect,
  install: root.dataset.endpointInstall,
  inbox: root.dataset.endpointInbox,
  complete: root.dataset.endpointComplete,
};

function showStep(name) {
  root.querySelectorAll("[data-step]").forEach((el) => {
    el.hidden = el.dataset.step !== name;
  });
}

async function postJSON(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return resp.json();
}

async function getJSON(url) {
  const resp = await fetch(url);
  return resp.json();
}

let detectedIndicatorsPath = null;

async function runDetect() {
  showStep("detect");
  const result = await getJSON(endpoints.detect);
  if (result.found) {
    detectedIndicatorsPath = result.indicators_path;
    root.querySelector('[data-region="indicators-path"]').textContent = result.indicators_path;
    showStep("install-offer");
  } else {
    showStep("manual");
  }
}

async function runInstall() {
  if (!detectedIndicatorsPath) return;
  const btn = root.querySelector('[data-action="install-indicator"]');
  btn.disabled = true;
  btn.textContent = "Installing...";
  const result = await postJSON(endpoints.install, {
    dest_dir: detectedIndicatorsPath,
    on_conflict: "backup_replace",
  });
  btn.disabled = false;
  btn.textContent = "Install indicator";
  if (result.success) {
    showStep("followup");
    startInboxPolling();
  } else {
    alert(`Install failed: ${result.error || "unknown error"}`);
  }
}

let inboxTimer = null;
let inboxDeadline = 0;

function startInboxPolling() {
  clearInterval(inboxTimer);
  inboxDeadline = Date.now() + 60_000;
  const statusEl = root.querySelector('[data-region="verify-status"]');
  const tick = async () => {
    const result = await getJSON(endpoints.inbox);
    if (result.files_count > 0) {
      clearInterval(inboxTimer);
      showStep("done");
      return;
    }
    if (Date.now() > inboxDeadline) {
      statusEl.textContent =
        "No executions received yet. Check NinjaTrader's NinjaScript Output window " +
        "for compile errors, then add the ExecutionExporter indicator to a chart.";
    }
  };
  tick();
  inboxTimer = setInterval(tick, 3000);
}

async function finish() {
  await postJSON(endpoints.complete, {});
  window.location.href = "/";
}

root.addEventListener("click", async (e) => {
  const action = e.target?.dataset?.action;
  if (!action) return;
  e.preventDefault();
  switch (action) {
    case "next-welcome":
      await runDetect();
      break;
    case "install-indicator":
      await runInstall();
      break;
    case "manual":
      showStep("manual");
      break;
    case "next-manual":
      showStep("followup");
      startInboxPolling();
      break;
    case "download-cs":
      window.location.href = "/static/ninjascript/ExecutionExporter.cs";
      break;
    case "skip":
    case "finish":
      await finish();
      break;
  }
});
