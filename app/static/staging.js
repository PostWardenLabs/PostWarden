/* PostWarden — Staging approval page. "Select" reveals a checkbox per
   entry plus "select all" (body.select-mode/.select-only — same
   mechanism as the Journal's own "Select entries", entries-select.js);
   Approve and the top-of-page bulk Reject stay visible throughout,
   just disabled until at least one entry is checked, so there's no
   accidental empty submit and no need to discover Select first to see
   what they do. Alt+A approves whatever's checked, Alt+R rejects it —
   both no-op while disabled, same as clicking by hand. Reject used to
   also have a per-entry button inside each expanded row; removed in
   favor of this one mechanism for both a single entry (check just that
   one) and many. */
(function () {
  const form = document.getElementById("staging-form");
  if (!form) return;
  const toggle = document.getElementById("select-toggle");
  const selectAll = document.getElementById("select-all");
  const checks = Array.from(form.querySelectorAll(".staging-check"));
  const approveBtn = document.getElementById("approve-btn");
  const rejectBtn = document.getElementById("reject-btn");
  const buttons = [approveBtn, rejectBtn];

  function sync() {
    const checkedCount = checks.filter((c) => c.checked).length;
    buttons.forEach((b) => { if (b) b.disabled = checkedCount === 0; });
    if (selectAll) {
      selectAll.checked = checkedCount === checks.length;
      selectAll.indeterminate = checkedCount > 0 && checkedCount < checks.length;
    }
  }

  // Same shape as entries-select.js's own setSelectMode: turning Select
  // off clears every checkbox rather than leaving a stale, invisible
  // selection behind — reopening Select later should always start from
  // nothing, not silently resume whatever was checked before.
  function setSelectMode(on) {
    document.body.classList.toggle("select-mode", on);
    toggle.textContent = on ? "Deselect" : "Select";
    if (!on) {
      checks.forEach((c) => { c.checked = false; });
      sync();
    }
  }
  if (toggle) {
    toggle.addEventListener("click", () => setSelectMode(!document.body.classList.contains("select-mode")));
  }

  if (selectAll) {
    selectAll.addEventListener("change", () => {
      checks.forEach((c) => { c.checked = selectAll.checked; });
      sync();
    });
  }
  checks.forEach((c) => c.addEventListener("change", sync));
  sync();

  document.addEventListener("keydown", (e) => {
    if (!e.altKey) return;
    if (e.code === "KeyA" && approveBtn) {
      e.preventDefault();
      approveBtn.click();
    } else if (e.code === "KeyR" && rejectBtn) {
      e.preventDefault();
      rejectBtn.click();
    }
  });

  // Both bulk actions here (Approve and the top-of-page Reject) need a
  // message that depends on how many entries are checked, computed right
  // when it's needed — can't be a static data-confirm attribute the way
  // per-entry Reject's is. Approving is the one action with no undo
  // through this screen again (once posted it's real, fixable only with
  // Reverse from the Journal); bulk Reject is a permanent delete, same
  // as its per-entry sibling, so it gets the same danger styling.
  // Per-entry Reject already confirms itself (its own data-confirm,
  // handled generically by confirm.js) — recognized here by *having*
  // that attribute, so this only ever runs for the two buttons that
  // don't.
  form.addEventListener("submit", (e) => {
    const submitter = e.submitter;
    if (submitter && submitter.dataset.confirm) return;
    // A separate flag from confirm.js's own confirmBypass — this and the
    // generic data-confirm handler both listen on/near this same form,
    // and each only needs to recognize its *own* already-confirmed
    // resubmit, not the other's.
    if (form.dataset.approveConfirmBypass === "1") { delete form.dataset.approveConfirmBypass; return; }
    e.preventDefault();
    const n = checks.filter((c) => c.checked).length;
    const isBulkReject = submitter === rejectBtn;
    const msg = isBulkReject
      ? (n === 1
          ? "Reject and permanently delete this entry? This cannot be undone."
          : `Reject and permanently delete these ${n} entries? This cannot be undone.`)
      : (n === 1
          ? "Approve this entry? It'll be posted for real — Reject won't be able to undo it anymore, only Reverse."
          : `Approve these ${n} entries? They'll be posted for real — Reject won't be able to undo them anymore, only Reverse.`);
    window.PostWardenConfirm.ask(msg, { danger: isBulkReject }).then((confirmed) => {
      if (!confirmed) return;
      form.dataset.approveConfirmBypass = "1";
      form.requestSubmit(submitter || undefined);
    });
  });
})();
