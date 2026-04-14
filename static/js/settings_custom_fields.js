const endpoint = "/api/custom-fields";
const list = document.getElementById("fields-list");
const form = document.getElementById("new-field-form");

async function refresh() {
  const res = await fetch(endpoint);
  const body = await res.json();
  list.replaceChildren();
  for (const field of body.fields) {
    list.appendChild(renderField(field));
  }
}

function renderField(field) {
  const wrap = document.createElement("div");
  wrap.className = "field-row";
  wrap.dataset.fieldId = String(field.field_id);

  const name = document.createElement("input");
  name.value = field.name;
  name.addEventListener("blur", () => update(field.field_id, { name: name.value }));

  const typeLabel = document.createElement("span");
  typeLabel.textContent = field.field_type;
  typeLabel.className = "muted";

  const activeToggle = document.createElement("label");
  activeToggle.innerHTML = `<input type="checkbox" ${field.is_active ? "checked" : ""}> Active`;
  activeToggle.querySelector("input").addEventListener("change", (e) => {
    update(field.field_id, { is_active: e.target.checked });
  });

  const delBtn = document.createElement("button");
  delBtn.textContent = "Delete";
  delBtn.addEventListener("click", () => remove(field.field_id));

  wrap.append(name, typeLabel, activeToggle, delBtn);

  if (field.field_type === "dropdown") {
    wrap.appendChild(renderOptionsEditor(field.field_id));
  }
  return wrap;
}

function renderOptionsEditor(fieldId) {
  const container = document.createElement("div");
  container.className = "options-editor";
  const textarea = document.createElement("textarea");
  textarea.placeholder = "One option per line";
  textarea.rows = 4;
  container.appendChild(textarea);
  const saveBtn = document.createElement("button");
  saveBtn.textContent = "Save options";
  container.appendChild(saveBtn);

  fetch(`${endpoint}/${fieldId}/options`).then((r) => r.json()).then((body) => {
    textarea.value = body.options.map((o) => o.value).join("\n");
  });

  saveBtn.addEventListener("click", async () => {
    const options = textarea.value
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
      .map((value, idx) => ({ value, display_order: idx }));
    const res = await fetch(`${endpoint}/${fieldId}/options`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ options }),
    });
    if (!res.ok) alert("Save failed");
  });
  return container;
}

async function create(event) {
  event.preventDefault();
  const payload = {
    name: form.elements.name.value,
    field_type: form.elements.field_type.value,
  };
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.json();
    alert(`Create failed: ${body.error || res.status}`);
    return;
  }
  form.reset();
  await refresh();
}

async function update(fieldId, patch) {
  const res = await fetch(`${endpoint}/${fieldId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const body = await res.json();
    alert(`Update failed: ${body.error || res.status}`);
  }
}

async function remove(fieldId) {
  const peek = await fetch(`${endpoint}/${fieldId}`, { method: "DELETE" });
  if (peek.status === 204) {
    await refresh();
    return;
  }
  const body = await peek.json();
  const n = body.affected_executions ?? 0;
  if (!confirm(`This field has values on ${n} executions. Delete anyway?`)) return;
  const res = await fetch(`${endpoint}/${fieldId}?confirm_count=${n}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    alert("Delete failed");
    return;
  }
  await refresh();
}

form.addEventListener("submit", create);
refresh();
