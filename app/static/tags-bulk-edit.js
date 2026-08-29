/* PostWarden — shared "Edit tags" bulk popup, used by both the Journal's
   "Select entries" mode (entries-select.js) and Staging's own "Select"
   mode (staging.js). Adding a chip adds that tag to every checked entry
   that doesn't already have it; removing one drops it from every checked
   entry that does — never a full replace, since different selected
   entries can have different existing tags, and this should only ever
   touch the one tag actually being changed. Applies live, one fetch per
   chip add/remove against POST /entries/tags (shared by both pages: tags
   live on journal_entries/journal_entry_tags regardless of is_staging,
   and that route carries no Journal-only restriction — see its own
   comment in main.py). The popup has no Save button of its own to batch
   a set of changes behind. Tag badges reflecting the change only catch up
   after a reload, which is what closing the popup does if anything
   actually changed — each caller decides what "reload" means for its own
   page (both just use location.reload()).

   Factored out of entries-select.js (Journal-only, originally) once
   Staging grew the identical need — one popup implementation instead of
   two copies that could quietly drift apart, same reasoning as
   period-picker.js's Income Statement -> Cash Flow generalization. */
window.PostWardenBulkTags = (function () {
  function attach({ button, csrfToken, getEntryIds, entryTagsData, endpoint = "/entries/tags" }) {
    if (!button) return;

    let overlay, modalBody, activeEntryIds = [], previousTags = new Set(), changed = false;

    function buildOverlay() {
      overlay = document.createElement("div");
      overlay.className = "confirm-overlay";
      overlay.hidden = true;
      const modal = document.createElement("div");
      modal.className = "confirm-modal";
      modal.setAttribute("role", "dialog");
      modal.setAttribute("aria-label", "Edit tags");
      modalBody = document.createElement("div");
      modal.appendChild(modalBody);
      overlay.appendChild(modal);
      document.body.appendChild(overlay);
      overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) closePopup(); });
      document.addEventListener("keydown", (e) => {
        if (!overlay.hidden && e.key === "Escape") closePopup();
      });
    }

    function postTagChange(entryIds, tag, action) {
      const body = new URLSearchParams();
      body.set("tag", tag);
      body.set("action", action);
      body.set("csrf_token", csrfToken());
      entryIds.forEach((id) => body.append("entry_id", id));
      return fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      })
        .then((r) => r.json())
        .then((data) => { if (!data.ok) console.error("Edit tags:", data.error); })
        .catch((err) => console.error("Edit tags:", err));
    }

    function openPopup() {
      if (!overlay) buildOverlay();
      activeEntryIds = getEntryIds();
      const union = new Set();
      activeEntryIds.forEach((id) => (entryTagsData[id] || []).forEach((t) => union.add(t)));
      previousTags = union;
      changed = false;

      modalBody.innerHTML = "";
      const heading = document.createElement("h3");
      heading.textContent = "Edit Tags";
      modalBody.appendChild(heading);

      const wrap = document.createElement("div");
      wrap.className = "tag-input";
      wrap.dataset.placeholder = "Add a tag…";
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.value = Array.from(union).join(",");
      wrap.appendChild(hidden);
      modalBody.appendChild(wrap);
      window.PostWardenTags.enhance(wrap);

      hidden.addEventListener("change", () => {
        const current = new Set((hidden.value || "").split(",").map((s) => s.trim()).filter(Boolean));
        const added = Array.from(current).filter((t) => !previousTags.has(t));
        const removed = Array.from(previousTags).filter((t) => !current.has(t));
        added.forEach((t) => postTagChange(activeEntryIds, t, "add"));
        removed.forEach((t) => postTagChange(activeEntryIds, t, "remove"));
        previousTags = current;
        changed = true;
      });

      // Same .confirm-actions row the message-and-buttons dialog uses
      // (already flex-start, so this sits at the lower-left of the
      // modal) — just a single Done button here, since every change
      // already applies live as soon as a chip is added or removed.
      const actions = document.createElement("div");
      actions.className = "confirm-actions";
      actions.style.marginTop = "1.1rem";
      const doneBtn = document.createElement("button");
      doneBtn.type = "button";
      doneBtn.className = "confirm-ok";
      doneBtn.textContent = "Done";
      doneBtn.addEventListener("click", closePopup);
      actions.appendChild(doneBtn);
      modalBody.appendChild(actions);

      overlay.hidden = false;
      const input = wrap.querySelector('input[type="text"]');
      if (input) input.focus();
    }

    function closePopup() {
      if (!overlay || overlay.hidden) return;
      overlay.hidden = true;
      if (changed) location.reload();
    }

    button.addEventListener("click", openPopup);
  }

  return { attach };
})();
