/* PostWarden — journal entry grid.
   Keyboard-first: Tab flows through account → debit → credit → memo;
   a new blank line appears once the last line is in use. Entering a debit
   clears the credit on that line (and vice versa) — one side per line,
   exactly like the paper form. The Post button unlocks only when the
   entry balances, unless the chosen scenario allows single-sided entries.
   The database re-checks everything at commit regardless.

   The account cell is a real <select> (options built from ACCOUNTS below),
   skinned into a searchable combobox by combobox.js — so a line can only
   ever reference an account that actually exists; there's no "unknown
   account code" typo path left in the UI (the server still validates,
   since a direct POST could still send garbage). */
(function () {
  const body = document.getElementById("lines-body");
  const bar = document.getElementById("balance-bar");
  const tDeb = document.getElementById("t-debits");
  const tCre = document.getElementById("t-credits");
  const tDiff = document.getElementById("t-diff");
  const msg = document.getElementById("balance-msg");
  const postBtn = document.getElementById("post-btn");
  const scenarioSel = document.getElementById("scenario");
  const form = document.getElementById("entry-form");
  const errBox = document.getElementById("entry-error");
  if (!body) return;

  let ACCOUNTS = JSON.parse(document.getElementById("accounts-data").textContent || "[]");
  // {scenario_id: [account, ...]} — entry_templates.html has no scenario
  // picker and thus no such blob; ACCOUNTS just stays the broadened list
  // that page was given (see postable_accounts_for_pickers()).
  const accountsByScenarioEl = document.getElementById("accounts-by-scenario-data");
  const ACCOUNTS_BY_SCENARIO = accountsByScenarioEl
    ? JSON.parse(accountsByScenarioEl.textContent || "{}") : null;

  // Same symbol/decimal/thousands preferences as every server-rendered
  // {{ x | money }} span (see money-format.js) — this bar is the one
  // money display in the app computed entirely client-side, so it needs
  // its own call in rather than a data-value span to rewrite.
  const fmt = (n) => window.PostWardenMoney
    ? window.PostWardenMoney.format(n)
    : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function buildAccountOptions(select) {
    select.innerHTML = "";
    select.appendChild(document.createElement("option")); // blank = unset
    ACCOUNTS.forEach((a) => {
      // Options built via textContent, not innerHTML — an account name
      // can't inject markup here regardless of what it contains.
      const opt = document.createElement("option");
      opt.value = a.code;
      opt.textContent = `${a.code} · ${a.name}`;
      opt.dataset.path = a.path;
      select.appendChild(opt);
    });
  }

  function makeRow() {
    const tr = document.createElement("tr");

    const acctTd = document.createElement("td");
    acctTd.className = "col-account";
    const acctSelect = document.createElement("select");
    acctSelect.name = "account";
    buildAccountOptions(acctSelect);
    acctTd.appendChild(acctSelect);
    tr.appendChild(acctTd);

    const debitTd = document.createElement("td");
    debitTd.className = "col-amount money money-first";
    const debitInput = document.createElement("input");
    debitInput.name = "debit"; debitInput.className = "amount"; debitInput.inputMode = "decimal";
    debitTd.appendChild(debitInput);
    tr.appendChild(debitTd);

    const creditTd = document.createElement("td");
    creditTd.className = "col-amount money";
    const creditInput = document.createElement("input");
    creditInput.name = "credit"; creditInput.className = "amount"; creditInput.inputMode = "decimal";
    creditTd.appendChild(creditInput);
    tr.appendChild(creditTd);

    const memoTd = document.createElement("td");
    const memoInput = document.createElement("input");
    memoInput.name = "memo";
    memoTd.appendChild(memoInput);
    tr.appendChild(memoTd);

    body.appendChild(tr);
    if (window.PostWardenCombobox) window.PostWardenCombobox.enhance(acctSelect);
    return tr;
  }

  function focusAccountField(tr) {
    // The real <select name="account"> is hidden once combobox.js skins
    // it; the thing a person actually types into is its sibling input.
    const field = tr.querySelector(".combobox-input") || tr.querySelector('[name="account"]');
    if (field) field.focus();
  }

  function rows() { return Array.from(body.querySelectorAll("tr")); }

  function rowUsed(tr) {
    const acct = tr.querySelector('select[name="account"]');
    if (acct && acct.value !== "") return true;
    return Array.from(tr.querySelectorAll('input[name="debit"], input[name="credit"], input[name="memo"]'))
      .some((i) => i.value.trim() !== "");
  }

  function ensureTrailingBlank() {
    const rs = rows();
    if (rs.length === 0 || rowUsed(rs[rs.length - 1])) makeRow();
    // trim extra blanks at the end, keep exactly one — but never the row
    // the user is currently focused in (e.g. mid-search in its account
    // combobox after clicking "Add line" left two blank rows). This runs
    // on every keystroke in the grid; yanking that row out from under a
    // still-typing user would kill their focus and close the dropdown.
    let r = rows();
    while (r.length > 2 && !rowUsed(r[r.length - 1]) && !rowUsed(r[r.length - 2])
           && !r[r.length - 1].contains(document.activeElement)) {
      r[r.length - 1].remove();
      r = rows();
    }
  }

  function enforcing() {
    // No scenario picker on this page (entry_templates.html — a template
    // isn't posted to any scenario) — always require balance there, same
    // as any scenario that doesn't explicitly opt out of it.
    if (!scenarioSel) return true;
    const opt = scenarioSel.selectedOptions[0];
    return !opt || opt.dataset.enforce === "1";
  }

  function recalc() {
    let deb = 0, cre = 0;
    rows().forEach((tr) => {
      deb += parseFloat(tr.querySelector('[name="debit"]').value) || 0;
      cre += parseFloat(tr.querySelector('[name="credit"]').value) || 0;
    });
    const diff = Math.round((deb - cre) * 100) / 100;
    tDeb.textContent = fmt(deb);
    tCre.textContent = fmt(cre);
    tDiff.textContent = fmt(Math.abs(diff));
    const balanced = diff === 0 && (deb > 0 || cre > 0);
    bar.classList.toggle("balanced", balanced);
    bar.classList.toggle("unbalanced", !balanced);
    if (enforcing()) {
      postBtn.disabled = !balanced;
      msg.textContent = balanced
        ? "Balanced — ready to post."
        : "Debits and credits must be equal before this entry can post.";
    } else {
      postBtn.disabled = deb === 0 && cre === 0;
      msg.textContent = balanced
        ? "Balanced — ready to post."
        : "This scenario accepts single-sided entries; balance is optional.";
    }
  }

  function onRowChange(e) {
    const tr = e.target.closest("tr");
    if (!tr) return;
    if (e.target.name === "debit" && e.target.value.trim() !== "")
      tr.querySelector('[name="credit"]').value = "";
    if (e.target.name === "credit" && e.target.value.trim() !== "")
      tr.querySelector('[name="debit"]').value = "";
    ensureTrailingBlank();
    recalc();
  }
  // "input" covers typing in debit/credit/memo; "change" covers picking an
  // account from the combobox (its underlying <select> only fires change,
  // not input, when set programmatically — see combobox.js).
  body.addEventListener("input", onRowChange);
  body.addEventListener("change", onRowChange);

  // Re-filters every row's account picker to whatever the newly-selected
  // scenario can actually post to (see fn_line_account_guard) — a line
  // already pointed at an account that's no longer valid for the new
  // scenario gets cleared rather than silently left showing something the
  // form would reject at submit time.
  function refreshAccountsForScenario() {
    if (!ACCOUNTS_BY_SCENARIO || !scenarioSel) return;
    ACCOUNTS = ACCOUNTS_BY_SCENARIO[scenarioSel.value] || [];
    rows().forEach((tr) => {
      const select = tr.querySelector('select[name="account"]');
      if (!select) return;
      const prevValue = select.value;
      buildAccountOptions(select);
      select.value = ACCOUNTS.some((a) => a.code === prevValue) ? prevValue : "";
      if (window.PostWardenCombobox) window.PostWardenCombobox.resync(select);
    });
  }

  if (scenarioSel) {
    scenarioSel.addEventListener("change", () => {
      refreshAccountsForScenario();
      recalc();
    });
  }

  document.getElementById("add-row").addEventListener("click", () => {
    focusAccountField(makeRow());
    recalc();
  });

  // Distribute — the line you're currently in (wherever focus is; the
  // trailing blank row if nothing's focused) gets whatever amount would
  // zero out the entry, on whichever side needs it. "Debit Cash 1000,
  // credit A/R 500, distribute the last line" fills in Credit 500 rather
  // than making you do the subtraction yourself. Always overwrites the
  // target line's own amount rather than adding to it, so clicking twice
  // is idempotent instead of compounding.
  const distributeBtn = document.getElementById("distribute-row");
  if (distributeBtn) {
    distributeBtn.addEventListener("click", () => {
      const active = document.activeElement;
      const focusedRow = active && body.contains(active) ? active.closest("tr") : null;
      const rs = rows();
      const tr = focusedRow || rs[rs.length - 1];
      if (!tr) return;
      let deb = 0, cre = 0;
      rs.forEach((r) => {
        if (r === tr) return;
        deb += parseFloat(r.querySelector('[name="debit"]').value) || 0;
        cre += parseFloat(r.querySelector('[name="credit"]').value) || 0;
      });
      // More debit than credit so far (diff > 0) means the entry is short
      // on the credit side — this line needs to *credit* the difference
      // to zero it out, and vice versa. (Debits and credits net to zero;
      // this line supplies whichever side is currently missing.)
      const diff = Math.round((deb - cre) * 100) / 100;
      const debitField = tr.querySelector('[name="debit"]');
      const creditField = tr.querySelector('[name="credit"]');
      creditField.value = diff > 0 ? diff.toFixed(2) : "";
      debitField.value = diff < 0 ? (-diff).toFixed(2) : "";
      debitField.dispatchEvent(new Event("input", { bubbles: true }));
      (diff > 0 ? creditField : debitField).focus();
    });
  }
  document.addEventListener("keydown", (e) => {
    if (e.altKey && e.key.toLowerCase() === "n") {
      e.preventDefault();
      focusAccountField(makeRow());
    }
  });

  // Submit via fetch so a rejected entry (unbalanced, locked scenario, ...)
  // can show its error without reloading the page — otherwise every line
  // the user typed would vanish on a plain redirect.
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    rows().forEach((tr) => { if (!rowUsed(tr)) tr.remove(); });
    errBox.hidden = true;
    postBtn.disabled = true;
    try {
      const res = await fetch(form.action, {
        method: "POST",
        headers: { Accept: "application/json" },
        body: new FormData(form),
      });
      const data = await res.json();
      if (data.ok) {
        window.location.href = data.redirect;
        return; // leaving the page
      }
      errBox.textContent = data.error;
      errBox.hidden = false;
      errBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      errBox.textContent = "Could not reach the server — check your connection and try again.";
      errBox.hidden = false;
    } finally {
      ensureTrailingBlank(); // the strip above may have removed the editable blank row
      recalc(); // restores the balance-derived enabled/disabled state
    }
  });

  makeRow();
  makeRow();
  recalc();

  // Lets other progressive-enhancement scripts drive the grid the same way
  // a person typing into it would — see entry_templates.js's "Load
  // template", the only current caller. Deliberately narrow: callers set
  // field values and dispatch their own change/input events (as
  // createAndSelect in combobox.js does), then call recalc().
  window.PostWardenEntryGrid = {
    addRow: () => { const tr = makeRow(); return tr; },
    clear: () => { body.innerHTML = ""; },
    ensureTrailingBlank,
    recalc,
  };
})();
