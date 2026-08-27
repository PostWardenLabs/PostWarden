/* PostWarden — font bundle picker. Loaded on every page (see base.html).
   Same shape as theme.js right next to it: the actual switch-before-paint
   logic lives inline in base.html's <head> so a saved bundle applies
   before the stylesheet renders, this file only wires the <select> once
   the page is interactive. combobox.js enhances it the same way it does
   every other <select> — nothing font-specific to do for that part.

   A separate localStorage key and a separate `data-font` attribute from
   theme.js's own `data-theme` — Font and Theme are independent choices
   (see style.css's font-bundle block for how data-font interacts with a
   theme that has its own font opinion, like Monaspace's --mono). */
(function () {
  var KEY = "postwarden-font";
  var DEFAULT = "system";
  var select = document.getElementById("font-select");
  if (!select) return;

  select.value = localStorage.getItem(KEY) || DEFAULT;

  select.addEventListener("change", function () {
    var font = select.value;
    if (font === DEFAULT) {
      document.documentElement.removeAttribute("data-font");
      localStorage.removeItem(KEY);
    } else {
      document.documentElement.setAttribute("data-font", font);
      localStorage.setItem(KEY, font);
    }
  });
})();
