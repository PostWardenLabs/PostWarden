/* PostWarden — auto-refresh a filter bar when a combobox or date picker
   changes, instead of waiting for its Refresh/Filter/Go button. Every
   `<form class="bar" method="get">` on the page gets this automatically
   (see enhanceAll() below) — a single row with its fields as direct
   children of the form, so .bar's flex layout can sit right on the form
   itself with nothing extra needed. Staging and Balance Sheet/Trial
   Balance are shaped this way (no second row of their own).

   A filter form with a second row below its fields (Journal's Clear
   filters/Export CSV; Income Statement/Variance's Hide zero
   balances/% variance toggle/Export CSV; Budget Grid's toggle/Go/prev-
   next) wraps the fields in a nested `<div class="bar">` instead, since
   putting .bar on the form too would flex the form's own children (that
   div, the second row) side by side instead of stacking them.
   `data-auto-refresh` is the same hook with no such layout side effect
   — see any of those templates' own filter form for why it carries
   this instead of the class.

   Deliberately scoped to selects, date fields, checkboxes, and the tag
   picker's own hidden value field — never a free-typed text field — via
   a single delegated "change" listener on the form rather than one per
   field: combobox.js and datepicker.js both dispatch a real bubbling
   "change" on their underlying <select>/<input> when a value is picked,
   so this fires the same way whether a person used the fancy widget or
   (with JS disabled, or just habit) typed straight into the plain field
   underneath. A checkbox (Trial Balance's "show zero balances"/"show
   true balances", Balance Sheet's "show true balances") is a discrete
   pick exactly like a <select> option, not something typed. So is a
   tag: tags.js's own sync() dispatches "change" on its hidden input
   exactly once per add/remove, never while just typing toward one (the
   visible text field there is a separate, unnamed element that never
   submits anything itself) — matched here by reaching for its
   .tag-input wrapper, not by name, so this keeps working if that field
   is ever reused somewhere with a different name. Search and Amount
   stay excluded — refreshing on every keystroke there would just be
   noise — Search has its own submit icon instead, and Enter still
   submits from any text field regardless. */
(function () {
  function isAutoRefreshField(el) {
    if (!el) return false;
    if (el.tagName === "SELECT") return true;
    if (el.tagName === "INPUT" &&
        (el.type === "date" || el.type === "month" || el.type === "checkbox" ||
         el.classList.contains("date-input"))) return true;
    if (el.tagName === "INPUT" && el.type === "hidden" && el.closest(".tag-input")) return true;
    return false;
  }

  function enhance(form) {
    if (form.dataset.autoRefreshBound) return;
    form.dataset.autoRefreshBound = "1";
    form.addEventListener("change", (e) => {
      if (isAutoRefreshField(e.target)) form.requestSubmit();
    });
  }

  function enhanceAll() {
    document.querySelectorAll("form.bar, form[data-auto-refresh]").forEach((form) => {
      if (form.method.toLowerCase() === "get") enhance(form);
    });
  }

  document.addEventListener("DOMContentLoaded", enhanceAll);
})();
