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
let phase = "idle"; // idle | loading | calling | revealed | done

// Generation token. Bumped by every loadNextCard/endSession call that takes
// ownership of the card/chart. submitCall (and a stale loadNextCard/
// endSession tail resuming after an await) captures the token at the start
// and must re-check it after every await before touching `chart`, `card`,
// `phase`, or review DOM: a mismatch means a newer operation already took
// over and this continuation's remaining work is stale and must no-op.
// This guards against e.g. pressing N while submitCall's reveal-bars fetch
// is still in flight (phase is already "revealed" at that point, so the
// key handler's phase check alone can't catch it).
let generation = 0;

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

async function loadNextCard({ internal = false } = {}) {
  // Entry gate: ignore a Next click / N keypress that arrives while another
  // load, attempt, or end-session is already in flight. The internal 404-
  // skip recursion below is exempt — it's a synchronous continuation of a
  // load this same call already owns, not a new external trigger.
  if (!internal && phase === "loading") return;
  const gen = ++generation;

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
    if (gen !== generation) return;
    els.status.textContent = `Failed to load next card: ${errMessage(e)}`;
    phase = "done"; // not stuck on "loading" — Done remains reachable
    return;
  }
  if (gen !== generation) return;
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
  //
  // The resolved chart is held locally (not assigned into the module-level
  // `chart` var) until we've confirmed this generation is still current —
  // a stale generation must never clobber a newer generation's active chart.
  let lastBarsError = null;
  let newChart;
  try {
    newChart = await PriceChart.initReview({
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

  if (gen !== generation) {
    // Superseded while awaiting (a newer loadNextCard or endSession already
    // took over). Release the orphaned chart and touch nothing else.
    if (newChart) newChart.destroy();
    return;
  }
  chart = newChart || null;

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
    return loadNextCard({ internal: true });
  }
  if (!chart || chart.state === "error") {
    els.status.textContent = `Chart failed to load: ${lastBarsError ? errMessage(lastBarsError) : "unknown error"}`;
    phase = "done"; // not stuck on "loading" — Done remains reachable
    return;
  }

  els.valid.disabled = false;
  els.invalid.disabled = false;
  els.status.textContent = "Valid entry or invalid entry?";
  phase = "calling";
}

async function submitCall(call) {
  if (phase !== "calling") return;
  // Captured once, up front: if a newer loadNextCard/endSession takes over
  // while we're awaiting below (e.g. the user presses N the instant reveal
  // starts, before this function's own UI update reaches the Next button),
  // `generation` will have moved past this value and every check below
  // turns the rest of this call into a no-op instead of touching a chart or
  // card that no longer belongs to us.
  const gen = generation;
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
    if (gen !== generation) return;
    // Let the user retry the same card rather than getting stuck.
    phase = "calling";
    els.valid.disabled = false;
    els.invalid.disabled = false;
    els.status.textContent = `Call failed: ${errMessage(e)}`;
    return;
  }
  if (gen !== generation) return;

  // Flip to "revealed" before fetching the reveal window so the barsProvider
  // closure (and any timeframe switch the user fires mid-fetch) asks for
  // revealed=1 data — this is the only place `phase` becomes "revealed".
  // From here on every await is re-checked against `gen` before touching
  // `chart` or review DOM.
  phase = "revealed";
  const reveal = result.reveal;

  let revealError = null;
  try {
    const data = await fetchJSON(barsUrl(chart.timeframe, true));
    if (gen !== generation) return;
    chart.setReviewData(data.bars, reveal.exit_fills);
  } catch (e) {
    if (gen !== generation) return;
    revealError = e;
  }
  if (gen !== generation) return;

  els.reveal.hidden = false;
  els.reveal.textContent =
    `You called ${call.toUpperCase()} — net ` +
    fmtMoney(reveal.net_pnl, { decimals: 2, signed: reveal.net_pnl > 0 });
  els.reveal.className = pnlClass(reveal.net_pnl);
  els.next.hidden = false;
  els.next.focus();
  els.status.textContent = revealError
    ? `Reveal chart failed to load: ${errMessage(revealError)}`
    : "";
}

async function endSession() {
  // Entry gate, symmetric with loadNextCard: ignore a Done click while a
  // load or an in-flight attempt call already owns "loading". Once past the
  // gate, claim "loading" ourselves immediately — this is what stops a
  // concurrent Next click / N keypress (both gated on phase) from starting a
  // competing loadNextCard while we're ending the session.
  if (phase === "loading") return;
  const gen = ++generation;
  const priorPhase = phase;
  phase = "loading";
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
    if (gen !== generation) return;
    phase = priorPhase; // restore so a retry (Done again, or resuming review) makes sense
    els.done.disabled = false;
    els.status.textContent = `Failed to end session: ${errMessage(e)}`;
    return;
  }
  if (gen !== generation) return;

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
  rows.forEach((r, rowIndex) => {
    const tr = document.createElement("tr");
    r.forEach((c, colIndex) => {
      const td = document.createElement("td");
      td.textContent = c;
      // Row 2 = "Called invalid", column 1 = "Won": invalid entries that got
      // paid anyway. The feature exists to make this cell confront the
      // user, so it gets its own class regardless of scratch/zero state.
      if (rowIndex === 2 && colIndex === 1) td.className = "review-summary-invalid-won";
      tr.appendChild(td);
    });
    table.appendChild(tr);
  });
  const scratches = s.valid_scratch.count + s.invalid_scratch.count;
  if (scratches > 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 3;
    td.textContent = `${scratches} scratch (exactly $0.00) not shown above`;
    tr.appendChild(td);
    table.appendChild(tr);
  }
  if (s.invalid_won.count > 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 3;
    td.className = "review-summary-invalid-won-note";
    td.textContent =
      `Invalid entries that got paid anyway: ${s.invalid_won.count} for ` +
      `${fmtMoney(s.invalid_won.net_pnl, { decimals: 2 })} — these wins train the habit.`;
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
