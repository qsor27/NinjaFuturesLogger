// review.js — hindsight-free review deck. Flow: create session -> loop
// (next-card -> chart cropped at entry -> Valid/Invalid -> reveal -> Next)
// -> Done -> 2x2 summary. The server refuses post-entry bars until an
// attempt is recorded, so nothing here can leak the future by accident.

import { HttpError, fetchJSON, postJSON } from "./api.js";
import { fmtMoney, pnlClass } from "./format.js";
import { PriceChart } from "./PriceChart.js";

const els = {
  status: document.getElementById("review-status"),
  meta: document.getElementById("review-card-meta"),
  chart: document.getElementById("review-chart"),
  valid: document.getElementById("review-valid"),
  invalid: document.getElementById("review-invalid"),
  next: document.getElementById("review-next"),
  done: document.getElementById("review-done"),
  reveal: document.getElementById("review-reveal"),
  summary: document.getElementById("review-summary"),
};

let sessionId = null;
let card = null;
let chart = null;
let phase = "loading"; // loading | calling | revealed | done

// Buttons start disabled/hidden until the first card actually loads.
els.valid.disabled = true;
els.invalid.disabled = true;
els.next.hidden = true;

function errMessage(e) {
  return (e && e.message) || String(e);
}

// Bars URL for a card. `revealed` is read by the caller at call time (not
// captured eagerly) so a timeframe switch after reveal keeps asking for the
// revealed window instead of silently re-hiding the future.
function barsUrl(tf, revealed) {
  const qs = new URLSearchParams({
    timeframe: tf,
    session_id: String(sessionId),
  });
  if (revealed) qs.set("revealed", "1");
  return `/api/review/cards/${encodeURIComponent(card.entry_execution_id)}/bars?${qs}`;
}

async function loadNextCard() {
  phase = "loading";
  els.reveal.hidden = true;
  els.reveal.textContent = "";
  els.reveal.className = "";
  els.next.hidden = true;
  els.valid.disabled = true;
  els.invalid.disabled = true;
  els.status.textContent = "Loading next card…";

  if (chart) {
    chart.destroy();
    chart = null;
  }
  els.chart.innerHTML = "";
  els.meta.textContent = "";

  let result;
  try {
    result = await fetchJSON(`/api/review/next-card?session_id=${encodeURIComponent(sessionId)}`);
  } catch (e) {
    els.status.textContent = `Failed to load next card: ${errMessage(e)}`;
    return;
  }
  if (result === null) {
    // 204: deck is empty (no reviewable cards left, or none ever existed).
    els.status.textContent =
      "No reviewable trades yet — the deck needs closed positions with 1m bar data.";
    phase = "done";
    return;
  }
  card = result.card;
  els.meta.textContent =
    `${card.instrument} — ${card.side} ${card.quantity} @ ` + `${card.entry_price.toFixed(2)}`;

  // The barsProvider is re-invoked by PriceChart on every timeframe switch,
  // both before and after reveal, so it must consult `phase` at call time
  // (not capture it now). We also capture the last bars error ourselves:
  // PriceChart swallows barsProvider failures into its own error/placeholder
  // state rather than rejecting initReview(), so this is the only way for
  // the page to notice a coverage-gap 404 and skip the card silently.
  let lastBarsError = null;
  try {
    chart = await PriceChart.initReview({
      container: els.chart,
      card,
      barsProvider: async (tf) => {
        try {
          const payload = await fetchJSON(barsUrl(tf, phase === "revealed"));
          lastBarsError = null;
          return payload;
        } catch (e) {
          lastBarsError = e;
          throw e;
        }
      },
    });
  } catch (e) {
    // Defensive: initReview does not currently reject on a barsProvider
    // failure, but guard in case that ever changes.
    lastBarsError = e;
  }

  if (
    chart &&
    chart.state === "error" &&
    lastBarsError instanceof HttpError &&
    lastBarsError.status === 404
  ) {
    // Coverage gap discovered at serve time (eligibility passed but the
    // bars route found nothing pre-entry): skip this card silently (spec).
    chart.destroy();
    chart = null;
    return loadNextCard();
  }
  if (chart && chart.state === "error") {
    els.status.textContent = `Chart failed to load: ${lastBarsError ? errMessage(lastBarsError) : "unknown error"}`;
    return;
  }

  els.valid.disabled = false;
  els.invalid.disabled = false;
  els.status.textContent = "Valid entry or invalid entry?";
  phase = "calling";
}

