/* PostWarden — Journal "select entries" mode. Hidden by default (see
   .select-only in style.css); "Select entries" reveals a checkbox per
   entry and the bar above it, same mechanism Staging's own bulk actions
   already use — "select all", Reverse/Edit tags disabled until
   something's checked, Alt+R as Reverse's keyboard shortcut. Reverse
   confirms via confirm.js's ask() with a count-aware message (same
   pattern as Staging's Approve/Reject) before actually submitting.
   Edit tags opens a popup styled like that same confirm dialog (same
   .confirm-overlay/.confirm-modal), but holding the tag-picker pill box
   from New entry instead of a message and buttons — the popup itself is
   tags-bulk-edit.js, shared with Staging's own Edit tags button. */
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
    // On document.body, not the form itself — the per-entry checkboxes
    // this mode reveals live inside each entry's <summary>, not inside
    // #entries-select-form (see its own comment on why), so a class
    // scoped to the form could never be read by a selector that needs
    // to reach them. body is an ancestor of both the toolbar and every
    // entry row.
    document.body.classList.toggle("select-mode", on);
    toggle.textContent = on ? "Deselect" : "Select";
    if (!on) {
      checks.forEach((c) => { c.checked = false; });
      if (selectAll) { selectAll.checked = false; selectAll.indeterminate = false; }
      sync();
    }
  }

  toggle.addEventListener("click", () => setSelectMode(!document.body.classList.contains("select-mode")));

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
  // Popup itself lives in tags-bulk-edit.js, shared with Staging's own
  // Edit tags button — this just supplies the Journal-specific bits:
  // which checkboxes count as "checked" and where the CSRF token lives.
  if (editTagsBtn) {
    const entryTagsData = JSON.parse(
      (document.getElementById("entry-tags-data") || {}).textContent || "{}");
    const csrfInput = form.querySelector('input[name="csrf_token"]');
    window.PostWardenBulkTags.attach({
      button: editTagsBtn,
      csrfToken: () => (csrfInput ? csrfInput.value : ""),
      getEntryIds: () => checks.filter((c) => c.checked).map((c) => c.value),
      entryTagsData,
    });
  }
})();
