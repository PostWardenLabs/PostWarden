/* PostWarden — "Load template" on New entry. Picking a saved template replaces
   every other field on the form (description, reference, payee, tags, and
   the whole line grid) with what was saved, using the small APIs app.js
   (PostWardenEntryGrid) and tags.js (root.__postwardenTags) expose for exactly this.
   Entirely client-side against a #templates-data blob already on the page
   — no round trip needed to "load" one.

   All lookups are scoped to a container (the entry form's nearest
   <details> on the Journal page, or the whole document when there isn't
   one) rather than a bare document.querySelector — the Journal's filter
   bar has its own unrelated .tag-input (for filtering by tag), and a
   global lookup would find that one first instead of the entry form's. */
(function () {
  function loadTemplateInto(tpl, root) {
    const grid = window.PostWardenEntryGrid;
    if (!grid) return;

    const desc = root.querySelector('input[name="description"]');
    if (desc) desc.value = tpl.description || "";
    const ref = root.querySelector('input[name="reference"]');
    if (ref) ref.value = tpl.reference || "";

    const payeeSel = root.querySelector('select[name="payee_id"]');
    if (payeeSel) {
      payeeSel.value = tpl.payee_id != null ? String(tpl.payee_id) : "";
      payeeSel.dispatchEvent(new Event("change", { bubbles: true }));
    }

    const tagsRoot = root.querySelector(".tag-input");
    if (tagsRoot && tagsRoot.__postwardenTags) {
      tagsRoot.__postwardenTags.setValue((tpl.tags || []).join(","));
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
    const root = picker.closest("details") || document;

    picker.addEventListener("change", () => {
      const tpl = templates.find((t) => String(t.id) === picker.value);
      if (tpl) loadTemplateInto(tpl, root);
    });
  });
})();
