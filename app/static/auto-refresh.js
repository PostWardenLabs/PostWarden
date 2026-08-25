/* Libro — auto-refresh a filter bar when a combobox or date picker
   changes, instead of waiting for its Refresh/Filter/Go button. Every
   `<form class="bar" method="get">` on the page gets this automatically
   (see enhanceAll() below) — that's every report's filter form and the
   Journal's, all built the same way.

   Deliberately scoped to selects and date fields only, via a single
   delegated "change" listener on the form rather than one per field:
   combobox.js and datepicker.js both dispatch a real bubbling "change"
   on their underlying <select>/<input> when a value is picked, so this
   fires the same way whether a person used the fancy widget or (with JS
   disabled, or just habit) typed straight into the plain field
   underneath. A text field (Search, Amount) or the tag picker never
   matches, so a submit only ever happens on a deliberate pick, not every
   keystroke. */
(function () {
  function isAutoRefreshField(el) {
    if (!el) return false;
    if (el.tagName === "SELECT") return true;
    if (el.tagName === "INPUT" &&
        (el.type === "date" || el.type === "month" || el.classList.contains("date-input"))) return true;
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
    document.querySelectorAll("form.bar").forEach((form) => {
      if (form.method.toLowerCase() === "get") enhance(form);
    });
  }

  document.addEventListener("DOMContentLoaded", enhanceAll);
})();
