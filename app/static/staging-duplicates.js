/* PostWarden — Find Duplicates merge flow (/staging/duplicates).

   Checking 2+ entries within one group enables the top Merge button.
   Clicking it processes exactly one group per click — the first one
   (in document order) with 2+ checked — same one-atomic-action-per-
   submit shape entity-manage.js's own Payee/Tag Merge already uses,
   rather than trying to batch-resolve several groups' worth of "which
   description/tags/memos to keep" behind one click. If other duplicate
   groups remain after this one merges, the merge route's own flash-
   redirect reloads the page and recomputes them fresh — Merge just
   works the same way again on whatever's left.

   If some entries in the qualifying group were left unchecked, a
   Proceed/Select remaining/Cancel dialog asks first (BACKLOG.md's own
   spec) — a custom three-button popup, since confirm.js's ask() only
   ever offers two. Proceeding opens the actual merge-detail popup:
   Description/Reference/Payee/Tags, plus one memo field per line on the
   surviving entry, each pre-filled from that entry's own memo or (if
   blank) the first non-blank memo found on the matching (account,
   amount) leg among the other checked entries — never a guess across a
   *different* leg, since matching account+amount is exactly what makes
   two legs "the same line" across duplicate entries. Saving fills in
   the page's real <form> with hidden inputs and submits it for real —
   a flash-redirect round trip, not a fetch, matching every other Merge
   in this app. */
