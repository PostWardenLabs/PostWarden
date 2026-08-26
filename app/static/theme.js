/* PostWarden — theme picker. Loaded on every page (see base.html).
   The actual switch-before-paint logic lives inline in base.html's <head>,
   so a saved choice applies before the stylesheet renders; this file only
   wires the <select> once the page is interactive. */
(function () {
  var KEY = "postwarden-theme";
  var DEFAULT = "ledger";
  var select = document.getElementById("theme-select");
  if (!select) return;

  select.value = localStorage.getItem(KEY) || DEFAULT;

  select.addEventListener("change", function () {
    var theme = select.value;
    if (theme === DEFAULT) {
      document.documentElement.removeAttribute("data-theme");
      localStorage.removeItem(KEY);
    } else {
      document.documentElement.setAttribute("data-theme", theme);
      localStorage.setItem(KEY, theme);
    }
  });
})();
