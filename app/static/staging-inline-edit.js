/* PostWarden — Staging's inline "Edit" panel. Clicking Edit on a pending
   entry used to navigate to its own page (/staging/{id}/edit); this
   drives the same grid (app.js — the exact "+ New entry" component the
   Journal uses) as a panel that relocates into whichever entry is
   currently being edited, instead. Opening one no longer costs a page
   load; Save still does (same as "+ New entry"'s Post always has) —
   this only removes the navigation it took just to *start* editing.

   Only one entry can be mid-edit at a time: there's exactly one grid on
   the page (the same singleton #lines-body/#entry-form/etc. shape
   app.js has always assumed everywhere it runs), so opening a second
   entry closes whichever one was already open first. */
(function () {
  const panel = document.getElementById("staging-edit-panel");
  const home = document.getElementById("staging-edit-panel-home");
  const grid = window.PostWardenEntryGrid;
  if (!panel || !home || !grid) return;

  const form = document.getElementById("entry-form");
  const errBox = document.getElementById("entry-error");
  const dateField = form.querySelector('[name="entry_date"]');
  const descField = form.querySelector('[name="description"]');
  const refField = form.querySelector('[name="reference"]');
  const payeeSel = form.querySelector('select[name="payee_id"]');
  const tagsRoot = form.querySelector(".tag-input");
  const scenarioSel = document.getElementById("scenario");
  const postBtn = document.getElementById("post-btn");
  const cancelBtn = document.getElementById("staging-edit-cancel");

  let currentId = null;

  function closePanel() {
    if (currentId !== null) {
      const prevView = document.querySelector(
        '.lines[data-entry-id="' + currentId + '"] .staging-view');
      if (prevView) prevView.hidden = false;
    }
    panel.hidden = true;
    postBtn.disabled = true;
    home.after(panel);
    currentId = null;
  }

  function openEntry(id) {
    if (id === currentId) return;
    closePanel();

    const container = document.querySelector('.lines[data-entry-id="' + id + '"]');
    if (!container) return;
    const view = container.querySelector(".staging-view");
    view.hidden = true;
    container.appendChild(panel);
    panel.hidden = false;
    currentId = id;
    form.action = "/staging/" + id + "/edit";
    errBox.hidden = true;

    fetch("/staging/" + id + "/edit", { headers: { Accept: "application/json" } })
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) {
          errBox.textContent = data.error;
          errBox.hidden = false;
          return;
        }
        dateField.value = data.entry.entry_date;
        descField.value = data.entry.description;
        refField.value = data.entry.reference;
        if (payeeSel) {
          payeeSel.value = data.entry.payee_id || "";
          if (window.PostWardenCombobox) window.PostWardenCombobox.resync(payeeSel);
        }
        if (tagsRoot && tagsRoot.__postwardenTags) {
          tagsRoot.__postwardenTags.setValue((data.tags || []).join(","));
        }

        // Single-option select, same idea as "+ New entry"'s own
        // scenario picker, just fixed to one option — rewritten to
        // whichever entry's target scenario is now open, since (unlike
        // that picker) it's never something a person chooses here.
        const opt = scenarioSel.options[0];
        opt.value = data.target_scenario.id;
        opt.textContent = data.target_scenario.code;
        opt.dataset.enforce = data.target_scenario.enforce_balance ? "1" : "0";
        scenarioSel.value = data.target_scenario.id;

        grid.setAccounts(data.accounts);
        grid.clear();
        // Same reasoning as entry_templates.js's own "Load template":
        // create every row before setting any values, so
        // ensureTrailingBlank() can't interleave a stray blank row
        // between two loaded lines.
        const rows = data.lines.map(() => grid.addRow());
        data.lines.forEach((ln, i) => {
          const tr = rows[i];
          const acct = tr.querySelector('select[name="account"]');
          acct.value = ln.code;
          acct.dispatchEvent(new Event("change", { bubbles: true }));
          if (window.PostWardenCombobox) window.PostWardenCombobox.resync(acct);
          if (ln.debit) {
            const debit = tr.querySelector('[name="debit"]');
            debit.value = ln.debit;
            debit.dispatchEvent(new Event("input", { bubbles: true }));
          }
          if (ln.credit) {
            const credit = tr.querySelector('[name="credit"]');
            credit.value = ln.credit;
            credit.dispatchEvent(new Event("input", { bubbles: true }));
          }
          if (ln.memo) tr.querySelector('[name="memo"]').value = ln.memo;
        });
        grid.ensureTrailingBlank();
        grid.recalc();
        descField.focus();
      })
      .catch(() => {
        errBox.textContent = "Could not reach the server — check your connection and try again.";
        errBox.hidden = false;
      });
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".staging-edit-btn");
    if (btn) openEntry(btn.dataset.entryId);
  });
  cancelBtn.addEventListener("click", closePanel);
})();
