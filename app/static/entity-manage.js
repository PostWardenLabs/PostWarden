/* PostWarden — Payees and Tags' shared "manage the entity itself" page.
   Both pages share one markup shape (payees.html/tags.html) and this one
   script, parameterized by data-* attributes rather than two near-
   identical files — the two entities differ only in which routes they
   hit and what a row is called in a sentence, not in any of the actual
   interaction.

   Three pieces, all scoped to whichever of the two pages is actually
   loaded (the selectors below simply find nothing on the other one):

   1. Edit — click swaps a row's plain name label for a real text input
      in place (not a popup); Enter submits the row's own small rename
      <form> (a real POST + redirect, same flash-banner pattern as every
      other action here, not a fetch()). Escape reverts without saving.

   2. Select mode — same body.select-mode toggle entries-select.js uses
      on the Journal (see style.css's .select-only), reusing that exact
      CSS hook rather than inventing a second one.

   3. Merge — enabled once 2+ rows are checked; opens a popup built from
      confirm.js's own .confirm-overlay/.confirm-modal CSS (same look as
      entries-select.js's "Edit tags" popup), holding a text field
      pre-filled with the first checked row's current name and editable
      before confirming. Unlike Edit tags (which fires fetch() per chip),
      confirming here fills in the page's own hidden #merge-form with one
      hidden input per checked id plus the typed name, then submits it for
      real — the usual flash-redirect round trip, since a merge is one
      atomic action with one result message, not a live-applying stream of
      small edits. */
(function () {
  function enhance(root) {
    const table = root.querySelector(".entity-table");
    if (!table) return;

    // -- Edit: swap the name label for its row's own rename form ---------
    table.addEventListener("click", (e) => {
      const btn = e.target.closest(".entity-edit-btn");
      if (!btn) return;
      const row = btn.closest("tr");
      const label = row.querySelector(".entity-name-label");
      const form = row.querySelector(".entity-rename-form");
      const input = form.querySelector(".entity-rename-input");
      label.hidden = true;
      form.hidden = false;
      input.focus();
      input.select();
    });
    table.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      const form = e.target.closest(".entity-rename-form");
      if (!form || form.hidden) return;
      const row = form.closest("tr");
      const label = row.querySelector(".entity-name-label");
      const input = form.querySelector(".entity-rename-input");
      input.value = label.textContent;
      form.hidden = true;
      label.hidden = false;
    });

    // -- Select mode + Merge ----------------------------------------------
    const toggle = root.querySelector(".select-toggle");
    const selectAll = root.querySelector(".select-all");
    const mergeBtn = root.querySelector(".merge-btn");
    const mergeForm = root.querySelector(".merge-form");
    if (!toggle) return;
    const checks = Array.from(table.querySelectorAll(".entity-check"));

    function sync() {
      const checked = checks.filter((c) => c.checked);
      if (mergeBtn) mergeBtn.disabled = checked.length < 2;
      if (selectAll) {
        selectAll.checked = checked.length === checks.length && checks.length > 0;
        selectAll.indeterminate = checked.length > 0 && checked.length < checks.length;
      }
    }

    function setSelectMode(on) {
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

    if (!mergeBtn || !mergeForm) return;
    const idParam = mergeForm.dataset.idParam;
    const labelPlural = mergeForm.dataset.labelPlural;
    let overlay, nameInput, confirmBtn;

    function build() {
      overlay = document.createElement("div");
      overlay.className = "confirm-overlay";
      overlay.hidden = true;
      const modal = document.createElement("div");
      modal.className = "confirm-modal";
      modal.setAttribute("role", "dialog");
      modal.setAttribute("aria-label", "Merge " + labelPlural);

      const heading = document.createElement("h3");
      modal.appendChild(heading);
      heading.className = "merge-heading";

      const field = document.createElement("label");
      field.className = "field";
      field.textContent = "Merge into";
      nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.required = true;
      nameInput.maxLength = 80;
      field.appendChild(nameInput);
      modal.appendChild(field);

      const actions = document.createElement("div");
      actions.className = "confirm-actions";
      actions.style.marginTop = "1.1rem";
      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "quiet confirm-cancel";
      cancelBtn.textContent = "Cancel";
      confirmBtn = document.createElement("button");
      confirmBtn.type = "button";
      confirmBtn.className = "confirm-ok";
      confirmBtn.textContent = "Merge";
      actions.append(cancelBtn, confirmBtn);
      modal.appendChild(actions);

      overlay.appendChild(modal);
      document.body.appendChild(overlay);
      overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
      cancelBtn.addEventListener("click", close);
      document.addEventListener("keydown", (e) => {
        if (!overlay.hidden && e.key === "Escape") close();
      });
      confirmBtn.addEventListener("click", submit);
    }

    function close() {
      if (overlay) overlay.hidden = true;
    }

    function submit() {
      const name = nameInput.value.trim();
      if (!name) { nameInput.focus(); return; }
      mergeForm.querySelectorAll("input[name='" + idParam + "']").forEach((el) => el.remove());
      checks.filter((c) => c.checked).forEach((c) => {
        const hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = idParam;
        hidden.value = c.value;
        mergeForm.appendChild(hidden);
      });
      let targetInput = mergeForm.querySelector("input[name='target_name']");
      if (!targetInput) {
        targetInput = document.createElement("input");
        targetInput.type = "hidden";
        targetInput.name = "target_name";
        mergeForm.appendChild(targetInput);
      }
      targetInput.value = name;
      mergeForm.requestSubmit();
    }

    mergeBtn.addEventListener("click", () => {
      if (!overlay) build();
      const checked = checks.filter((c) => c.checked);
      const heading = overlay.querySelector(".merge-heading");
      heading.textContent = "Merge " + checked.length + " " + labelPlural;
      nameInput.value = checked.length ? checked[0].dataset.name : "";
      overlay.hidden = false;
      nameInput.focus();
      nameInput.select();
    });
  }

  document.addEventListener("DOMContentLoaded", () => enhance(document));
})();
