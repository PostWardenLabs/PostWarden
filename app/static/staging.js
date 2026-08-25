/* Libro — Staging approval page. "select all" toggles every entry
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
})();