(function () {
  const groups = JSON.parse((document.getElementById("duplicates-data") || {}).textContent || "[]");
  const payees = JSON.parse((document.getElementById("payees-data") || {}).textContent || "[]");
  const form = document.getElementById("duplicates-form");
  if (!form) return;
  const mergeBtn = document.getElementById("merge-btn");
  const sections = Array.from(document.querySelectorAll(".duplicate-group"));

  function checksIn(section) {
    return Array.from(section.querySelectorAll(".dup-check"));
  }
  function sync() {
    mergeBtn.disabled = !sections.some((s) => checksIn(s).filter((c) => c.checked).length >= 2);
  }
  sections.forEach((s) => checksIn(s).forEach((c) => c.addEventListener("change", sync)));
  sync();

  // -- A small overlay, reused for both the three-way dialog and the
  //    merge-detail form — same .confirm-overlay/.confirm-modal CSS
  //    confirm.js's own singleton uses, built by hand like entries-
  //    select.js's Edit tags popup, since neither shape here fits
  //    confirm.js's plain message+OK/Cancel ask(). ----------------------
  let overlay, modalBody;
  function buildOverlay() {
    overlay = document.createElement("div");
    overlay.className = "confirm-overlay";
    overlay.hidden = true;
    const modal = document.createElement("div");
    modal.className = "confirm-modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-label", "Merge duplicate entries");
    modalBody = document.createElement("div");
    modal.appendChild(modalBody);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) closeOverlay(); });
    document.addEventListener("keydown", (e) => { if (!overlay.hidden && e.key === "Escape") closeOverlay(); });
  }
  function closeOverlay() { if (overlay) overlay.hidden = true; }

  function askThreeWay(message) {
    if (!overlay) buildOverlay();
    return new Promise((resolve) => {
      modalBody.innerHTML = "";
      const p = document.createElement("p");
      p.className = "confirm-message";
      p.textContent = message;
      const actions = document.createElement("div");
      actions.className = "confirm-actions";
      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button"; cancelBtn.className = "quiet";
      cancelBtn.textContent = "Cancel";
      cancelBtn.addEventListener("click", () => { closeOverlay(); resolve("cancel"); });
      const selectBtn = document.createElement("button");
      selectBtn.type = "button"; selectBtn.className = "quiet";
      selectBtn.textContent = "Select remaining entries";
      selectBtn.addEventListener("click", () => { closeOverlay(); resolve("select"); });
      const proceedBtn = document.createElement("button");
      proceedBtn.type = "button"; proceedBtn.className = "confirm-ok";
      proceedBtn.textContent = "Proceed";
      proceedBtn.addEventListener("click", () => { closeOverlay(); resolve("proceed"); });
      actions.append(cancelBtn, selectBtn, proceedBtn);
      modalBody.append(p, actions);
      overlay.hidden = false;
      cancelBtn.focus();
    });
  }

  function findLeg(entry, accountId, amount) {
    return (entry.lines || []).find(
      (l) => l.account_id === accountId && Number(l.amount) === Number(amount));
  }

  function field(container, labelText, input) {
    const label = document.createElement("label");
    label.className = "field";
    label.style.marginTop = "0.6rem";
    label.textContent = labelText;
    label.appendChild(input);
    container.appendChild(label);
    return input;
  }

  function setHidden(name, value) {
    let el = form.querySelector(`input[name="${name}"]`);
    if (!el) {
      el = document.createElement("input");
      el.type = "hidden";
      el.name = name;
      form.appendChild(el);
    }
    el.value = value;
  }
  function addHidden(name, value) {
    const el = document.createElement("input");
    el.type = "hidden";
    el.name = name;
    el.value = value;
    form.appendChild(el);
  }
  function clearPriorSelection() {
    // A previous group's own merge could have been cancelled after
    // partially filling these in (unlikely given the flow below, but
    // cheap insurance) — never let a stale remove_id/memo_* ride along
    // into a different group's submit.
    form.querySelectorAll('input[name="remove_id"], input[name^="memo_"]').forEach((el) => el.remove());
  }

  function openMergeDetail(groupIndex, checkedIds) {
    const group = groups[groupIndex];
    const entries = group.entries.filter((e) => checkedIds.includes(String(e.id)));
    const survivor = entries[0];
    const others = entries.slice(1);

    if (!overlay) buildOverlay();
    modalBody.innerHTML = "";
    const h = document.createElement("h3");
    h.textContent = `Merge ${entries.length} entries`;
    modalBody.appendChild(h);

    const descInput = document.createElement("input");
    descInput.type = "text";
    descInput.value = survivor.description;
    field(modalBody, "Description", descInput);

    const refInput = document.createElement("input");
    refInput.type = "text";
    refInput.value = survivor.reference || "";
    field(modalBody, "Reference", refInput);

    const payeeSelect = document.createElement("select");
    const noneOpt = document.createElement("option");
    noneOpt.value = "";
    noneOpt.textContent = "(none)";
    payeeSelect.appendChild(noneOpt);
    payees.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name;
      if (survivor.payee_id != null && String(survivor.payee_id) === String(p.id)) opt.selected = true;
      payeeSelect.appendChild(opt);
    });
    field(modalBody, "Payee", payeeSelect);

    const tagsWrap = document.createElement("div");
    tagsWrap.className = "tag-input";
    tagsWrap.dataset.placeholder = "Add a tag…";
    const tagsHidden = document.createElement("input");
    tagsHidden.type = "hidden";
    const unionTags = new Set();
    entries.forEach((e) => (e.tags || []).forEach((t) => unionTags.add(t)));
    tagsHidden.value = Array.from(unionTags).join(",");
    tagsWrap.appendChild(tagsHidden);
    field(modalBody, "Tags", tagsWrap);
    window.PostWardenTags.enhance(tagsWrap);

    const memoInputs = [];
    survivor.lines.forEach((line) => {
      let candidate = line.memo || "";
      if (!candidate) {
        for (const other of others) {
          const leg = findLeg(other, line.account_id, line.amount);
          if (leg && leg.memo) { candidate = leg.memo; break; }
        }
      }
      const input = document.createElement("input");
      input.type = "text";
      input.value = candidate;
      input.dataset.lineId = line.id;
      memoInputs.push(input);
      field(modalBody, `Memo — ${line.account_code} ${line.account_name}`, input);
    });

    const actions = document.createElement("div");
    actions.className = "confirm-actions";
    actions.style.marginTop = "1.1rem";
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button"; cancelBtn.className = "quiet";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", closeOverlay);
    const saveBtn = document.createElement("button");
    saveBtn.type = "button"; saveBtn.className = "confirm-ok";
    saveBtn.textContent = "Merge";
    saveBtn.addEventListener("click", () => {
      clearPriorSelection();
      setHidden("keep_id", survivor.id);
      setHidden("description", descInput.value.trim());
      setHidden("reference", refInput.value.trim());
      setHidden("payee_id", payeeSelect.value);
      setHidden("tags", tagsHidden.value);
      others.forEach((o) => addHidden("remove_id", o.id));
      memoInputs.forEach((input) => addHidden(`memo_${input.dataset.lineId}`, input.value.trim()));
      form.submit();
    });
    actions.append(cancelBtn, saveBtn);
    modalBody.appendChild(actions);

    overlay.hidden = false;
    descInput.focus();
    descInput.select();
  }

  mergeBtn.addEventListener("click", async () => {
    const section = sections.find((s) => checksIn(s).filter((c) => c.checked).length >= 2);
    if (!section) return;
    const groupIndex = Number(section.dataset.groupIndex);
    const allChecks = checksIn(section);
    const checked = allChecks.filter((c) => c.checked);
    const uncheckedCount = allChecks.length - checked.length;

    let checkedIds = checked.map((c) => c.dataset.entryId);
    if (uncheckedCount > 0) {
      const noun = uncheckedCount === 1 ? "entry" : "entries";
      const verb = uncheckedCount === 1 ? "is" : "are";
      const choice = await askThreeWay(
        `Another ${noun} matching the same accounts, amounts and date ${verb} not being included. Are you sure you want to proceed?`);
      if (choice === "cancel") return;
      if (choice === "select") {
        allChecks.forEach((c) => { c.checked = true; });
        sync();
        checkedIds = allChecks.map((c) => c.dataset.entryId);
      }
    }
    openMergeDetail(groupIndex, checkedIds);
  });
})();
