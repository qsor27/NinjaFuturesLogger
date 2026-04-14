export function mountCustomFields(container, detailPayload, entryExecutionId) {
  container.replaceChildren();
  const cf = detailPayload.custom_fields || {};
  const definitions = cf.definitions || [];
  const entry = cf.entry || {};
  const perExecution = cf.per_execution || [];

  if (definitions.length === 0 && perExecution.length === 0) {
    return;
  }

  const h = document.createElement("h2");
  h.textContent = "Custom fields";
  container.appendChild(h);

  const form = document.createElement("form");
  form.className = "custom-fields-form";
  form.addEventListener("submit", (e) => e.preventDefault());
  for (const def of definitions) {
    const label = document.createElement("label");
    label.className = "custom-field-label";
    const labelText = document.createElement("span");
    labelText.textContent = def.name;
    label.appendChild(labelText);
    const input = buildInput(def, entry[String(def.field_id)]);
    const persist = () =>
      saveValue(entryExecutionId, def.field_id, extractValue(input, def.field_type));
    input.addEventListener("change", persist);
    input.addEventListener("blur", persist);
    label.appendChild(input);
    form.appendChild(label);
  }
  container.appendChild(form);

  if (perExecution.length > 0) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = `Per-execution values (${perExecution.length})`;
    details.appendChild(summary);
    const table = buildPerExecutionTable(definitions, perExecution);
    details.appendChild(table);
    container.appendChild(details);
  }
}

function buildInput(def, currentValue) {
  if (def.field_type === "text") {
    const i = document.createElement("input");
    i.type = "text";
    if (currentValue !== undefined) i.value = currentValue;
    return i;
  }
  if (def.field_type === "number") {
    const i = document.createElement("input");
    i.type = "number";
    i.step = "any";
    if (currentValue !== undefined) i.value = String(currentValue);
    return i;
  }
  if (def.field_type === "date") {
    const i = document.createElement("input");
    i.type = "date";
    if (currentValue !== undefined) i.value = currentValue;
    return i;
  }
  if (def.field_type === "boolean") {
    const i = document.createElement("input");
    i.type = "checkbox";
    if (currentValue === true) i.checked = true;
    return i;
  }
  if (def.field_type === "dropdown") {
    const s = document.createElement("select");
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "—";
    s.appendChild(blank);
    s.addEventListener("focus", async () => {
      if (s.dataset.loaded === "1") return;
      const res = await fetch(`/api/custom-fields/${def.field_id}/options`);
      const body = await res.json();
      for (const o of body.options) {
        const opt = document.createElement("option");
        opt.value = o.value;
        opt.textContent = o.value;
        s.appendChild(opt);
      }
      if (currentValue !== undefined) s.value = currentValue;
      s.dataset.loaded = "1";
    });
    return s;
  }
  const fallback = document.createElement("input");
  fallback.type = "text";
  return fallback;
}

function extractValue(input, fieldType) {
  if (fieldType === "boolean") return input.checked;
  if (fieldType === "number") return input.value === "" ? "" : parseFloat(input.value);
  return input.value;
}

async function saveValue(executionId, fieldId, value) {
  const res = await fetch(
    `/api/executions/${encodeURIComponent(executionId)}/custom-fields/${fieldId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    }
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    alert(`Save failed: ${body.error || res.status}`);
  }
}

function buildPerExecutionTable(definitions, perExecution) {
  const table = document.createElement("table");
  table.className = "per-execution-table";
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  const eidTh = document.createElement("th");
  eidTh.textContent = "Execution";
  headerRow.appendChild(eidTh);
  for (const def of definitions) {
    const th = document.createElement("th");
    th.textContent = def.name;
    headerRow.appendChild(th);
  }
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const row of perExecution) {
    const tr = document.createElement("tr");
    const eidTd = document.createElement("td");
    eidTd.textContent = row.execution_id;
    tr.appendChild(eidTd);
    for (const def of definitions) {
      const td = document.createElement("td");
      const v = row.values[String(def.field_id)];
      td.textContent = v === undefined ? "" : String(v);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  return table;
}
