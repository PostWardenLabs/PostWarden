/* Libro — journal entry grid.
   Keyboard-first: Tab flows through account → debit → credit → memo;
   a new blank line appears once the last line is in use. Entering a debit
   clears the credit on that line (and vice versa) — one side per line,
   exactly like the paper form. The Post button unlocks only when the
   entry balances, unless the chosen scenario allows single-sided entries.
   The database re-checks everything at commit regardless. */
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

  const fmt = (n) =>
    n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function makeRow() {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="col-account"><input name="account" list="acctlist"
          autocomplete="off" placeholder="code or name"></td>
      <td class="col-amount money money-first"><input name="debit" class="amount"
          inputmode="decimal" placeholder=""></td>
      <td class="col-amount money"><input name="credit" class="amount"
          inputmode="decimal" placeholder=""></td>
      <td><input name="memo" placeholder=""></td>`;
    body.appendChild(tr);
    return tr;
  }

  function rows() { return Array.from(body.querySelectorAll("tr")); }

  function rowUsed(tr) {
    return Array.from(tr.querySelectorAll("input")).some((i) => i.value.trim() !== "");
  }

  function ensureTrailingBlank() {
    const rs = rows();
    if (rs.length === 0 || rowUsed(rs[rs.length - 1])) makeRow();
    // trim extra blanks at the end, keep exactly one
    let r = rows();
    while (r.length > 2 && !rowUsed(r[r.length - 1]) && !rowUsed(r[r.length - 2])) {
      r[r.length - 1].remove();
      r = rows();
    }
  }

  function enforcing() {
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

  body.addEventListener("input", (e) => {
    const tr = e.target.closest("tr");
    if (e.target.name === "debit" && e.target.value.trim() !== "")
      tr.querySelector('[name="credit"]').value = "";
    if (e.target.name === "credit" && e.target.value.trim() !== "")
      tr.querySelector('[name="debit"]').value = "";
    ensureTrailingBlank();
    recalc();
  });

  scenarioSel.addEventListener("change", recalc);

  document.getElementById("add-row").addEventListener("click", () => {
    makeRow().querySelector('[name="account"]').focus();
    recalc();
  });
  document.addEventListener("keydown", (e) => {
    if (e.altKey && e.key.toLowerCase() === "n") {
      e.preventDefault();
      makeRow().querySelector('[name="account"]').focus();
    }
  });

  // Submit via fetch so a rejected entry (unbalanced, bad account code,
  // locked scenario, ...) can show its error without reloading the page —
  // otherwise every line the user typed would vanish on a plain redirect.
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
})();
