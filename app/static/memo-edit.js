/* PostWarden — Journal line memo, click-to-edit. Clicking a .memo-cell
   swaps its text for a plain <input> in place; Enter or blur saves via
   fetch to /entries/lines/{id}/edit-memo (no page navigation, same
   fetch-driven shape as entries-select.js's own Edit tags popup),
   Escape cancels and restores the original text unchanged. Every
   .memo-cell on the page wires up independently (there can be many, one
   per line, across many expanded entries) — a memo is one small input,
   not a whole grid, so there's no shared "currently editing" state to
   track the way staging-inline-edit.js's grid needs.

   Deliberately not entity-manage.js's own click-to-edit shape (a real
   rename <form>, Enter does a normal POST + flash-redirect, no fetch at
   all) even though the two look like the same interaction from the
   outside. That shape is the right one for Payees/Tags, a flat list of
   top-level rows where a full-page reload after a rename costs nothing.
   It's the wrong one here: a memo lives inside one of potentially many
   expanded `<details>` entry panels, and `<details open>` state isn't
   preserved across a server round trip — a real POST would silently
   collapse every entry the user had open (and reset scroll position)
   just to save one line's memo. Fetch, matching Edit tags' own
   reasoning on this exact page, avoids that entirely. */
(function () {
  // Any hidden csrf_token input already on the page carries the same
  // session-wide value — the Journal renders one per entry's own Edit
  // description form, so there's always at least one to read from
  // without this file needing its own.
  const csrfInput = document.querySelector('input[name="csrf_token"]');
  const csrfToken = () => (csrfInput ? csrfInput.value : "");

  function render(cell, text) {
    cell.textContent = "";
    const span = document.createElement("span");
    span.className = "memo-text" + (text ? "" : " memo-empty italic");
    span.textContent = text || "Add memo";
    cell.appendChild(span);
  }

  function startEdit(cell) {
    if (cell.querySelector("input")) return; // already editing this cell
    const span = cell.querySelector(".memo-text");
    const original = span.classList.contains("memo-empty") ? "" : span.textContent;

    const input = document.createElement("input");
    input.type = "text";
    input.className = "memo-input";
    input.value = original;
    input.maxLength = 200;
    cell.textContent = "";
    cell.appendChild(input);
    input.focus();
    input.select();

    let done = false;
    function cancel() {
      done = true;
      render(cell, original);
    }
    function save() {
      if (done) return;
      const value = input.value.trim();
      if (value === original) { done = true; render(cell, original); return; }
      done = true;
      const body = new URLSearchParams();
      body.set("memo", value);
      body.set("csrf_token", csrfToken());
      fetch(`/entries/lines/${cell.dataset.lineId}/edit-memo`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.ok) render(cell, data.memo);
          else { console.error("Edit memo:", data.error); render(cell, original); }
        })
        .catch((err) => { console.error("Edit memo:", err); render(cell, original); });
    }

    input.addEventListener("blur", save);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); input.blur(); }
      else if (e.key === "Escape") { e.preventDefault(); cancel(); }
    });
  }

  // Delegated on document, not one listener per cell: every entry's
  // lines are already server-rendered at page load (each `<details>`
  // just hides its own content natively until expanded, nothing fetched
  // on click), so a plain querySelectorAll('.memo-cell') here would
  // work too — delegation is still the better default, the same
  // resilient pattern every other page-wide click handler in this app
  // uses, so nothing needs re-wiring if that ever changes.
  document.addEventListener("click", (e) => {
    const cell = e.target.closest(".memo-cell");
    if (cell) startEdit(cell);
  });
})();
