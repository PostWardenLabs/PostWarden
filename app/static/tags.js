/* Libro — tag chip input. A hidden input holds the actual comma-separated
   value that submits with the form (or drives the Journal filter); this
   renders it as removable chips plus a text field with autocomplete
   against existing tag names, the same skin-over-a-plain-field pattern
   as combobox.js and datepicker.js. Reuses .combobox-panel/-option
   styling for the suggestion dropdown rather than inventing a new look.

   Suggestions come from a <script type="application/json" id="tags-data">
   tag on the page (see entry_new.html / entries.html); if it isn't there,
   the input still works, just without autocomplete. */
(function () {
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

    const hidden = root.querySelector('input[type="hidden"]');
    const text = document.createElement("input");
    text.type = "text";
    text.autocomplete = "off";
    text.spellcheck = false;
    text.placeholder = root.dataset.placeholder || "Add a tag…";
    root.appendChild(text);

    const panel = document.createElement("div");
    panel.className = "combobox-panel";
    panel.hidden = true;
    root.appendChild(panel);

    let tags = (hidden.value || "").split(",").map((s) => s.trim()).filter(Boolean);
    let filtered = [];

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

    function addTag(raw) {
      const name = raw.trim().toLowerCase();
      text.value = "";
      closePanel();
      if (!name || tags.includes(name)) return;
      tags.push(name);
      sync();
    }

    function renderPanel() {
      const query = text.value.trim().toLowerCase();
      filtered = allTagSuggestions().filter((s) =>
        !tags.includes(s) && (!query || s.includes(query))).slice(0, 8);
      panel.innerHTML = "";
      filtered.forEach((s) => {
        const row = document.createElement("div");
        row.className = "combobox-option";
        row.textContent = s;
        panel.appendChild(row);
      });
      panel.hidden = filtered.length === 0;
    }

    function closePanel() {
      panel.hidden = true;
    }

    text.addEventListener("focus", renderPanel);
    text.addEventListener("input", renderPanel);
    text.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        addTag(text.value);
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
      if (row) addTag(row.textContent);
    });
    document.addEventListener("mousedown", (e) => {
      if (!root.contains(e.target)) closePanel();
    });

    renderChips();
  }

  function enhanceAll(root) {
    (root || document).querySelectorAll(".tag-input:not([data-enhanced])").forEach(enhance);
  }

  document.addEventListener("DOMContentLoaded", () => enhanceAll());
  window.LibroTags = { enhance, enhanceAll };
})();
