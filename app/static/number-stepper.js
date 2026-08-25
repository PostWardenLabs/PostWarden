/* PostWarden — custom up/down stepper for <input type="number">, replacing
   the browser's own spinner arrows with the site's own chevron so a
   plain OS control doesn't sit inside an otherwise hand-styled page —
   same idea as datepicker.js: a skin over the native input, not a
   replacement for it. Typing a value directly, and the keyboard's own
   Up/Down arrows, still work exactly as before; input stays
   type="number" throughout, so nothing server-side changes. Every
   number input on the page gets this automatically (see enhanceAll()
   below). */
(function () {
  function updateDisabled(input) {
    const wrap = input.closest(".number-stepper");
    if (!wrap) return;
    const up = wrap.querySelector(".step-up");
    const down = wrap.querySelector(".step-down");
    const cur = input.value === "" ? null : Number(input.value);
    const max = input.max !== "" ? Number(input.max) : null;
    const min = input.min !== "" ? Number(input.min) : null;
    if (up) up.disabled = input.disabled || (cur !== null && max !== null && cur >= max);
    if (down) down.disabled = input.disabled || (cur !== null && min !== null && cur <= min);
  }

  function step(input, dir) {
    const before = input.value;
    try {
      if (dir > 0) input.stepUp(); else input.stepDown();
    } catch (e) {
      // stepUp/stepDown throw if the result would land outside min/max
      // (even by a fraction of `step`) — fall back to a plain
      // arithmetic nudge, clamped to bounds.
      const s = Number(input.step) || 1;
      const min = input.min !== "" ? Number(input.min) : -Infinity;
      const max = input.max !== "" ? Number(input.max) : Infinity;
      const cur = Number(input.value) || 0;
      input.value = String(Math.min(max, Math.max(min, cur + dir * s)));
    }
    if (input.value !== before) {
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
    updateDisabled(input);
  }

  function enhanceNumber(input) {
    if (input.dataset.enhanced) return;
    input.dataset.enhanced = "1";
    input.classList.add("number-input");

    const wrap = document.createElement("span");
    wrap.className = "number-stepper";
    input.insertAdjacentElement("beforebegin", wrap);
    wrap.appendChild(input);

    const up = document.createElement("button");
    up.type = "button";
    up.className = "number-step step-up";
    up.setAttribute("aria-label", "Increase");
    up.tabIndex = -1;
    up.innerHTML = '<span class="chevron chevron-up"></span>';
    wrap.appendChild(up);

    const down = document.createElement("button");
    down.type = "button";
    down.className = "number-step step-down";
    down.setAttribute("aria-label", "Decrease");
    down.tabIndex = -1;
    down.innerHTML = '<span class="chevron chevron-down"></span>';
    wrap.appendChild(down);

    up.addEventListener("click", () => step(input, 1));
    down.addEventListener("click", () => step(input, -1));
    input.addEventListener("input", () => updateDisabled(input));
    updateDisabled(input);
  }

  function enhanceAll(root) {
    (root || document).querySelectorAll('input[type="number"]:not([data-enhanced])').forEach(enhanceNumber);
  }

  document.addEventListener("DOMContentLoaded", () => enhanceAll());
  window.PostWardenNumberStepper = { enhance: enhanceNumber, enhanceAll };
})();
