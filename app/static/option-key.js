/* PostWarden — shows the real Mac/iPad/iPhone modifier key symbol (⌥)
   in place of the literal "Alt+" text every keyboard-shortcut hint in
   this app is server-rendered with (button labels like "Reverse
   (Alt+R)", and the Help page's own prose walking through all of them).
   BACKLOG.md's own ask: "When device is iPad or Mac show option key
   instead of ALT."

   The underlying shortcuts themselves never change — every keydown
   listener in app.js/entries-select.js/staging.js/etc. checks
   e.altKey, which is what the real Option key on a Mac keyboard (and
   the on-screen/hardware-keyboard equivalent on iPad) actually sets;
   nothing here touches that wiring. This only swaps the *label* text,
   client-side, once on load — a text-node sweep rather than a template
   change in every one of the ~15 spots "Alt+" is hardcoded across
   entries.html/staging.html/scheduled.html/entry_templates.html/
   help.html, so a future new shortcut hint anywhere just works without
   remembering to wire this in again.

   Detection: navigator.userAgentData (the modern replacement for
   navigator.platform, Chromium-only for now) when available, falling
   back to the classic UA-string sniff otherwise — both are fine here
   since the cost of guessing wrong is a label reading "Alt+" on an
   Apple device or "⌥" on a non-Apple one, not a broken shortcut.
   iPadOS Safari's own UA string says "Macintosh" (has done since
   iPadOS 13's default desktop-class UA), indistinguishable here from a
   real Mac — deliberately not disambiguated further, since both should
   show the same ⌥ symbol regardless of which of the two it actually is. */
(function () {
  function isApplePlatform() {
    const uaData = navigator.userAgentData;
    if (uaData && uaData.platform) return uaData.platform === "macOS";
    return /Mac|iPhone|iPad|iPod/.test(navigator.userAgent || navigator.platform || "");
  }

  if (!isApplePlatform()) return;

  // Matches "Alt+R", "Alt+S", ... — always one letter, per every actual
  // shortcut hint in this app (see help.html's own "Alt shortcuts use
  // the physical key" note) — and swaps in "⌥R" etc., no "+", matching
  // how macOS's own menus show a modifier symbol directly against the
  // key rather than spelling out the join.
  const ALT_SHORTCUT = /\bAlt\+([A-Z])\b/g;

  function swapTextNode(node) {
    const replaced = node.nodeValue.replace(ALT_SHORTCUT, "⌥$1");
    if (replaced !== node.nodeValue) node.nodeValue = replaced;
  }

  function sweep(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        // Skip <script>/<style> text content — never real shortcut-hint
        // prose, and no reason to run a regex over inline JS/CSS source.
        const tag = node.parentElement && node.parentElement.tagName;
        return tag === "SCRIPT" || tag === "STYLE"
          ? NodeFilter.FILTER_REJECT
          : NodeFilter.FILTER_ACCEPT;
      },
    });
    let node;
    while ((node = walker.nextNode())) swapTextNode(node);
  }

  document.addEventListener("DOMContentLoaded", () => sweep(document.body));
})();
