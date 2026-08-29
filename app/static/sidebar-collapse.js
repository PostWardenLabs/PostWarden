/* PostWarden — collapsible sidebar sections (Books/Reports/Setup).
   Clicking a group's own label toggles its "collapsed" class, hiding
   that group's links; state persists per browser in localStorage, one
   key per group (data-sidebar-key) rather than one shared key, so
   collapsing Reports doesn't touch Books' own saved state — same
   per-thing-not-shared-key convention report-tree.js's own per-table
   data-collapse-key already uses.

   No head-script preload the way theme/font/sidebar-pin get (see
   base.html's own inline <script>) — those avoid a real layout-shifting
   flash (colors flipping, the whole page's margin jumping when pinned);
   this is just a few nav links briefly visible before collapsing, low
   enough stakes not to need running before the stylesheet does. */
(function () {
  const KEY_PREFIX = "postwarden-sidebar-collapsed-";
  document.querySelectorAll(".sidebar-group[data-sidebar-key]").forEach((group) => {
    const key = KEY_PREFIX + group.dataset.sidebarKey;
    const label = group.querySelector(".sidebar-label");
    if (!label) return;

    function setCollapsed(collapsed) {
      group.classList.toggle("collapsed", collapsed);
      label.setAttribute("aria-expanded", String(!collapsed));
    }
    setCollapsed(localStorage.getItem(key) === "1");

    label.addEventListener("click", () => {
      const collapsed = !group.classList.contains("collapsed");
      setCollapsed(collapsed);
      localStorage.setItem(key, collapsed ? "1" : "0");
    });
  });
})();