async function submitCall(call) {
  if (phase !== "calling") return;
  phase = "loading";
  els.valid.disabled = true;
  els.invalid.disabled = true;
  els.status.textContent = "Recording call…";

  let result;
  try {
    result = await postJSON("/api/review/attempts", {
      session_id: sessionId,
      entry_execution_id: card.entry_execution_id,
      call,
    });
  } catch (e) {
    // Let the user retry the same card rather than getting stuck.
    phase = "calling";
    els.valid.disabled = false;
    els.invalid.disabled = false;
    els.status.textContent = `Call failed: ${errMessage(e)}`;
    return;
  }

  // Flip to "revealed" before fetching the reveal window so the barsProvider
  // closure (and any timeframe switch the user fires mid-fetch) asks for
  // revealed=1 data — this is the only place `phase` becomes "revealed".
  phase = "revealed";
  const reveal = result.reveal;

  try {
    const data = await fetchJSON(barsUrl(chart.timeframe, true));
    chart.setReviewData(data.bars, reveal.exit_fills);
  } catch (e) {
    els.status.textContent = `Reveal chart failed to load: ${errMessage(e)}`;
  }

  els.reveal.hidden = false;
  els.reveal.textContent =
    `You called ${call.toUpperCase()} — net ` +
    fmtMoney(reveal.net_pnl, { decimals: 2, signed: reveal.net_pnl > 0 });
  els.reveal.className = pnlClass(reveal.net_pnl);
  els.next.hidden = false;
  els.next.focus();
  if (!els.status.textContent.startsWith("Reveal chart failed")) {
    els.status.textContent = "";
  }
}

async function endSession() {
  els.done.disabled = true;
  if (chart) {
    chart.destroy();
    chart = null;
  }
  els.chart.innerHTML = "";

  let body;
  try {
    body = await postJSON(`/api/review/sessions/${sessionId}/end`, {});
  } catch (e) {
    els.done.disabled = false;
    els.status.textContent = `Failed to end session: ${errMessage(e)}`;
    return;
  }
  phase = "done";
  els.meta.textContent = "";
  els.reveal.hidden = true;
  els.next.hidden = true;
  els.valid.disabled = true;
  els.invalid.disabled = true;
  els.status.textContent = "Session ended.";
  renderSummary(body.session, body.all_time);
}

function summaryTable(title, s) {
  const cell = (c) => `${c.count} · ${fmtMoney(c.net_pnl, { decimals: 2 })}`;
  const table = document.createElement("table");
  table.className = "review-summary-table";
  const caption = document.createElement("caption");
  caption.textContent = `${title} (${s.attempts} attempts)`;
  table.appendChild(caption);
  const rows = [
    ["", "Won", "Lost"],
    ["Called valid", cell(s.valid_won), cell(s.valid_lost)],
    ["Called invalid", cell(s.invalid_won), cell(s.invalid_lost)],
  ];
  for (const r of rows) {
    const tr = document.createElement("tr");
    for (const c of r) {
      const td = document.createElement("td");
      td.textContent = c;
      tr.appendChild(td);
    }
    table.appendChild(tr);
  }
  const scratches = s.valid_scratch.count + s.invalid_scratch.count;
  if (scratches > 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 3;
    td.textContent = `${scratches} scratch (exactly $0.00) not shown above`;
    tr.appendChild(td);
    table.appendChild(tr);
  }
  return table;
}

function renderSummary(session, allTime) {
  els.summary.hidden = false;
  els.summary.innerHTML = "";
  els.summary.appendChild(summaryTable("This session", session));
  els.summary.appendChild(summaryTable("All time", allTime));
}

function onKey(e) {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  const k = e.key.toLowerCase();
  if (phase === "calling" && k === "v") submitCall("valid");
  else if (phase === "calling" && k === "i") submitCall("invalid");
  else if (phase === "revealed" && (k === "n" || k === " " || k === "enter")) {
    e.preventDefault();
    loadNextCard();
  }
}

async function main() {
  const created = await postJSON("/api/review/sessions");
  sessionId = created.session_id;
  els.valid.addEventListener("click", () => submitCall("valid"));
  els.invalid.addEventListener("click", () => submitCall("invalid"));
  els.next.addEventListener("click", () => loadNextCard());
  els.done.addEventListener("click", () => endSession());
  document.addEventListener("keydown", onKey);
  await loadNextCard();
}

main().catch((e) => {
  els.status.textContent = `Review failed to start: ${errMessage(e)}`;
});
