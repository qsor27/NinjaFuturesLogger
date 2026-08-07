// static/js/ohlc_jobs.js — the one OHLC fetch-trigger + job poller.
// Every on-demand bar fetch in the UI goes through triggerFetch + pollJob.
// Result-status branching (all_sources_unavailable / out_of_reach / cached)
// stays caller-side — this module only moves the job lifecycle.

import { fetchJSON, postJSON } from "./api.js";

// POST /api/chart/{instrument}/fetch → 202 {job_id}. Throws HttpError on
// non-2xx (e.g. 409 {error: "out_of_reach"}) — callers branch on e.status.
export async function triggerFetch(instrument, timeframe, start, end) {
  const body = await postJSON(`/api/chart/${encodeURIComponent(instrument)}/fetch`, {
    timeframe,
    start,
    end,
  });
  return body.job_id;
}

// Poll /api/ohlc/jobs/{jobId} until it reaches a terminal state. Resolves
// with the final snapshot ({state, result?, ...}) for "done"/"failed"/"error",
// or null when timeoutMs elapses first. Transient poll errors are swallowed
// and retried within the window.
export async function pollJob(jobId, { intervalMs = 2000, timeoutMs = 120000 } = {}) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    await new Promise((r) => setTimeout(r, intervalMs));
    let snap;
    try {
      snap = await fetchJSON(`/api/ohlc/jobs/${encodeURIComponent(jobId)}`);
    } catch (_e) {
      continue;
    }
    if (snap.state === "done" || snap.state === "failed" || snap.state === "error") {
      return snap;
    }
  }
  return null;
}
