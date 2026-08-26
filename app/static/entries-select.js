/* PostWarden — Journal "select entries" mode. Hidden by default (see
   .select-only in style.css); "Select entries" reveals a checkbox per
   entry and the bar above it, same mechanism Staging's own bulk actions
   already use — "select all", Reverse disabled until something's
   checked, Alt+R as the keyboard shortcut. Reverse confirms via
   confirm.js's ask() with a count-aware message (same pattern as
   Staging's Approve/Reject) before actually submitting. */
(function () {
  const form = document.getElementById("entries-select-form");
  if (!form) return;
  const toggle = document.getElementById("select-toggle");
  const selectAll = document.getElementById("select-all");
  const reverseBtn = document.getElementById("reverse-btn");
  const checks = Array.from(form.querySelectorAll(".entry-check"));

  function sync() {
    const checkedCount = checks.filter((c) => c.checked).length;
    if (reverseBtn) reverseBtn.disabled = checkedCount === 0;
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
})();
