// MultiSelect — reusable checkbox dropdown.
// Pure helpers live at the top of the file (DOM-/fetch-/library-free,
// exported for future test runners). The createMultiSelect factory wires
// the DOM.

export function computeLabel(selected, allOptions, allLabel) {
  const uniq = Array.from(new Set(selected));
  if (uniq.length === 0) return allLabel;
  if (allOptions.length > 0 && uniq.length === allOptions.length) {
    const allPresent = allOptions.every((o) => uniq.includes(o));
    if (allPresent) return allLabel;
  }
  if (uniq.length === 1) return uniq[0];
  if (uniq.length === 2) return uniq.join(", ");
  return `${uniq.length} accounts`;
}

export function normalizeSelection(selected, allOptions) {
  const allowed = new Set(allOptions);
  const seen = new Set();
  const out = [];
  for (const s of selected || []) {
    if (typeof s !== "string") continue;
    if (!allowed.has(s)) continue;
    if (seen.has(s)) continue;
    seen.add(s);
    out.push(s);
  }
  return out;
}

export function createMultiSelect(container, opts) {
  const {
    options: initialOptions = [],
    selected: initialSelected = [],
    label = "",
    allLabel = "All",
    onChange = () => {},
  } = opts;

  let options = [...initialOptions];
  let selected = normalizeSelection(initialSelected, options);

  container.classList.add("multiselect");
  container.innerHTML = "";

  const button = document.createElement("button");
  button.type = "button";
  button.className = "multiselect-button";
  button.setAttribute("aria-haspopup", "listbox");
  button.setAttribute("aria-expanded", "false");
  if (label) button.setAttribute("aria-label", label);

  const panel = document.createElement("div");
  panel.className = "multiselect-panel";
  panel.setAttribute("role", "listbox");
  panel.hidden = true;

  const shortcuts = document.createElement("div");
  shortcuts.className = "multiselect-shortcuts";
  const allBtn = document.createElement("button");
  allBtn.type = "button";
  allBtn.textContent = "All";
  const noneBtn = document.createElement("button");
  noneBtn.type = "button";
  noneBtn.textContent = "None";
  shortcuts.appendChild(allBtn);
  shortcuts.appendChild(noneBtn);
  panel.appendChild(shortcuts);

  const optionList = document.createElement("div");
  panel.appendChild(optionList);

  container.appendChild(button);
  container.appendChild(panel);

  const renderButton = () => {
    button.textContent = computeLabel(selected, options, allLabel);
  };

  const renderOptions = () => {
    optionList.innerHTML = "";
    for (const opt of options) {
      const row = document.createElement("label");
      row.className = "multiselect-option";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = opt;
      cb.checked = selected.includes(opt);
      cb.addEventListener("change", () => {
        if (cb.checked) {
          if (!selected.includes(opt)) selected.push(opt);
        } else {
          selected = selected.filter((s) => s !== opt);
        }
        renderButton();
        onChange([...selected]);
      });
      const text = document.createElement("span");
      text.textContent = opt;
      row.appendChild(cb);
      row.appendChild(text);
      optionList.appendChild(row);
    }
  };

  const onDocMouseDown = (e) => { if (!container.contains(e.target)) close(); };
  const onDocKeyDown = (e) => { if (e.key === "Escape") { close(); button.focus(); } };

  const open = () => {
    panel.hidden = false;
    button.setAttribute("aria-expanded", "true");
    document.addEventListener("mousedown", onDocMouseDown, true);
    document.addEventListener("keydown", onDocKeyDown, true);
  };
  const close = () => {
    panel.hidden = true;
    button.setAttribute("aria-expanded", "false");
    document.removeEventListener("mousedown", onDocMouseDown, true);
    document.removeEventListener("keydown", onDocKeyDown, true);
  };

  button.addEventListener("click", () => { panel.hidden ? open() : close(); });

  allBtn.addEventListener("click", () => {
    selected = [...options];
    renderOptions();
    renderButton();
    onChange([...selected]);
  });
  noneBtn.addEventListener("click", () => {
    selected = [];
    renderOptions();
    renderButton();
    onChange([...selected]);
  });

  renderOptions();
  renderButton();

  return {
    getSelected: () => [...selected],
    setSelected: (next) => {
      selected = normalizeSelection(next, options);
      renderOptions();
      renderButton();
    },
    setOptions: (nextOptions) => {
      options = [...nextOptions];
      selected = normalizeSelection(selected, options);
      renderOptions();
      renderButton();
    },
    destroy: () => {
      close();
      container.innerHTML = "";
      container.classList.remove("multiselect");
    },
  };
}
