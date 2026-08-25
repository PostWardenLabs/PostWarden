/* PostWarden — collapsible, drillable chart of accounts.
   Summary accounts (the ones with children) get a toggle arrow, revealed
   on hover, that shows/hides their descendants. Collapse state persists
   in localStorage per browser, not per user in the database — it's a
   view preference, not data.

   True tree browsing: on a browser's first visit (nothing in localStorage
   yet), every summary account starts collapsed — Assets shows only until
   you click it, which reveals Bank/Cash but leaves Bank itself collapsed,
   so its own children (Checking, Savings, ...) need their own click. Once
   a person starts customizing, their exact per-account choices persist
   exactly as before.

   Also wires the "+" gap rows between account rows (see accounts.html) —
   an Actual Budget-style "hover between two rows to add a category here"
   affordance, alternative to the form at the bottom of the page. */
(function () {
  const body = document.getElementById("accounts-body");
  if (!body) return;

  const STORAGE_KEY = "libro-accounts-collapsed";
  const rows = Array.from(body.querySelectorAll("tr.acct-row"));
  const gapRows = Array.from(body.querySelectorAll("tr.add-gap"));
  const byId = {};
  rows.forEach((tr) => { byId[tr.dataset.id] = tr; });

  let collapsed;
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored !== null) {
    try {
      collapsed = new Set(JSON.parse(stored));
    } catch (e) {
      collapsed = new Set();
    }
  } else {
    collapsed = new Set(
      rows.filter((tr) => tr.dataset.postable === "0").map((tr) => tr.dataset.id));
  }

  function hasCollapsedAncestor(tr) {
    let parentId = tr.dataset.parent;
    while (parentId) {
      if (collapsed.has(parentId)) return true;
      const parentTr = byId[parentId];
      parentId = parentTr ? parentTr.dataset.parent : "";
    }
    return false;
  }

  function save() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(collapsed)));
  }

  function render() {
    rows.forEach((tr) => {
      tr.hidden = hasCollapsedAncestor(tr);
      if (tr.dataset.postable === "0") {
        tr.classList.toggle("collapsed", collapsed.has(tr.dataset.id));
      }
    });
    // A gap row tracks whichever account row it's rendered next to (see
    // _accounts_with_gaps in main.py) — hidden exactly when that row is.
    gapRows.forEach((tr) => {
      const tracked = byId[tr.dataset.track];
      tr.hidden = tracked ? tracked.hidden : false;
    });
  }

  body.addEventListener("click", (e) => {
    const nameCell = e.target.closest(".acct-name");
    const tr = e.target.closest("tr");
    if (!nameCell || !tr || tr.dataset.postable !== "0") return;
    const id = tr.dataset.id;
    if (collapsed.has(id)) collapsed.delete(id);
    else collapsed.add(id);
    save();
    render();
  });

  // "+" gap rows: click to reveal the inline add-category form, Cancel (or
  // clicking elsewhere) to collapse it back down. Which parent/type a new
  // account gets depends on whichever two rows are *currently visible*
  // right around this gap — not the full flat list — since a collapsed
  // summary account hides its own children from being "the next row."
  // E.g. Liabilities collapsed (hiding Credit Card) followed by Equity:
  // the gap between them must default to a new top-level account, not a
  // sibling of the hidden Credit Card.
  function nearestVisible(tr, direction) {
    let el = tr[direction];
    while (el && (el.tagName !== "TR" || !el.classList.contains("acct-row") || el.hidden)) {
      el = el[direction];
    }
    return el || null;
  }

  gapRows.forEach((tr) => {
    const trigger = tr.querySelector(".add-gap-trigger");
    const form = tr.querySelector(".add-gap-form");
    const cancel = tr.querySelector(".add-gap-cancel");
    const parentField = form && form.querySelector('input[name="parent_id"]');
    const typeField = form && form.querySelector(".add-gap-type");
    if (!trigger || !form) return;
    trigger.addEventListener("click", () => {
      gapRows.forEach((other) => other.classList.remove("open"));

      const prev = nearestVisible(tr, "previousElementSibling");
      const next = nearestVisible(tr, "nextElementSibling");
      let parentId = "";
      let type = next ? next.dataset.type : "";
      if (prev) {
        // A summary account with zero children anywhere (not just
        // visible ones — a brand new one collapse-tracks nothing either
        // way) is otherwise indistinguishable here from "insert a
        // sibling after it": there's no child row to compare `next`
        // against. Default to "first child of prev" in that case —
        // an empty summary account's whole reason to exist is to hold
        // children, so that's the far more useful guess.
        const prevIsEmptySummary = prev.dataset.postable === "0" &&
          !body.querySelector('tr.acct-row[data-parent="' + prev.dataset.id + '"]');
        if (prevIsEmptySummary || (next && next.dataset.parent === prev.dataset.id)) {
          parentId = prev.dataset.id; // first child of prev
        } else {
          parentId = prev.dataset.parent; // sibling of prev
        }
        type = prev.dataset.type;
      }
      parentField.value = parentId || "";
      // combobox.js wraps this <select> in its own sibling div (the
      // visible text input + panel) — hiding the select itself (already
      // moot, combobox.js's own CSS hides it unconditionally) does
      // nothing to that wrapper, which is what's actually on screen.
      const typeWrap = typeField.closest(".combobox") || typeField;
      typeWrap.hidden = !!parentId;
      typeField.hidden = !!parentId;
      if (!parentId && type) {
        typeField.value = type;
        // combobox.js skins this <select> into a wrap + visible text
        // input, but only resyncs that text on its own click/keyboard
        // paths — not on a value set from outside like this one — so
        // without this the field would submit the right type but *show*
        // whatever it displayed last.
        const comboInput = typeField.parentElement &&
          typeField.parentElement.querySelector(".combobox-input");
        const label = typeField.options[typeField.selectedIndex];
        if (comboInput && label) comboInput.value = label.textContent.trim();
      }

      tr.classList.add("open");
      const nameField = form.querySelector('input[name="name"]');
      if (nameField) nameField.focus();
    });
    if (cancel) cancel.addEventListener("click", () => tr.classList.remove("open"));
    document.addEventListener("mousedown", (e) => {
      if (tr.classList.contains("open") && !tr.contains(e.target)) {
        tr.classList.remove("open");
      }
    });
  });

  render();
})();
