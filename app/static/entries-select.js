/* PostWarden — Journal "select entries" mode. Hidden by default (see
   .select-only in style.css); "Select entries" reveals a checkbox per
   entry and the bar above it, same mechanism Staging's own bulk actions
   already use — "select all", Reverse/Edit tags disabled until
   something's checked, Alt+R as Reverse's keyboard shortcut. Reverse
   confirms via confirm.js's ask() with a count-aware message (same
   pattern as Staging's Approve/Reject) before actually submitting.
   Edit tags opens a popup styled like that same confirm dialog (same
   .confirm-overlay/.confirm-modal), but holding the tag-picker pill box
   from New entry instead of a message and buttons — see the bottom of
   this file. */
(function () {
  const form = document.getElementById("entries-select-form");
  if (!form) return;
  const toggle = document.getElementById("select-toggle");
  const selectAll = document.getElementById("select-all");
  const reverseBtn = document.getElementById("reverse-btn");
  const editTagsBtn = document.getElementById("edit-tags-btn");
  // document-wide, not form.querySelectorAll: each checkbox is
  // associated with the form via its own form="entries-select-form"
  // attribute rather than DOM nesting (the form wraps only the
  // toolbar — see entries.html's own comment on why), so it isn't a
  // descendant of `form` and querySelectorAll scoped to `form` would
  // never find it.
  const checks = Array.from(document.querySelectorAll(".entry-check"));

  function sync() {
    const checkedCount = checks.filter((c) => c.checked).length;
    if (reverseBtn) reverseBtn.disabled = checkedCount === 0;
    if (editTagsBtn) editTagsBtn.disabled = checkedCount === 0;
    if (selectAll) {
      selectAll.checked = checkedCount === checks.length && checks.length > 0;
      selectAll.indeterminate = checkedCount > 0 && checkedCount < checks.length;
    }
  }

  function setSelectMode(on) {
    form.classList.toggle("select-mode", on);
    toggle.textContent = on ? "Cancel selecting" : "Select entries";
    if (!on) {
      checks.forEach((c) => { c.checked = false; });
      if (selectAll) { selectAll.checked = false; selectAll.indeterminate = false; }
      sync();
    }
  }

  toggle.addEventListener("click", () => setSelectMode(!form.classList.contains("select-mode")));

  if (selectAll) {
    selectAll.addEventListener("change", () => {
      checks.forEach((c) => { c.checked = selectAll.checked; });
      sync();
    });
  }
  checks.forEach((c) => c.addEventListener("change", sync));
  sync();

  document.addEventListener("keydown", (e) => {
    if (e.altKey && e.code === "KeyR" && reverseBtn) {
      e.preventDefault();
      reverseBtn.click();
    }
  });

  // Same shape as Staging's Approve/Reject: the message depends on how
  // many entries are checked, computed right when it's needed, so it
  // can't be a static data-confirm attribute — calls ask() directly,
  // then resubmits itself once confirmed.
  form.addEventListener("submit", (e) => {
    // A dedicated flag, not confirm.js's own confirmBypass — this form
    // carries no data-confirm attribute itself, so confirm.js's generic
    // handler never touches it, but a distinct name keeps that true on
    // purpose rather than by coincidence.
    if (form.dataset.reverseConfirmBypass === "1") { delete form.dataset.reverseConfirmBypass; return; }
    e.preventDefault();
    const n = checks.filter((c) => c.checked).length;
    const msg = n === 1
      ? "Are you sure you want to post a reversal for this entry? You can't delete a posted entry, only reverse it."
      : `Are you sure you want to post a reversal for these ${n} entries? You can't delete a posted entry, only reverse it.`;
    window.PostWardenConfirm.ask(msg).then((confirmed) => {
      if (!confirmed) return;
      form.dataset.reverseConfirmBypass = "1";
      form.requestSubmit(e.submitter || undefined);
    });
  });

  // -- Edit tags (bulk) ----------------------------------------------------
  // Adding a chip here adds that tag to every checked entry that doesn't
  // already have it; removing one drops it from every checked entry that
  // does — never a full replace, since different selected entries can
  // have different existing tags and this should only ever touch the one
  // tag actually being changed. Applies live, one fetch per chip add/
  // remove, since the popup has no Save button of its own to batch a set
  // of changes behind (see the module comment up top). Tag badges next
  // to each entry only reflect that after a reload, which is what
  // closing the popup does if anything actually changed.
  if (editTagsBtn) {
    const entryTagsData = JSON.parse(
      (document.getElementById("entry-tags-data") || {}).textContent || "{}");
    const csrfInput = form.querySelector('input[name="csrf_token"]');
    const csrfToken = () => (csrfInput ? csrfInput.value : "");

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
      return fetch("/entries/tags", {
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
      activeEntryIds = checks.filter((c) => c.checked).map((c) => c.value);
      const union = new Set();
      activeEntryIds.forEach((id) => (entryTagsData[id] || []).forEach((t) => union.add(t)));
      previousTags = union;
      changed = false;

      modalBody.innerHTML = "";
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

      overlay.hidden = false;
      const input = wrap.querySelector('input[type="text"]');
      if (input) input.focus();
    }

    function closePopup() {
      if (!overlay || overlay.hidden) return;
      overlay.hidden = true;
      // Tag badges next to each entry are server-rendered — a reload is
      // the simplest way to make them catch up with whatever changed.
      if (changed) location.reload();
    }

    editTagsBtn.addEventListener("click", openPopup);
  }
})();
