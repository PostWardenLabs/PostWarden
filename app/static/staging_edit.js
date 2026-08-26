/* PostWarden — Staging's "Edit" screen. Loads the entry's existing lines
   into app.js's grid on page load, the same way entry_templates.js loads
   a saved template into New entry's grid — just automatic instead of
   picked from a dropdown, and reading #staging-entry-lines-data instead
   of a template's own blob. Everything else on this page (description,
   reference, payee, tags) is filled in server-side already, since those
   are plain form fields with a real value= — only the grid is built by
   JS at all, so only the grid needs loading here. */
(function () {
  document.addEventListener("DOMContentLoaded", () => {
    const grid = window.PostWardenEntryGrid;
    const dataEl = document.getElementById("staging-entry-lines-data");
    if (!grid || !dataEl) return;
    const lines = JSON.parse(dataEl.textContent || "[]");

    grid.clear();
    // Same reasoning as entry_templates.js: create every row before
    // setting any values, so ensureTrailingBlank()'s own "add a blank
    // once the last row fills up" logic can't interleave a stray blank
    // row in between two loaded lines.
    const rows = lines.map(() => grid.addRow());
    lines.forEach((ln, i) => {
      const tr = rows[i];
      const acct = tr.querySelector('select[name="account"]');
      acct.value = ln.code;
      acct.dispatchEvent(new Event("change", { bubbles: true }));
      // The dispatched change above runs app.js's own onRowChange (balance
      // recalc, ensureTrailingBlank) fine, but combobox.js only syncs its
      // *visible* text from a select's value on the paths it drives
      // itself (typing, picking an option) — not from an externally
      // dispatched event on the underlying <select>. Without this, the
      // account column reads as blank even though the real value (and
      // what actually submits) is set correctly.
      if (window.PostWardenCombobox) window.PostWardenCombobox.resync(acct);
      if (ln.debit) {
        const debit = tr.querySelector('input[name="debit"]');
        debit.value = ln.debit;
        debit.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (ln.credit) {
        const credit = tr.querySelector('input[name="credit"]');
        credit.value = ln.credit;
        credit.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (ln.memo) tr.querySelector('input[name="memo"]').value = ln.memo;
    });
    grid.ensureTrailingBlank();
    grid.recalc();
  });
})();
