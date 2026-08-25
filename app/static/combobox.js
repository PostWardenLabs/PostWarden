/* PostWarden — searchable combobox, progressively enhancing a plain <select>.
   Every <select> on the page gets this automatically (see enhanceAll()
   below); dynamically-created selects (the account picker's per-line
   dropdown — see app.js) call PostWardenCombobox.enhance() themselves.

   The original <select> stays in the DOM (display:none) and stays the
   thing that actually submits with the form — this is a UI skin, not a
   new source of truth. Existing `change` listeners on the select (the
   scenario picker's balance recalc, the theme picker) keep working
   unchanged, since selecting an option here just sets select.value and
   dispatches a real "change" event. */
(function () {
  function enhanceSelect(select) {
    if (select.dataset.enhanced) return;
    select.dataset.enhanced = "1";

    const wrap = document.createElement("div");
    wrap.className = "combobox";
    select.insertAdjacentElement("beforebegin", wrap);
    wrap.appendChild(select);
    select.classList.add("combobox-native");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");

    const input = document.createElement("input");
    input.type = "text";
    input.className = "combobox-input";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-autocomplete", "list");
    if (select.disabled) input.disabled = true;
    wrap.appendChild(input);

    const panel = document.createElement("div");
    panel.className = "combobox-panel";
    panel.setAttribute("role", "listbox");
    panel.hidden = true;
    wrap.appendChild(panel);

    let filtered = [];
    let activeIndex = -1;

    // Optional "+ Create <name>" row — see entry_new.html's payee <select>
    // (data-create-url points at a POST endpoint returning {ok, id, name}).
    // Only single-value creatable selects are supported; multi-value
    // pick-or-create lives in tags.js, which has its own chip UI.
    const createUrl = select.dataset.createUrl || null;

    function options() {
      return Array.from(select.options);
    }

    function labelFor(opt) {
      if (opt.__create) return "+ Create “" + opt.query + "”";
      return opt.textContent.trim();
    }

    function syncInputFromSelect() {
      const opt = select.options[select.selectedIndex];
      input.value = opt ? labelFor(opt) : "";
    }

    function updateActive() {
      Array.from(panel.children).forEach((el, i) => {
        el.classList.toggle("active", i === activeIndex);
      });
      const activeEl = panel.children[activeIndex];
      if (activeEl) activeEl.scrollIntoView({ block: "nearest" });
    }

    function renderPanel(filterText) {
      const q = (filterText || "").trim();
      const qLower = q.toLowerCase();
      filtered = options().filter((o) => labelFor(o) &&
        (!qLower || labelFor(o).toLowerCase().includes(qLower)));
      if (createUrl && q) {
        const exact = options().some((o) => labelFor(o).toLowerCase() === qLower);
        if (!exact) filtered = filtered.concat([{ __create: true, query: q, value: "" }]);
      }
      panel.innerHTML = "";
      if (!filtered.length) {
        const empty = document.createElement("div");
        empty.className = "combobox-empty";
        empty.textContent = "No matches";
        panel.appendChild(empty);
      } else {
        filtered.forEach((o) => {
          const row = document.createElement("div");
          row.className = "combobox-option" +
            (o.value === select.value ? " selected" : "") +
            (o.__create ? " combobox-create" : "");
          row.setAttribute("role", "option");
          row.textContent = labelFor(o);
          panel.appendChild(row);
        });
      }
      activeIndex = filtered.findIndex((o) => o.value === select.value);
      // Nothing currently selected (or the selected option got filtered
      // out) — default to the first match, so typing-then-Enter picks the
      // best match instead of doing nothing.
      if (activeIndex === -1 && filtered.length) activeIndex = 0;
      updateActive();
    }

    function open(filterText) {
      renderPanel(filterText || "");
      if (panel.hidden) {
        panel.hidden = false;
        input.setAttribute("aria-expanded", "true");
        document.addEventListener("mousedown", onDocMouseDown, true);
      }
    }

    function close() {
      if (panel.hidden) return;
      panel.hidden = true;
      input.setAttribute("aria-expanded", "false");
      syncInputFromSelect();
      document.removeEventListener("mousedown", onDocMouseDown, true);
    }

    function onDocMouseDown(e) {
      if (!wrap.contains(e.target)) close();
    }

    function csrfToken() {
      const el = document.querySelector('input[name="csrf_token"]');
      return el ? el.value : "";
    }

    function selectOption(opt) {
      if (opt.__create) { createAndSelect(opt.query); return; }
      const changed = select.value !== opt.value;
      select.value = opt.value;
      if (changed) select.dispatchEvent(new Event("change", { bubbles: true }));
      syncInputFromSelect();
      close();
    }

    function createAndSelect(name) {
      input.disabled = true;
      panel.innerHTML = "";
      const loading = document.createElement("div");
      loading.className = "combobox-empty";
      loading.textContent = "Creating…";
      panel.appendChild(loading);
      fetch(createUrl, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ name, csrf_token: csrfToken() }),
      })
        .then((r) => r.json())
        .then((data) => {
          input.disabled = false;
          if (!data.ok) { renderCreateError(data.error || "Couldn't create"); return; }
          const opt = document.createElement("option");
          opt.value = data.id;
          opt.textContent = data.name;
          select.appendChild(opt);
          selectOption(opt);
        })
        .catch(() => {
          input.disabled = false;
          renderCreateError("Couldn't reach the server");
        });
    }

    function renderCreateError(message) {
      panel.innerHTML = "";
      const err = document.createElement("div");
      err.className = "combobox-empty combobox-error";
      err.textContent = message;
      panel.appendChild(err);
    }

    input.addEventListener("focus", () => {
      input.select();
      open();
    });
    input.addEventListener("click", () => open());
    input.addEventListener("input", () => open(input.value));
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (panel.hidden) { open(); return; }
        activeIndex = Math.min(activeIndex + 1, filtered.length - 1);
        updateActive();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        updateActive();
      } else if (e.key === "Enter") {
        if (!panel.hidden && filtered[activeIndex]) {
          e.preventDefault();
          selectOption(filtered[activeIndex]);
        }
      } else if (e.key === "Escape") {
        if (!panel.hidden) { e.preventDefault(); close(); }
      } else if (e.key === "Tab") {
        close();
      }
    });
    panel.addEventListener("mousedown", (e) => {
      e.preventDefault(); // don't steal focus from the input mid-click
      const row = e.target.closest(".combobox-option");
      if (!row) return;
      const idx = Array.from(panel.children).indexOf(row);
      if (filtered[idx]) selectOption(filtered[idx]);
    });

    syncInputFromSelect();
    // Exposes the sync this instance already does on its own click/keyboard
    // paths — for code elsewhere that changes select.value or rebuilds its
    // <option>s programmatically (see app.js's refreshAccountsForScenario())
    // and needs the visible text to catch up, since nothing here is
    // listening for that kind of external mutation.
    select.__libroComboboxSync = syncInputFromSelect;
  }

  function enhanceAll(root) {
    (root || document).querySelectorAll("select:not([data-enhanced])").forEach(enhanceSelect);
  }

  function resync(select) {
    if (select && select.__libroComboboxSync) select.__libroComboboxSync();
  }

  document.addEventListener("DOMContentLoaded", () => enhanceAll());
  window.PostWardenCombobox = { enhance: enhanceSelect, enhanceAll, resync };
})();
