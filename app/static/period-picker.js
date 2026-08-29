/* PostWarden — period preset dropdown for date-ranged reports (Income
   Statement, Cash Flow — UI_CONSISTENCY_AUDIT.md promoted this from
   Income Statement alone once both pages turned out to be asking the
   same "what happened in this range" question). Purely a convenience
   that fills in the two real date inputs the form actually submits;
   the backend only ever sees plain date_from/date_to, same as
   Journal's filters. Picking "Custom range" just leaves whatever's in
   the two fields for hand-editing.

   Split view's own trailing "Total" column (see income_statement.html)
   wants to read whatever this dropdown currently says ("This Quarter",
   "Custom range", ...) instead of a bare "Total" — but the backend
   itself never learns which preset was picked, only the date_from/
   date_to it resolved to (that's deliberate — see above), so it can't
   render that label itself. Handled here instead, client-side, the same
   place that already knows the preset/date-range relationship: on load
   and on every change, if a #totals-period-label element exists on the
   page, its text becomes this dropdown's current selected option text.
   Degrades gracefully with JS disabled — the server-rendered default is
   the plain, still-correct "Total". */
(function () {
  const preset = document.getElementById("period-preset");
  const fromInput = document.getElementById("date_from");
  const toInput = document.getElementById("date_to");
  const totalsLabel = document.getElementById("totals-period-label");
  if (!preset || !fromInput || !toInput) return;

  function syncTotalsLabel() {
    if (totalsLabel) totalsLabel.textContent = preset.options[preset.selectedIndex].text;
  }

  const iso = (d) => d.toISOString().slice(0, 10);
  const today = new Date();

  function monthRange(year, month) {
    // month is 0-based; day 0 of the *next* month is the last day of this one.
    return [iso(new Date(year, month, 1)), iso(new Date(year, month + 1, 0))];
  }

  function quarterRange(year, quarterIndex0) {
    const startMonth = quarterIndex0 * 3;
    return [iso(new Date(year, startMonth, 1)), iso(new Date(year, startMonth + 3, 0))];
  }

  function rangeFor(value) {
    const y = today.getFullYear(), m = today.getMonth();
    const q = Math.floor(m / 3);
    const todayIso = iso(today);
    switch (value) {
      case "this_month": return [monthRange(y, m)[0], todayIso];
      case "last_month": return monthRange(y, m - 1);
      case "this_quarter": return [quarterRange(y, q)[0], todayIso];
      case "last_quarter": return q === 0 ? quarterRange(y - 1, 3) : quarterRange(y, q - 1);
      case "this_year": return [`${y}-01-01`, todayIso];
      case "last_year": return [`${y - 1}-01-01`, `${y - 1}-12-31`];
      default: return null; // custom — leave the fields alone
    }
  }

  preset.addEventListener("change", () => {
    const range = rangeFor(preset.value);
    syncTotalsLabel();
    if (!range) return;
    fromInput.value = range[0];
    toInput.value = range[1];
  });

  // Reflect the current from/to back onto the dropdown on load, so a
  // bookmarked or reloaded URL doesn't silently show "Custom range" when
  // it's actually exactly "This month" — best-effort, matched by value.
  const current = JSON.stringify([fromInput.value, toInput.value]);
  for (const opt of preset.options) {
    if (opt.value === "custom") continue;
    if (JSON.stringify(rangeFor(opt.value)) === current) {
      preset.value = opt.value;
      break;
    }
  }
  syncTotalsLabel();
})();
