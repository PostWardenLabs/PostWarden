/* PostWarden — Budget grid (see app/templates/budget.html). A leaf account's
   Budgeted cell is a plain text input; typing into it recomputes every
   ancestor's rolled-up Budgeted/Variance live (client-side, no round
   trip — Actual never changes here, so only Budgeted needs recomputing),
   and blurring the field autosaves that one cell via fetch, the same
   FormData-to-JSON pattern app.js uses for posting an entry.

   Each row already carries its own Actual as a static data-actual
   attribute (server-rendered, never touched by this script) — Variance
   is (live) actual - budgeted (or budgeted - actual, if "Flip variance
   direction" is checked — see pctOfBase below), recomputed alongside it. */
(function () {
  const table = document.querySelector("table[data-collapse-key^='postwarden-budget-collapsed']");
  if (!table) return;
  const status = document.getElementById("budget-save-status");
  const csrfEl = document.getElementById("budget-csrf");

  const fmt = (n) => window.PostWardenMoney
    ? window.PostWardenMoney.format(n)
    : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  // Which of the two conventions is live right now — set server-side from
  // the same pct_of_base the "Flip variance direction" checkbox submits,
  // on the table itself so a page reload (the checkbox auto-refreshes,
  // same as every other filter) is the only thing that ever changes it;
  // typing into a Budgeted cell never does. Same two formulas as
  // _pct_variance()/_variance_amount() in main.py: default (0) — the
  // standard percent-change reading, actual as "new," budgeted as "old"
  // it's measured against — or checked (1), the same reading with the
  // two swapped.
  const pctOfBase = table.dataset.pctOfBase === "1";

  function pctVariance(actual, budgeted) {
    if (pctOfBase) {
      if (!actual) return null;
      return Math.round(((budgeted - actual) / Math.abs(actual)) * 1000) / 10;
    }
    if (!budgeted) return null;
    return Math.round(((actual - budgeted) / Math.abs(budgeted)) * 1000) / 10;
  }

  function setVariance(tr, budgeted) {
    const actual = parseFloat(tr.dataset.actual || "0");
    const cell = tr.querySelector(".variance-cell");
    if (cell) {
      const v = pctOfBase ? budgeted - actual : actual - budgeted;
      cell.textContent = fmt(v);
      cell.classList.toggle("neg", v < 0);
    }
    const pctCell = tr.querySelector(".pct-variance-cell");
    if (pctCell) {
      const pct = pctVariance(actual, budgeted);
      // Same two shapes budget.html's own var() macro renders server-side
      // — a dim em dash with nothing to divide by, otherwise the percent
      // itself, colored only when negative.
      pctCell.innerHTML = pct === null
        ? '<span class="dim">—</span>'
        : '<span' + (pct < 0 ? ' class="neg"' : "") + ">" + pct.toFixed(1) + "%</span>";
    }
  }

  function recompute() {
    const rows = Array.from(table.querySelectorAll("tr[data-id]"));
    const byId = {};
    rows.forEach((tr) => { byId[tr.dataset.id] = tr; });
    const childrenOf = {};
    rows.forEach((tr) => {
      const p = tr.dataset.parent;
      if (p && byId[p]) (childrenOf[p] = childrenOf[p] || []).push(tr);
    });

    function budgetedOf(tr) {
      const input = tr.querySelector(".budget-cell");
      let b;
      if (input) {
        b = parseFloat(input.value) || 0;
      } else {
        b = (childrenOf[tr.dataset.id] || []).reduce((s, k) => s + budgetedOf(k), 0);
        const cell = tr.querySelector(".budgeted-cell");
        if (cell) cell.textContent = fmt(b);
      }
      setVariance(tr, b);
      return b;
    }

    const roots = rows.filter((tr) => !tr.dataset.parent || !byId[tr.dataset.parent]);
    const typeSums = {};
    roots.forEach((tr) => {
      const b = budgetedOf(tr);
      typeSums[tr.dataset.type] = (typeSums[tr.dataset.type] || 0) + b;
    });

    table.querySelectorAll("tr[data-type-subtotal]").forEach((tr) => {
      const b = typeSums[tr.dataset.typeSubtotal] || 0;
      const cell = tr.querySelector(".budgeted-cell");
      if (cell) cell.textContent = fmt(b);
      setVariance(tr, b);
    });

    const netRow = table.querySelector("tr[data-net-row]");
    if (netRow) {
      const b = (typeSums.income || 0) - (typeSums.expense || 0);
      const cell = netRow.querySelector(".budgeted-cell");
      if (cell) cell.textContent = fmt(b);
      setVariance(netRow, b);
    }
  }

  async function save(input) {
    const value = input.value.trim();
    if (value === input.dataset.saved) return;
    status.textContent = "Saving…";
    try {
      const res = await fetch("/budget/cell", {
        method: "POST",
        headers: { Accept: "application/json" },
        body: new URLSearchParams({
          csrf_token: csrfEl.value,
          scenario_id: input.dataset.scenarioId,
          account: input.dataset.account,
          period_month: input.dataset.month,
          amount: value,
        }),
      });
      const data = await res.json();
      if (!data.ok) {
        status.textContent = data.error;
        return;
      }
      input.dataset.saved = value;
      status.textContent = "Saved";
    } catch (e) {
      status.textContent = "Could not reach the server — check your connection and try again.";
    }
  }

  table.addEventListener("input", (e) => {
    if (!e.target.classList.contains("budget-cell")) return;
    recompute();
  });
  table.addEventListener("blur", (e) => {
    if (!e.target.classList || !e.target.classList.contains("budget-cell")) return;
    save(e.target);
  }, true);

  table.querySelectorAll(".budget-cell").forEach((input) => {
    input.dataset.saved = input.value.trim();
  });
})();
