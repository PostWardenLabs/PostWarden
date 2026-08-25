/* PostWarden — tag chip input. A hidden input holds the actual comma-separated
   value that submits with the form (or drives the Journal filter); this
   renders it as removable pill chips plus a text field that behaves like
   combobox.js's picker rather than a free-text box: typing filters a list
   of existing tags, and only selecting a row (via click, Enter, or comma)
   adds it — arrow keys move a highlighted "active" row exactly like the
   account/payee combobox. A tag that doesn't exist yet shows as a
   "+ Create tag "…"" row instead of being silently accepted, same pattern
   combobox.js uses for creatable single-value fields (see its
   data-create-url), except tags are created for real lazily at whatever
   form submits them (_sync_entry_tags upserts by name) rather than over
   the network here — nothing to roll back if the form is abandoned.

   Suggestions come from a <script type="application/json" id="tags-data">
   tag on the page (see entry_new.html / entries.html); if it isn't there,
   the input still works, just without autocomplete or the ability to
   create a genuinely new tag (nothing to validate a new name against).

   Set data-creatable="0" on the root .tag-input to disable the "+ Create"
   row entirely — the Journal filter bar's tag field uses this, since
   filtering by a tag that doesn't exist yet is meaningless. */
(function () {
  const TAG_PATTERN = /^[a-z0-9][a-z0-9 _-]{0,39}$/;
  let suggestions = null;
  function allTagSuggestions() {
    if (suggestions) return suggestions;
    try {
      const el = document.getElementById("tags-data");
      suggestions = el ? JSON.parse(el.textContent || "[]") : [];
    } catch (e) {
      suggestions = [];
    }
    return suggestions;
  }

  function enhance(root) {
    if (root.dataset.enhanced) return;
    root.dataset.enhanced = "1";
    const creatable = root.dataset.creatable !== "0";

    const hidden = root.querySelector('input[type="hidden"]');
    const text = document.createElement("input");
    text.type = "text";
    text.autocomplete = "off";
    text.spellcheck = false;
    text.setAttribute("role", "combobox");
    text.setAttribute("aria-expanded", "false");
    text.placeholder = root.dataset.placeholder || "Add a tag…";
    root.appendChild(text);

    const panel = document.createElement("div");
    panel.className = "combobox-panel";
    panel.setAttribute("role", "listbox");
    panel.hidden = true;
    root.appendChild(panel);

    let tags = (hidden.value || "").split(",").map((s) => s.trim()).filter(Boolean);
    let filtered = [];
    let activeIndex = -1;

    function sync() {
      hidden.value = tags.join(",");
      hidden.dispatchEvent(new Event("change", { bubbles: true }));
      renderChips();
    }

    function renderChips() {
      root.querySelectorAll(".tag-chip").forEach((el) => el.remove());
      tags.forEach((t, i) => {
        const chip = document.createElement("span");
        chip.className = "tag-chip";
        chip.textContent = t;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "tag-chip-remove";
        remove.textContent = "×";
        remove.setAttribute("aria-label", "Remove tag " + t);
        remove.addEventListener("click", () => {
          tags.splice(i, 1);
          sync();
        });
        chip.appendChild(remove);
        root.insertBefore(chip, text);
      });
    }

    function addTag(name) {
      text.value = "";
      closePanel();
      if (!name || tags.includes(name)) return;
      tags.push(name);
      if (!allTagSuggestions().includes(name)) suggestions = allTagSuggestions().concat([name]);
      sync();
    }

    function updateActive() {
      Array.from(panel.children).forEach((el, i) => {
        el.classList.toggle("active", i === activeIndex);
      });
      const activeEl = panel.children[activeIndex];
      if (activeEl) activeEl.scrollIntoView({ block: "nearest" });
    }

    function renderPanel() {
      const q = text.value.trim().toLowerCase();
      filtered = allTagSuggestions().filter((s) =>
        !tags.includes(s) && (!q || s.includes(q)));
      const exact = allTagSuggestions().some((s) => s === q);
      let invalidReason = null;
      if (creatable && q && !exact && !tags.includes(q)) {
        if (TAG_PATTERN.test(q)) {
          filtered = filtered.concat([{ __create: true, query: q }]);
        } else {
          invalidReason = "Only lowercase letters, numbers, spaces, - and _, max 40 chars";
        }
      }
      panel.innerHTML = "";
      if (!filtered.length) {
        const empty = document.createElement("div");
        empty.className = "combobox-empty" + (invalidReason ? " combobox-error" : "");
        empty.textContent = invalidReason || "No matches";
        panel.appendChild(empty);
      } else {
        filtered.forEach((item) => {
          const row = document.createElement("div");
          const isCreate = typeof item === "object";
          row.className = "combobox-option" + (isCreate ? " combobox-create" : "");
          row.setAttribute("role", "option");
          row.textContent = isCreate ? "+ Create tag “" + item.query + "”" : item;
          panel.appendChild(row);
        });
      }
      activeIndex = filtered.length ? 0 : -1;
      updateActive();
    }

    function openPanel() {
      renderPanel();
      panel.hidden = false;
      text.setAttribute("aria-expanded", "true");
    }

    function closePanel() {
      panel.hidden = true;
      text.setAttribute("aria-expanded", "false");
    }

    function selectActive() {
      const item = filtered[activeIndex];
      if (!item) return;
      addTag(typeof item === "object" ? item.query : item);
    }

    text.addEventListener("focus", openPanel);
    text.addEventListener("input", openPanel);
    text.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (panel.hidden) { openPanel(); return; }
        activeIndex = Math.min(activeIndex + 1, filtered.length - 1);
        updateActive();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        updateActive();
      } else if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        if (!panel.hidden) selectActive();
      } else if (e.key === "Backspace" && !text.value && tags.length) {
        tags.pop();
        sync();
      } else if (e.key === "Escape" && !panel.hidden) {
        e.preventDefault();
        closePanel();
      }
    });
    panel.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const row = e.target.closest(".combobox-option");
      if (!row) return;
      const idx = Array.from(panel.children).indexOf(row);
      activeIndex = idx;
      selectActive();
    });
    document.addEventListener("mousedown", (e) => {
      if (!root.contains(e.target)) closePanel();
    });

    // Exposes this instance's tag list to external scripts — see
    // entry_templates.js's "Load template", which needs to replace the
    // whole set at once the same way picking a saved template replaces
    // every other field on the form.
    root.__postwardenTags = {
      setValue(csv) {
        tags = (csv || "").split(",").map((s) => s.trim()).filter(Boolean);
        sync();
      },
    };

    renderChips();
  }

  function enhanceAll(root) {
    (root || document).querySelectorAll(".tag-input:not([data-enhanced])").forEach(enhance);
  }

  document.addEventListener("DOMContentLoaded", () => enhanceAll());
  window.PostWardenTags = { enhance, enhanceAll };
})();
