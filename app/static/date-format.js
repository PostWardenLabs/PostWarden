/* PostWarden — client-side date display formatting. Every {{ x | dateformat }}
   filter output (see app/main.py) is a <span class="date-fmt"
   data-value="2026-08-26"> holding the plain ISO text as a no-JS
   fallback; this rewrites its displayed text using the format saved
   from Settings (localStorage, same client-preference pattern as the
   theme picker and money-format.js — the date itself, stored in
   Postgres, never changes).

   Parses the ISO string by hand rather than `new Date("2026-08-26")` —
   that parses as UTC midnight, which `toLocaleDateString()` etc. then
   render as the *previous* day in any timezone behind UTC. Every date
   in this app is a plain DATE column (no time, no timezone), so this
   only ever needs to reorder y/m/d — there's no real time-zone
   conversion to do, and pulling one in by accident is the bug to
   avoid. */
(function () {
  const KEY = "postwarden-date-format";
  const DEFAULT = "iso";
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function pref() {
    try {
      return localStorage.getItem(KEY) || DEFAULT;
    } catch (e) {
      return DEFAULT;
    }
  }

  function format(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    if (!m) return iso || "";
    const [, y, mo, d] = m;
    const moNum = parseInt(mo, 10);
    switch (pref()) {
      case "us": return `${mo}/${d}/${y}`;
      case "eu": return `${d}/${mo}/${y}`;
      case "long": return `${MONTHS[moNum - 1]} ${parseInt(d, 10)}, ${y}`;
      case "iso":
      default: return `${y}-${mo}-${d}`;
    }
  }

  function applyAll(root) {
    (root || document).querySelectorAll(".date-fmt[data-value]").forEach((el) => {
      el.textContent = format(el.dataset.value);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    applyAll();

    // Settings form, if present on this page (see settings.html).
    const select = document.getElementById("date-format-select");
    if (!select) return;
    select.value = pref();
    select.addEventListener("change", () => {
      localStorage.setItem(KEY, select.value);
      applyAll(document);
    });
  });

  window.PostWardenDate = { KEY, format, pref, applyAll };
})();
