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
  // itself (its own onclick, since it's the one truly destructive
  // action — permanent delete); this only fires for a plain Approve
  // submit, identified by *not* carrying Reject's formaction override.
  form.addEventListener("submit", (e) => {
    const isReject = e.submitter && e.submitter.formAction
      && e.submitter.formAction.includes("/reject");
    if (isReject) return;
    const n = checks.filter((c) => c.checked).length;
    const msg = n === 1
      ? "Approve this entry? It'll be posted for real — Reject won't be able to undo it anymore, only Reverse."
      : `Approve these ${n} entries? They'll be posted for real — Reject won't be able to undo them anymore, only Reverse.`;
    if (!confirm(msg)) e.preventDefault();
  });
})();
