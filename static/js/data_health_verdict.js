// Renders the top-of-page verdict banner + updates the nav pill.
// Shared between /data-health and /data-health/system.

renderVerdict();

async function renderVerdict() {
  const el = document.getElementById("verdict-banner");
  if (!el) return;
  let body;
  try {
    const resp = await fetch("/api/data-health/summary");
    body = await resp.json();
  } catch (_e) {
    return;
  }

  const colors = {
    healthy: { border: "#0a7f0a", text: "#0a7f0a", icon: "🟢" },
    degraded: { border: "#b00020", text: "#b00020", icon: "🔴" },
    attention: { border: "#c07000", text: "#c07000", icon: "🟡" },
  };
  const style = colors[body.verdict] || colors.attention;

  const nextRetryStr = body.next_retry_at
    ? ` Next retry ${formatTime(body.next_retry_at)}.`
    : "";

  el.innerHTML = `
    <div style="padding:1em 1.25em;border-left:6px solid ${style.border};
                background:var(--bg-card);border-radius:4px;">
      <div style="font-size:1.3em;font-weight:600">
        ${style.icon} <span style="color:${style.text}">${escHtml(body.word)}</span>
      </div>
      <div style="margin-top:0.25em;color:var(--text-primary)">
        ${escHtml(body.line)}${nextRetryStr}
      </div>
    </div>`;

  updateNavPill(body);
}

function updateNavPill(summary) {
  const links = document.querySelectorAll("header a");
  for (const a of links) {
    if (a.getAttribute("href") !== "/data-health") continue;
    // Remove any prior pill from earlier renders.
    a.querySelector(".dh-nav-pill")?.remove();
    let text = "";
    let bg = "";
    if (summary.open_sources_count > 0) {
      text = "⚠";
      bg = "#b00020";
    } else if (summary.open_gaps_count > 0) {
      text = "•";
      bg = "#c07000";
    }
    if (!text) return;
    const pill = document.createElement("span");
    pill.className = "dh-nav-pill";
    pill.textContent = text;
    pill.style.cssText =
      `margin-left:6px;background:${bg};color:white;font-size:0.75em;` +
      `padding:2px 7px;border-radius:10px;font-weight:bold;`;
    a.appendChild(pill);
    return;
  }
}

function formatTime(unixSec) {
  return new Date(unixSec * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
