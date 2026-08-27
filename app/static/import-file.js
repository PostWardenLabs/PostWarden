/* PostWarden — Import's CSV file field (see its own comment in
   style.css for why the native file input's rendering is hidden at
   all). The real <input type="file"> stays keyboard/label-operable
   (.sr-only, not display:none) — this just keeps the visible button +
   name box in sync with it: the button proxies its click to the real
   input (clicking the label's own text does this natively already, via
   its for=, without any JS — this covers the button specifically, since
   an interactive element inside a <label> doesn't get the label's own
   click forwarded to it), and "change" on the real input updates the
   name box to whatever was actually picked, or back to the placeholder
   if the picker was cancelled with nothing chosen. */
(function () {
  const input = document.getElementById("import-file-input");
  const btn = document.getElementById("import-file-btn");
  const nameBox = document.getElementById("import-file-name");
  if (!input || !btn || !nameBox) return;

  const placeholder = nameBox.textContent;

  btn.addEventListener("click", () => input.click());
  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    nameBox.textContent = file ? file.name : placeholder;
    nameBox.classList.toggle("dim", !file);
  });
})();
