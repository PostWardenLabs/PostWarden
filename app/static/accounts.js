/* Libro — collapsible chart of accounts.
   Summary accounts (the ones with children) get a toggle arrow, revealed
   on hover, that shows/hides their descendants. Collapse state persists
   in localStorage per browser, not per user in the database — it's a
   view preference, not data. */
(function () {
  const body = document.getElementById("accounts-body");
  if (!body) return;

  const STORAGE_KEY = "libro-accounts-collapsed";
  const rows = Array.from(body.querySelectorAll("tr"));
  const byId = {};
  rows.forEach((tr) => { byId[tr.dataset.id] = tr; });

  let collapsed;
  try {
    collapsed = new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"));
  } catch (e) {
    collapsed = new Set();
  }

  function hasCollapsedAncestor(tr) {
    let parentId = tr.dataset.parent;
    while (parentId) {
      if (collapsed.has(parentId)) return true;
      const parentTr = byId[parentId];
      parentId = parentTr ? parentTr.dataset.parent : "";
    }
    return false;
  }

  function save() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(collapsed)));
  }

  function render() {
    rows.forEach((tr) => {
      tr.hidden = hasCollapsedAncestor(tr);
      if (tr.dataset.postable === "0") {
        tr.classList.toggle("collapsed", collapsed.has(tr.dataset.id));
      }
    });
  }

  body.addEventListener("click", (e) => {
    const nameCell = e.target.closest(".acct-name");
    const tr = e.target.closest("tr");
    if (!nameCell || !tr || tr.dataset.postable !== "0") return;
    const id = tr.dataset.id;
    if (collapsed.has(id)) collapsed.delete(id);
    else collapsed.add(id);
    save();
    render();
  });

  render();
})();
