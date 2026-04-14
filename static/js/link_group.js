import { fetchJSON, setText } from "./api.js";

const root = document.getElementById("link-root");
const { linkGroupId } = root.dataset;
const title = document.getElementById("link-title");
const membersEl = document.getElementById("link-members");

async function load() {
  try {
    const detail = await fetchJSON(`/api/links/${linkGroupId}`);
    setText(title, detail.label || `Link group #${detail.link_group_id}`);
    membersEl.innerHTML = "";
    for (const m of detail.members) {
      const box = document.createElement("div");
      box.className = "link-box";
      try {
        const posResp = await fetchJSON(
          `/api/positions/${encodeURIComponent(m.account)}/${encodeURIComponent(m.instrument)}/${encodeURIComponent(m.entry_execution_id)}`,
        );
        const p = posResp.position;
        const a = document.createElement("a");
        a.href = `/positions/${encodeURIComponent(m.account)}/${encodeURIComponent(m.instrument)}/${encodeURIComponent(m.entry_execution_id)}`;
        setText(a, `${p.instrument} ${p.side} × ${p.quantity} — $${(p.dollars_pnl || 0).toFixed(2)}`);
        box.appendChild(a);
      } catch (_e) {
        const orphan = document.createElement("span");
        orphan.className = "orphan";
        setText(
          orphan,
          `(orphaned) ${m.account}/${m.instrument}/${m.entry_execution_id} — position no longer exists in its original form`,
        );
        box.appendChild(orphan);
      }
      membersEl.appendChild(box);
    }
  } catch (e) {
    setText(title, `Error: ${e.message}`);
  }
}

load();
