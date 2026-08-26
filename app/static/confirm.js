/* PostWarden — a confirm dialog that actually looks like the app, not the
   browser's own unstyleable alert skin. window.PostWardenConfirm.ask(message,
   opts) returns a Promise<boolean>, same true/false shape as the native
   confirm() it replaces, just asynchronous — awaiting a click instead of
   blocking the whole page.

   Also wires up the common case on its own: any <form data-confirm="...">
   (or a specific submit <button data-confirm="...">, for a button that
   overrides the form's own action/method — see Reject on Staging) gets
   intercepted, shows the modal, and — only if confirmed — resubmits itself
   via form.requestSubmit(submitter), which preserves which button (and
   therefore which formaction/formmethod) actually triggered it. A form or
   button whose message depends on something computed at click time (the
   Staging "Approve N entries" count) calls ask() directly instead — see
   staging.js. */
(function () {
  let overlay, modal, messageEl, okBtn, cancelBtn, resolveFn, previouslyFocused;

  function build() {
    overlay = document.createElement("div");
    overlay.className = "confirm-overlay";
    overlay.hidden = true;
    modal = document.createElement("div");
    modal.className = "confirm-modal";
    modal.setAttribute("role", "alertdialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "confirm-message");
    const message = document.createElement("p");
    message.className = "confirm-message";
    message.id = "confirm-message";
    const actions = document.createElement("div");
    actions.className = "confirm-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "quiet confirm-cancel";
    const ok = document.createElement("button");
    ok.type = "button";
    ok.className = "confirm-ok";
    actions.append(cancel, ok);
    modal.append(message, actions);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    messageEl = message; okBtn = ok; cancelBtn = cancel;
    okBtn.addEventListener("click", () => settle(true));
    cancelBtn.addEventListener("click", () => settle(false));
    // Clicking the dimmed backdrop cancels, same as clicking outside any
    // other popover in this app (the date picker, a combobox panel).
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) settle(false); });
    document.addEventListener("keydown", (e) => {
      if (overlay.hidden) return;
      if (e.key === "Escape") { settle(false); return; }
      if (e.key !== "Tab") return;
      // A tiny two-item focus trap — Tab/Shift+Tab never leaves the modal
      // while it's open, same expectation as any real dialog.
      const items = [cancelBtn, okBtn];
      e.preventDefault();
      const i = items.indexOf(document.activeElement);
      const next = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : (i === items.length - 1 ? 0 : i + 1);
      items[next].focus();
    });
  }

  function settle(result) {
    overlay.hidden = true;
    if (previouslyFocused && document.contains(previouslyFocused)) previouslyFocused.focus();
    const fn = resolveFn;
    resolveFn = null;
    if (fn) fn(result);
  }

  // opts.danger styles OK in --red (Delete/Reject — data actually gone);
  // leave it off for a normal, reversible-enough action (Reverse an
  // entry, Approve a staged one) where red would overstate the risk.
  function ask(message, opts) {
    opts = opts || {};
    if (!overlay) build();
    messageEl.textContent = message;
    okBtn.textContent = opts.okLabel || "OK";
    cancelBtn.textContent = opts.cancelLabel || "Cancel";
    okBtn.classList.toggle("danger", !!opts.danger);
    previouslyFocused = document.activeElement;
    overlay.hidden = false;
    // Cancel gets initial focus regardless of danger — a stray Enter
    // press should never be the thing that confirms a destructive action.
    cancelBtn.focus();
    return new Promise((resolve) => { resolveFn = resolve; });
  }

  window.PostWardenConfirm = { ask };

  // The generic data-confirm wiring described up top.
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (form.dataset.confirmBypass === "1") { delete form.dataset.confirmBypass; return; }
    const submitter = e.submitter;
    const msg = (submitter && submitter.dataset.confirm) || form.dataset.confirm;
    if (!msg) return;
    const danger = !!((submitter && submitter.dataset.confirmDanger) || form.dataset.confirmDanger);
    e.preventDefault();
    ask(msg, { danger }).then((confirmed) => {
      if (!confirmed) return;
      form.dataset.confirmBypass = "1";
      form.requestSubmit(submitter || undefined);
    });
  });
})();
