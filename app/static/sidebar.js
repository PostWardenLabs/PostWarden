/* PostWarden — hamburger sidebar. Hovering the hamburger (or the sidebar
   itself) previews the menu; it closes again once the mouse leaves both.
   Clicking the hamburger pins it open instead — the sidebar stays put
   (and pushes the page over, see style.css's html.sidebar-pinned rules)
   until clicked again. Pinned state persists in localStorage per browser,
   same pattern as the theme picker; base.html applies it before the
   stylesheet renders so there's no flash of the unpinned layout. */
(function () {
  const toggle = document.getElementById("sidebar-toggle");
  const sidebar = document.getElementById("sidebar");
  if (!toggle || !sidebar) return;

  const KEY = "postwarden-sidebar-pinned";
  const root = document.documentElement;
  let closeTimer = null;

  function pinned() { return root.classList.contains("sidebar-pinned"); }

  function open() {
    clearTimeout(closeTimer);
    sidebar.classList.add("open");
    toggle.setAttribute("aria-expanded", "true");
  }

  function scheduleClose() {
    if (pinned()) return;
    clearTimeout(closeTimer);
    // A short grace period — moving the mouse from the hamburger to the
    // sidebar panel crosses a gap of a few pixels; without this, that
    // crossing itself would close the menu before the pointer arrives.
    closeTimer = setTimeout(() => {
      sidebar.classList.remove("open");
      toggle.setAttribute("aria-expanded", "false");
    }, 200);
  }

  toggle.addEventListener("mouseenter", open);
  sidebar.addEventListener("mouseenter", open);
  toggle.addEventListener("mouseleave", scheduleClose);
  sidebar.addEventListener("mouseleave", scheduleClose);

  toggle.addEventListener("click", () => {
    if (pinned()) {
      root.classList.remove("sidebar-pinned");
      localStorage.removeItem(KEY);
      sidebar.classList.remove("open");
      toggle.setAttribute("aria-expanded", "false");
    } else {
      root.classList.add("sidebar-pinned");
      localStorage.setItem(KEY, "1");
      open();
    }
  });

  // Escape closes an unpinned (hover-previewed) sidebar without having to
  // move the mouse back out over it.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !pinned()) {
      sidebar.classList.remove("open");
      toggle.setAttribute("aria-expanded", "false");
    }
  });

  if (pinned()) open();
})();
