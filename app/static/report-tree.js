/* PostWarden — collapsible account hierarchy on Trial Balance / Balance Sheet.
   Same interaction as the Accounts page's own tree (accounts.js): click a
   summary row to hide/show its descendants, state persisted per browser
   in localStorage. Deliberately a separate, smaller script rather than
   reusing accounts.js directly — that one also wires up the "+" gap-add
   inline account form, which has no meaning on a report.

   Unlike the Accounts page, a report defaults to fully *expanded* on a
   browser's first visit: the whole point of checking a report is usually
   to see the numbers, not to browse structure. Each <table> that wants
   this behavior opts in with data-collapse-key="some-storage-key" and
   rows shaped like:
     <tr data-id="…" data-parent="…" data-has-children="1|0">
       <td class="acct-name depth-N"><span class="tree-toggle"></span>…</td>
       ...
     </tr>
   The chevron itself is CSS-drawn (see style.css), not this empty span's
   text — it just reserves the indent's arrow column. */
(function () {
  function initTree(table) {
    const key = table.dataset.collapseKey;
    const rows = Array.from(table.querySelectorAll("tr[data-id]"));
    const byId = {};
    rows.forEach((tr) => { byId[tr.dataset.id] = tr; });

    let collapsed;
    try {
      collapsed = new Set(JSON.parse(localStorage.getItem(key) || "[]"));
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
      localStorage.setItem(key, JSON.stringify(Array.from(collapsed)));
    }

    function render() {
      rows.forEach((tr) => {
        tr.hidden = hasCollapsedAncestor(tr);
        if (tr.dataset.hasChildren === "1") {
          tr.classList.toggle("collapsed", collapsed.has(tr.dataset.id));
        }
      });
    }

    table.addEventListener("click", (e) => {
      const nameCell = e.target.closest(".acct-name");
      const tr = e.target.closest("tr");
      if (!nameCell || !tr || tr.dataset.hasChildren !== "1") return;
      const id = tr.dataset.id;
      if (collapsed.has(id)) collapsed.delete(id);
      else collapsed.add(id);
      save();
      render();
    });

    render();
  }

  document.querySelectorAll("table[data-collapse-key]").forEach(initTree);
})();
