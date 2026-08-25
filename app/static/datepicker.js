/* Libro — calendar date picker, progressively enhancing a plain
   <input type="date">. Every date input on the page gets this
   automatically (see enhanceAll() below).

   Switches the input to type="text" so it can be styled and paired with
   a calendar popup — but it still holds (and submits) the exact same
   YYYY-MM-DD value a native date input would, so nothing server-side
   changes. Typing a date directly still works; the calendar is the
   alternative, not a replacement. Without JS, the field stays a native
   date input — this is a skin, not a new source of truth. */
(function () {
  const DOW = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
  const MONTHS = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];

  function pad2(n) { return String(n).padStart(2, "0"); }
  function toISO(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`; }
  function parseISO(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec((s || "").trim());
    if (!m) return null;
    const d = new Date(+m[1], +m[2] - 1, +m[3]);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function enhanceDate(input) {
    if (input.dataset.enhanced) return;
    input.dataset.enhanced = "1";

    input.type = "text";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.placeholder = input.placeholder || "YYYY-MM-DD";
    input.pattern = "\\d{4}-\\d{2}-\\d{2}";
    input.classList.add("date-input");

    const wrap = document.createElement("div");
    wrap.className = "datepicker";
    input.insertAdjacentElement("beforebegin", wrap);
    wrap.appendChild(input);

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "date-trigger";
    trigger.setAttribute("aria-label", "Open calendar");
    if (input.disabled) trigger.disabled = true;
    trigger.innerHTML = '<span class="chevron chevron-down"></span>';
    wrap.appendChild(trigger);

    const panel = document.createElement("div");
    panel.className = "date-panel";
    panel.hidden = true;
    wrap.appendChild(panel);

    let viewDate = parseISO(input.value) || new Date();

    function render() {
      const year = viewDate.getFullYear();
      const month = viewDate.getMonth();
      const first = new Date(year, month, 1);
      const startOffset = (first.getDay() + 6) % 7; // Monday-first week
      const daysInMonth = new Date(year, month + 1, 0).getDate();
      const selected = parseISO(input.value);
      const todayISO = toISO(new Date());

      panel.innerHTML = "";

      const head = document.createElement("div");
      head.className = "date-panel-head";
      const prev = document.createElement("button");
      prev.type = "button"; prev.className = "date-nav"; prev.dataset.dir = "-1";
      prev.textContent = "‹"; prev.setAttribute("aria-label", "Previous month");
      const label = document.createElement("span");
      label.textContent = `${MONTHS[month]} ${year}`;
      const next = document.createElement("button");
      next.type = "button"; next.className = "date-nav"; next.dataset.dir = "1";
      next.textContent = "›"; next.setAttribute("aria-label", "Next month");
      head.append(prev, label, next);
      panel.appendChild(head);

      const grid = document.createElement("div");
      grid.className = "date-grid";
      DOW.forEach((d) => {
        const dow = document.createElement("span");
        dow.className = "date-dow";
        dow.textContent = d;
        grid.appendChild(dow);
      });
      for (let i = 0; i < startOffset; i++) grid.appendChild(document.createElement("span"));
      for (let day = 1; day <= daysInMonth; day++) {
        const iso = `${year}-${pad2(month + 1)}-${pad2(day)}`;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "date-day";
        if (selected && iso === toISO(selected)) btn.classList.add("selected");
        if (iso === todayISO) btn.classList.add("today");
        btn.textContent = String(day);
        btn.dataset.iso = iso;
        grid.appendChild(btn);
      }
      panel.appendChild(grid);

      const foot = document.createElement("div");
      foot.className = "date-panel-foot";
      const todayBtn = document.createElement("button");
      todayBtn.type = "button"; todayBtn.className = "quiet date-today";
      todayBtn.textContent = "Today";
      foot.appendChild(todayBtn);
      panel.appendChild(foot);
    }

    function setValue(iso) {
      input.value = iso;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function open() {
      viewDate = parseISO(input.value) || viewDate;
      render();
      if (panel.hidden) {
        panel.hidden = false;
        document.addEventListener("mousedown", onDocMouseDown, true);
      }
    }

    function close() {
      if (panel.hidden) return;
      panel.hidden = true;
      document.removeEventListener("mousedown", onDocMouseDown, true);
    }

    function onDocMouseDown(e) {
      if (!wrap.contains(e.target)) close();
    }

    trigger.addEventListener("click", () => (panel.hidden ? open() : close()));
    input.addEventListener("focus", open);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !panel.hidden) { e.preventDefault(); close(); }
    });

    panel.addEventListener("click", (e) => {
      const day = e.target.closest(".date-day");
      if (day) { setValue(day.dataset.iso); close(); return; }
      const nav = e.target.closest(".date-nav");
      if (nav) {
        viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() + Number(nav.dataset.dir), 1);
        render();
        return;
      }
      if (e.target.closest(".date-today")) { setValue(toISO(new Date())); close(); }
    });
  }

  function enhanceAll(root) {
    (root || document).querySelectorAll('input[type="date"]:not([data-enhanced])').forEach(enhanceDate);
  }

  document.addEventListener("DOMContentLoaded", () => enhanceAll());
  window.LibroDatePicker = { enhance: enhanceDate, enhanceAll };
})();
