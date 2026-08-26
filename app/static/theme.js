/* PostWarden — theme picker. Loaded on every page (see base.html).
   The actual switch-before-paint logic lives inline in base.html's <head>,
   so a saved choice applies before the stylesheet renders; this file only
   wires up Settings' theme swatch grid once the page is interactive —
   clicking a swatch, and keeping exactly one marked .active. */
(function () {
  var KEY = "postwarden-theme";
  var DEFAULT = "ledger";
  var swatches = document.querySelectorAll(".theme-swatch");
  if (!swatches.length) return;

  var current = localStorage.getItem(KEY) || DEFAULT;

  function markActive(theme) {
    swatches.forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.theme === theme);
    });
  }
  markActive(current);

  swatches.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var theme = btn.dataset.theme;
      if (theme === DEFAULT) {
        document.documentElement.removeAttribute("data-theme");
        localStorage.removeItem(KEY);
      } else {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem(KEY, theme);
      }
      markActive(theme);
    });
  });
})();
