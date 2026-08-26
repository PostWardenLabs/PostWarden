/* PostWarden — Staging approval page. "select all" toggles every entry
   checkbox at once; both Approve buttons (top and bottom of a possibly
   long list) stay disabled until at least one entry is checked, so
   there's no accidental empty submit. */
(function () {
  const form = document.getElementById("staging-form");
  if (!form) return;
  const selectAll = document.getElementById("select-all");
  const checks = Array.from(form.querySelectorAll(".staging-check"));
  const buttons = [
    document.getElementById("approve-btn"),
    document.getElementById("approve-btn-bottom"),
  ];

  function sync() {
    const checkedCount = checks.filter((c) => c.checked).length;
    buttons.forEach((b) => { if (b) b.disabled = checkedCount === 0; });
    if (selectAll) {
      selectAll.checked = checkedCount === checks.length;
      selectAll.indeterminate = checkedCount > 0 && checkedCount < checks.length;
    }
  }

  if (selectAll) {
    selectAll.addEventListener("change", () => {
      checks.forEach((c) => { c.checked = selectAll.checked; });
      sync();
    });
  }
  checks.forEach((c) => c.addEventListener("change", sync));
  sync();

  // Approving is the one Staging action with no undo through this same
  // screen again — once posted it's a real entry, fixable only with
  // Reverse from the Journal from here on. Reject already confirms
  // itself (a plain data-confirm on the button, handled generically by
  // confirm.js — it's the one truly destructive action, permanent
  // delete); this only fires for a plain Approve submit, identified by
  // *not* carrying Reject's formaction override. The message depends on
  // how many entries are checked, computed right when it's needed, so
  // it can't be a static data-confirm attribute the way Reject's is —
  // calls PostWardenConfirm.ask() directly instead, then resubmits
  // itself the same way confirm.js's own generic handler does.
  form.addEventListener("submit", (e) => {
    const isReject = e.submitter && e.submitter.formAction
      && e.submitter.formAction.includes("/reject");
    if (isReject) return;
    // A separate flag from confirm.js's own confirmBypass — this and the
    // generic data-confirm handler both listen on/near this same form,
    // and each only needs to recognize its *own* already-confirmed
    // resubmit, not the other's.
    if (form.dataset.approveConfirmBypass === "1") { delete form.dataset.approveConfirmBypass; return; }
    e.preventDefault();
    const n = checks.filter((c) => c.checked).length;
    const msg = n === 1
      ? "Approve this entry? It'll be posted for real — Reject won't be able to undo it anymore, only Reverse."
      : `Approve these ${n} entries? They'll be posted for real — Reject won't be able to undo them anymore, only Reverse.`;
    window.PostWardenConfirm.ask(msg).then((confirmed) => {
      if (!confirmed) return;
      form.dataset.approveConfirmBypass = "1";
      form.requestSubmit(e.submitter || undefined);
    });
  });
})();
