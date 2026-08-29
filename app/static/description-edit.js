/* PostWarden — Entry description, click-to-edit. Same shape as
   memo-edit.js (click swaps the text for a plain <input> in place,
   autosaves on a 600ms debounce while typing, blur/Enter commits,
   Escape reverts — including a corrective POST if a debounced draft
   already reached the server, so cancelling mid-edit still means
   cancel), applied to .description-cell instead of .memo-cell, on both
   the Journal and Staging (BACKLOG.md's own "make description
   click-to-edit on both, remove the now-unnecessary input box on the
   Journal" — that always-visible form is gone; this is what replaced
   it).

   Deliberately a second, parallel file rather than one shared
   abstraction with memo-edit.js. Two differences big enough to matter:

   1. This lives inside <summary> (see entries.html/staging.html for
      why .description-cell nests inside the summary's existing single
      grid-item <span> instead of being a sibling of it). Clicking it
      must not also toggle the parent <details> — summary's native
      "click anywhere inside toggles the panel" behavior is cancelled
      with e.preventDefault() in the delegated click listener below,
      the documented way to stop a details/summary toggle; the memo
      table lives in the entry's *body*, never inside <summary> at all,
      so memo-edit.js has never needed this.
   2. A description can never be saved blank (already enforced server-
      side) — save()/autosave() below just treat an emptied field as a
      cancel rather than letting a doomed request round-trip only to
      come back rejected.

   Two files this close in shape is exactly the amount of duplication
   worth keeping simple rather than abstracting; a third such widget
   would be the point to actually factor one out. */
(function () {
  const AUTOSAVE_DEBOUNCE_MS = 600;

  const csrfInput = document.querySelector('input[name="csrf_token"]');
  const csrfToken = () => (csrfInput ? csrfInput.value : "");

  function postDescription(entryId, value) {
    const body = new URLSearchParams();
    body.set("description", value);
    body.set("csrf_token", csrfToken());
    return fetch(`/entries/${entryId}/edit-description`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body,
    }).then((r) => r.json());
  }

  function startEdit(cell) {
    if (cell.querySelector("input")) return; // already editing this cell
    const original = cell.textContent.trim();
    const entryId = cell.dataset.entryId;

    const input = document.createElement("input");
    input.type = "text";
    input.className = "description-input";
    input.value = original;
    input.maxLength = 500;
    cell.textContent = "";
    cell.appendChild(input);
    input.focus();
    input.select();

    // Same onServer/autosave-then-corrective-cancel shape as
    // memo-edit.js's own startEdit — see its file comment for the full
    // reasoning (the iPad bug this pattern exists to survive).
    let onServer = original;
    let autosaveTimer = null;
    let done = false;

    function clearAutosaveTimer() {
      if (autosaveTimer) { clearTimeout(autosaveTimer); autosaveTimer = null; }
    }

    function autosave() {
      autosaveTimer = null;
      if (done) return;
      const value = input.value.trim();
      if (!value || value === onServer) return; // never autosave blank
      postDescription(entryId, value)
        .then((data) => { if (data.ok) onServer = value; })
        .catch(() => {});
    }

    function cancel() {
      done = true;
      clearAutosaveTimer();
      if (onServer !== original) postDescription(entryId, original).catch(() => {});
      cell.textContent = original;
    }

    function save() {
      if (done) return;
      done = true;
      clearAutosaveTimer();
      const value = input.value.trim();
      if (!value) { // can't save blank — same outcome as cancel()
        if (onServer !== original) postDescription(entryId, original).catch(() => {});
        cell.textContent = original;
        return;
      }
      if (value === onServer) { cell.textContent = value; return; }
      postDescription(entryId, value)
        .then((data) => {
          if (data.ok) cell.textContent = data.description;
          else { console.error("Edit description:", data.error); cell.textContent = onServer; }
        })
        .catch((err) => { console.error("Edit description:", err); cell.textContent = onServer; });
    }

    input.addEventListener("input", () => {
      clearAutosaveTimer();
      autosaveTimer = setTimeout(autosave, AUTOSAVE_DEBOUNCE_MS);
    });
    input.addEventListener("blur", save);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); input.blur(); }
      else if (e.key === "Escape") { e.preventDefault(); cancel(); }
    });
  }

  document.addEventListener("click", (e) => {
    const cell = e.target.closest(".description-cell");
    if (!cell) return;
    // Stop <summary>'s native toggle — see file comment above.
    e.preventDefault();
    startEdit(cell);
  });
})();
