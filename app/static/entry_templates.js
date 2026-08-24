/* Libro — "Load template" on New entry. Picking a saved template replaces
   every other field on the form (description, reference, payee, tags, and
   the whole line grid) with what was saved, using the small APIs app.js
   (LibroEntryGrid) and tags.js (root.__libroTags) expose for exactly this.
   Entirely client-side against a #templates-data blob already on the page
   — no round trip needed to "load" one. */
(function () {
  function loadTemplateInto(tpl) {
    const grid = window.LibroEntryGrid;
    if (!grid) return;

    const desc = document.querySelector('input[name="description"]');
    if (desc) desc.value = tpl.description || "";
    const ref = document.querySelector('input[name="reference"]');
    if (ref) ref.value = tpl.reference || "";

    const payeeSel = document.querySelector('select[name="payee_id"]');
    if (payeeSel) {
      payeeSel.value = tpl.payee_id != null ? String(tpl.payee_id) : "";
      payeeSel.dispatchEvent(new Event("change", { bubbles: true }));
    }

    const tagsRoot = document.querySelector(".tag-input");
    if (tagsRoot && tagsRoot.__libroTags) {
      tagsRoot.__libroTags.setValue((tpl.tags || []).join(","));
    }

    grid.clear();
    // Create every row up front, before setting any values: each field's
    // dispatched change/input event runs app.js's ensureTrailingBlank(),
    // which — correctly, for a person typing — appends a fresh blank row
    // once the *current last row* becomes used. Interleaving addRow()
    // with value-setting would let that fire mid-loop and shove a stray
    // blank in between template lines.
    const lineRows = (tpl.lines || []).map(() => grid.addRow());
    (tpl.lines || []).forEach((ln, i) => {
      const tr = lineRows[i];
      const acct = tr.querySelector('select[name="account"]');
      acct.value = ln.code;
      acct.dispatchEvent(new Event("change", { bubbles: true }));
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
  }

  document.addEventListener("DOMContentLoaded", () => {
    const picker = document.getElementById("template-select");
    const dataEl = document.getElementById("templates-data");
    if (!picker || !dataEl) return;
    const templates = JSON.parse(dataEl.textContent || "[]");

    picker.addEventListener("change", () => {
      const tpl = templates.find((t) => String(t.id) === picker.value);
      if (tpl) loadTemplateInto(tpl);
    });
  });
})();
