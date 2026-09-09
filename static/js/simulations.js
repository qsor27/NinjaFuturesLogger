// static/js/simulations.js — Simulation Analysis page.
// Builder (vocabulary-driven rule rows) + run + saved definitions + results.
// No math here: every number rendered arrives precomputed from the API.

import {
  filterToQueryString,
  parseFilterFromUrl,
  renderFilterBar,
} from "./stats_filter.js";
import { mountLineChart } from "./stats_charts.js";
import { HttpError, deleteJSON, fetchJSON, postJSON, putJSON } from "./api.js";
import { fmtMoney, formatTime, pnlClass, setText } from "./format.js";

const EXAMPLE_RULE = {
  metric: "losses",
  scope: "session",
  comparator: ">=",
  threshold: 2,
  action: "stop_session",
  action_param: null,
};

const state = {
  vocab: null,
  saved: [],
  selectedId: null,
  name: "",
  rules: [],
  filter: parseFilterFromUrl(),
  dirty: false,
  ruleErrors: {}, // rule index -> message
};

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const c of children) node.appendChild(c);
  return node;
}

function metricInfo(metric) {
  return state.vocab.metrics.find((m) => m.value === metric);
}

function fmtPercent(v) {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtNum(v, digits = 2) {
  if (v === null || v === undefined) return "—";
  return Number(v).toFixed(digits);
}

// ---------- builder ----------

function setStatus(text, dirty) {
  const s = $("sim-status");
  s.textContent = text;
  s.classList.toggle("dirty", Boolean(dirty));
}

function markDirty() {
  state.dirty = true;
  setStatus("Unsaved changes", true);
}

function select(options, value, onchange) {
  const s = el("select", { onchange });
  for (const o of options) {
    const opt = el("option", { value: o.value, text: o.label });
    if (o.value === value) opt.selected = true;
    s.appendChild(opt);
  }
  return s;
}

function thresholdInput(rule) {
  const kind = metricInfo(rule.metric).threshold_type;
  const commit = (e) => {
    const raw = e.target.value;
    if (kind === "time") rule.threshold = raw;
    else if (raw === "") rule.threshold = null;
    else rule.threshold = kind === "count" ? parseInt(raw, 10) : parseFloat(raw);
    markDirty();
  };
  if (kind === "time") {
    return el("input", { type: "time", value: rule.threshold ?? "11:00", onchange: commit });
  }
  return el("input", {
    type: "number",
    step: kind === "count" ? "1" : "0.01",
    min: kind === "count" ? "0" : null,
    value: rule.threshold ?? "",
    onchange: commit,
  });
}

function renderRuleRow(rule, idx) {
  const info = metricInfo(rule.metric);
  const scopeOptions = state.vocab.scopes.filter((s) => info.scopes.includes(s.value));
  if (!info.scopes.includes(rule.scope)) rule.scope = info.scopes[0];

  const row = el("div", { class: "rule-row", "data-index": String(idx) });
  row.appendChild(el("span", { class: "rule-word", text: `${idx + 1}. When` }));
  row.appendChild(
    select(state.vocab.metrics, rule.metric, (e) => {
      rule.metric = e.target.value;
      const kind = metricInfo(rule.metric).threshold_type;
      rule.threshold = kind === "time" ? "11:00" : kind === "count" ? 2 : 0;
      markDirty();
      renderRules();
    }),
  );
  if (info.threshold_type !== "time") {
    row.appendChild(el("span", { class: "rule-word", text: "in" }));
    row.appendChild(
      select(scopeOptions, rule.scope, (e) => {
        rule.scope = e.target.value;
        markDirty();
      }),
    );
  }
  row.appendChild(el("span", { class: "rule-word", text: "is" }));
  row.appendChild(
    select(state.vocab.comparators, rule.comparator, (e) => {
      rule.comparator = e.target.value;
      markDirty();
    }),
  );
  row.appendChild(thresholdInput(rule));
  row.appendChild(el("span", { class: "rule-word", text: "then" }));
  row.appendChild(
    select(state.vocab.actions, rule.action, (e) => {
      rule.action = e.target.value;
      const needs = state.vocab.actions.find((a) => a.value === rule.action).needs_param;
      rule.action_param = needs ? rule.action_param ?? 30 : null;
      markDirty();
      renderRules();
    }),
  );
  const action = state.vocab.actions.find((a) => a.value === rule.action);
  if (action.needs_param) {
    row.appendChild(
      el("input", {
        type: "number",
        min: "1",
        max: String(state.vocab.max_pause_minutes),
        step: "1",
        value: rule.action_param ?? 30,
        onchange: (e) => {
          rule.action_param = e.target.value === "" ? null : parseInt(e.target.value, 10);
          markDirty();
        },
      }),
    );
    row.appendChild(el("span", { class: "rule-word", text: "minutes" }));
  }
  row.appendChild(
    el("button", {
      type: "button",
      class: "rule-remove",
      text: "Remove",
      onclick: () => {
        state.rules.splice(idx, 1);
        markDirty();
        renderRules();
      },
    }),
  );
  const err = state.ruleErrors[idx];
  if (err) {
    row.classList.add("has-error");
    row.appendChild(el("div", { class: "rule-error", text: err }));
  }
  return row;
}

function renderRules() {
  const host = $("sim-rules");
  host.innerHTML = "";
  state.rules.forEach((rule, idx) => host.appendChild(renderRuleRow(rule, idx)));
  $("sim-add-rule").disabled = state.rules.length >= state.vocab.max_rules;
}

function readName() {
  state.name = $("sim-name").value;
}

function currentRulesPayload() {
  return state.rules.map((r) => ({
    metric: r.metric,
    scope: r.scope,
    comparator: r.comparator,
    threshold: r.threshold,
    action: r.action,
    action_param: r.action_param,
  }));
}

// ---------- errors ----------

function clearErrors() {
  state.ruleErrors = {};
  const e = $("sim-error");
  e.hidden = true;
  e.textContent = "";
}

function showError(err) {
  const e = $("sim-error");
  if (err instanceof HttpError && err.body && typeof err.body === "object") {
    e.textContent = err.body.error || `Request failed (${err.status})`;
    state.ruleErrors = {};
    for (const d of err.body.details || []) {
      if (d.loc && d.loc[0] === "rules" && /^\d+$/.test(d.loc[1] || "")) {
        const idx = Number(d.loc[1]);
        const field = d.loc.slice(2).join(".");
        state.ruleErrors[idx] = field ? `${field}: ${d.msg}` : d.msg;
      }
    }
    renderRules();
  } else {
    e.textContent = err && err.message ? err.message : String(err);
  }
  e.hidden = false;
}

// ---------- run / save / delete ----------

async function run() {
  clearErrors();
  setStatus("Running…", state.dirty);
  try {
    const body = {
      rules: currentRulesPayload(),
      accounts: state.filter.accounts || [],
      from: state.filter.from,
      to: state.filter.to,
      side: state.filter.side,
    };
    const result = await postJSON("/api/simulations/run", body);
    renderResults(result);
    setStatus(state.dirty ? "Unsaved changes" : "", state.dirty);
  } catch (err) {
    $("sim-results").hidden = true;
    setStatus("", state.dirty);
    showError(err);
  }
}

async function save() {
  clearErrors();
  readName();
  const body = { name: state.name, rules: currentRulesPayload() };
  try {
    const saved = state.selectedId
      ? await putJSON(`/api/simulations/${state.selectedId}`, body)
      : await postJSON("/api/simulations", body);
    state.selectedId = saved.simulation_id;
    state.dirty = false;
    setStatus("Saved", false);
    await loadSaved();
    $("sim-delete").hidden = false;
  } catch (err) {
    showError(err);
  }
}

async function remove() {
  if (!state.selectedId) return;
  if (!window.confirm(`Delete "${state.name}"?`)) return;
  try {
    await deleteJSON(`/api/simulations/${state.selectedId}`);
    await loadSaved();
    newSimulation();
  } catch (err) {
    showError(err);
  }
}

// ---------- saved list ----------

async function loadSaved() {
  const body = await fetchJSON("/api/simulations");
  state.saved = body.simulations || [];
  renderRail();
}

function renderRail() {
  const list = $("sim-list");
  list.innerHTML = "";
  if (!state.saved.length) {
    list.appendChild(el("li", { class: "empty-state", text: "Nothing saved yet" }));
    return;
  }
  for (const d of state.saved) {
    const li = el("li", { text: d.name, onclick: () => selectSaved(d.simulation_id) });
    if (d.simulation_id === state.selectedId) li.classList.add("selected");
    list.appendChild(li);
  }
}

function loadDefinition(def) {
  state.selectedId = def.simulation_id;
  state.name = def.name;
  state.rules = def.rules.map((r) => ({ ...r }));
  state.dirty = false;
  $("sim-name").value = def.name;
  $("sim-delete").hidden = false;
  clearErrors();
  renderRules();
  renderRail();
  setStatus("", false);
}

async function selectSaved(id) {
  const def = state.saved.find((d) => d.simulation_id === id);
  if (!def) return;
  loadDefinition(def);
  await run();
}

function newSimulation() {
  state.selectedId = null;
  state.name = "";
  state.rules = [{ ...EXAMPLE_RULE }];
  state.dirty = false;
  $("sim-name").value = "";
  $("sim-delete").hidden = true;
  $("sim-results").hidden = true;
  clearErrors();
  renderRules();
  renderRail();
  setStatus("", false);
}

// ---------- results ----------

function table(headers, rows) {
  const thead = el("thead", {}, [el("tr", {}, headers.map((h) => el("th", { text: h })))]);
  const tbody = el("tbody", {}, rows);
  const wrap = el("div", { class: "sim-table-wrap" }, [
    el("table", { class: "sim-table" }, [thead, tbody]),
  ]);
  return wrap;
}

function cell(text, cls) {
  return el("td", { text, class: cls || "" });
}

function renderSummary(container, result) {
  container.innerHTML = "";
  container.appendChild(el("p", { class: "section-label", text: "Actual vs simulated" }));
  const a = result.actual.summary;
  const s = result.simulated.summary;
  const d = result.delta;
  // [label, actualText, simulatedText, deltaValue|null, deltaFormatter, lowerIsBetter]
  const rows = [
    ["Net P&L", fmtMoney(a.total_pnl), fmtMoney(s.total_pnl), d.total_pnl, fmtMoney, false],
    ["Trades", String(a.total_positions), String(s.total_positions), d.total_positions, String, null],
    ["Wins", String(a.wins), String(s.wins), d.wins, String, false],
    ["Losses", String(a.losses), String(s.losses), d.losses, String, true],
    ["Win rate", fmtPercent(a.win_rate), fmtPercent(s.win_rate), d.win_rate, fmtPercent, false],
    ["Profit factor", fmtNum(a.profit_factor), fmtNum(s.profit_factor), d.profit_factor, fmtNum, false],
    ["Avg win", fmtMoney(a.avg_win), fmtMoney(s.avg_win), null, null, null],
    ["Avg loss", fmtMoney(a.avg_loss), fmtMoney(s.avg_loss), null, null, null],
    ["Largest loss", fmtMoney(a.largest_loss), fmtMoney(s.largest_loss), null, null, null],
    ["Max drawdown", fmtMoney(result.actual.max_drawdown), fmtMoney(result.simulated.max_drawdown), d.max_drawdown, fmtMoney, true],
  ].map(([label, av, sv, dv, fmt, lowerIsBetter]) => {
    let deltaText = "—";
    let cls = "";
    if (dv !== null && dv !== undefined) {
      deltaText = fmt(dv);
      if (lowerIsBetter === true) cls = pnlClass(-dv);
      else if (lowerIsBetter === false) cls = pnlClass(dv);
    }
    return el("tr", {}, [cell(label), cell(av), cell(sv), cell(deltaText, cls)]);
  });
  container.appendChild(table(["", "Actual", "Simulated", "Delta"], rows));
  const inp = result.inputs;
  const range = [inp.from_date, inp.to_date].filter(Boolean).join(" to ") || "all dates";
  container.appendChild(
    el("p", {
      class: "sim-rollup",
      text: `${inp.positions_considered} closed trades, ${range}, times in ${inp.display_tz}.`,
    }),
  );
}

function renderEquity(container, result) {
  container.innerHTML = "";
  container.appendChild(el("p", { class: "section-label", text: "Equity: actual vs simulated" }));
  const chartHost = el("div", { class: "chart-container" });
  container.appendChild(chartHost);
  mountLineChart(chartHost, [
    { account: "Actual", points: result.actual.equity },
    { account: "Simulated", points: result.simulated.equity },
  ]);
}

function renderAttribution(container, result) {
  container.innerHTML = "";
  container.appendChild(el("p", { class: "section-label", text: "Rule attribution" }));
  const rows = result.rule_attribution.map((r) =>
    el("tr", {}, [
      cell(`${r.rule_index + 1}. ${r.label}`),
      cell(String(r.fires)),
      cell(String(r.skipped_trades)),
      cell(fmtMoney(r.skipped_pnl), pnlClass(r.skipped_pnl)),
    ]),
  );
  container.appendChild(table(["Rule", "Fires", "Skipped trades", "Skipped P&L"], rows));
}

function renderByDay(container, result) {
  container.innerHTML = "";
  container.appendChild(el("p", { class: "section-label", text: "Days a rule changed" }));
  if (!result.by_day.length) {
    container.appendChild(el("div", { class: "empty-state", text: "No day was affected" }));
    return;
  }
  const rows = result.by_day.map((r) =>
    el("tr", {}, [
      cell(r.session_date),
      cell(fmtMoney(r.actual_pnl), pnlClass(r.actual_pnl)),
      cell(fmtMoney(r.simulated_pnl), pnlClass(r.simulated_pnl)),
      cell(String(r.skipped_count)),
      cell(r.rules_fired.map((i) => i + 1).join(", ")),
    ]),
  );
  container.appendChild(table(["Session", "Actual", "Simulated", "Skipped", "Rules"], rows));
}

function renderSkipped(container, result) {
  container.innerHTML = "";
  container.appendChild(el("p", { class: "section-label", text: "Skipped trades" }));
  const ss = result.skipped_summary;
  container.appendChild(
    el("p", {
      class: "sim-rollup",
      text:
        `${ss.count} skipped: ${ss.losers} losers (${fmtMoney(ss.losers_pnl)}), ` +
        `${ss.winners} winners (${fmtMoney(ss.winners_pnl)}), ${ss.scratches} scratches.`,
    }),
  );
  if (!result.skipped.length) return;
  const rows = result.skipped.map((s) => {
    const href = `/positions/${encodeURIComponent(s.account)}/${encodeURIComponent(
      s.instrument,
    )}/${encodeURIComponent(s.entry_execution_id)}`;
    const link = el("a", { href, text: formatTime(s.entry_time) });
    return el("tr", {}, [
      el("td", {}, [link]),
      cell(s.account),
      cell(s.instrument),
      cell(fmtMoney(s.dollars_pnl), pnlClass(s.dollars_pnl)),
      cell(s.outcome),
      cell(String(s.rule_index + 1)),
    ]);
  });
  container.appendChild(table(["Entry", "Account", "Instrument", "P&L", "Outcome", "Rule"], rows));
}

function renderResults(result) {
  renderSummary($("sim-summary"), result);
  renderEquity($("sim-equity"), result);
  renderAttribution($("sim-attribution"), result);
  renderByDay($("sim-by-day"), result);
  renderSkipped($("sim-skipped"), result);
  $("sim-results").hidden = false;
}

// ---------- boot ----------

async function init() {
  state.vocab = await fetchJSON("/api/simulations/vocabulary");
  renderFilterBar($("sim-filter-bar"), state.filter, (next) => {
    state.filter = next;
    run();
  });
  $("sim-new").addEventListener("click", newSimulation);
  $("sim-add-rule").addEventListener("click", () => {
    state.rules.push({ ...EXAMPLE_RULE });
    markDirty();
    renderRules();
  });
  $("sim-run").addEventListener("click", run);
  $("sim-save").addEventListener("click", save);
  $("sim-delete").addEventListener("click", remove);
  $("sim-name").addEventListener("input", () => {
    readName();
    markDirty();
  });
  await loadSaved();
  newSimulation();
  setText($("sim-status"), "");
}

init().catch(showError);

// Exposed for the static-sentinel test and for debugging in the console.
export { renderRuleRow, filterToQueryString };
