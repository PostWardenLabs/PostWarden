/* PostWarden — optional "digits fill in from the right" mode for amount fields
   (the debit/credit inputs in every entry grid), the same input style as
   a bank transfer app or a POS terminal: typing 6200 produces 62.00, and
   there's never a decimal point to type. Off by default, toggled from
   Settings (see the checkbox wiring at the bottom).

   Applies to any input.amount via event delegation on `document` — that
   covers rows app.js adds to the entry grid after page load without this
   file needing to know anything about app.js. */
(function () {
  const KEY = "libro-cents-entry";

  function enabled() {
    return localStorage.getItem(KEY) === "1";
  }

  function isAmountField(el) {
    return !!el && el.tagName === "INPUT" && el.classList.contains("amount");
  }

  function parseCents(value) {
    const n = parseFloat(value);
    return Number.isNaN(n) ? 0 : Math.round(n * 100);
  }

  function setFromCents(field, cents) {
    cents = Math.max(0, Math.min(cents, 99999999999)); // a sane ceiling, not a real limit
    field.value = (cents / 100).toFixed(2);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }

  // A fresh focus always starts a fresh number — the first digit typed
  // after focusing (or re-focusing) a field replaces whatever was there
  // rather than shifting on top of it, same as tapping an amount field in
  // a banking app. Only digits typed *after* that first one keep shifting
  // left within this same focus session.
  document.addEventListener("focus", (e) => {
    if (!enabled() || !isAmountField(e.target)) return;
    delete e.target.dataset.centsStarted;
  }, true);

  document.addEventListener("keydown", (e) => {
    if (!enabled() || !isAmountField(e.target)) return;
    const field = e.target;
    if (/^[0-9]$/.test(e.key)) {
      e.preventDefault();
      const cents = field.dataset.centsStarted === "1"
        ? parseCents(field.value) * 10 + Number(e.key)
        : Number(e.key);
      field.dataset.centsStarted = "1";
      setFromCents(field, cents);
    } else if (e.key === "Backspace") {
      e.preventDefault();
      field.dataset.centsStarted = "1";
      setFromCents(field, Math.floor(parseCents(field.value) / 10));
    } else if (e.key.length > 1) {
      // Tab / arrows / Enter / Escape / etc. — navigation and control
      // keys pass through untouched; the next digit still replaces.
      delete field.dataset.centsStarted;
    } else {
      // Anything else typeable (a literal ".", letters, ...) is exactly
      // what this mode exists to make unnecessary — block it rather than
      // let it desync the field from the digit buffer.
      e.preventDefault();
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    const toggle = document.getElementById("cents-entry-toggle");
    if (!toggle) return;
    toggle.checked = enabled();
    toggle.addEventListener("change", () => {
      if (toggle.checked) localStorage.setItem(KEY, "1");
      else localStorage.removeItem(KEY);
    });
  });

  window.PostWardenCentsEntry = { KEY, enabled };
})();
