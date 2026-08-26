/* PostWarden — calendar date picker, progressively enhancing a plain
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
    // Roving tabindex: exactly one day button is ever a real Tab stop
    // (the rest get tabIndex -1, still focusable via .focus() for arrow-
    // key navigation, just not by Tab) — without this, Tab had to walk
    // through all 28-31 day buttons plus month-nav and Today one at a
    // time before it could ever leave the calendar. Persists across
    // renders so tabbing away and back doesn't reset to the 1st.
    let rovingDate = null;

    function daysInMonthOf(d) { return new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate(); }

    // Clamped, not wrapped — Jan 31 + 1 month lands on Feb 28/29, not
    // rolling over into March the way `new Date(y, m+1, d)` would for a
    // day number the target month doesn't have.
    function addMonths(d, n) {
      const target = new Date(d.getFullYear(), d.getMonth() + n, 1);
      target.setDate(Math.min(d.getDate(), daysInMonthOf(target)));
      return target;
    }

    function render() {
      const year = viewDate.getFullYear();
      const month = viewDate.getMonth();
      const first = new Date(year, month, 1);
      const startOffset = (first.getDay() + 6) % 7; // Monday-first week
      const daysInMonth = daysInMonthOf(viewDate);
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
      // Roving tabindex target, in priority order: wherever arrow-key nav
      // last left it, else the selected date, else today — falling back
      // to day 1 only if none of those land in the month actually being
      // shown (e.g. paged away with nothing selected).
      const tabTargetIso = (rovingDate && toISO(rovingDate))
        || (selected && toISO(selected)) || todayISO;
      let tabTargetSet = false;
      for (let day = 1; day <= daysInMonth; day++) {
        const iso = `${year}-${pad2(month + 1)}-${pad2(day)}`;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "date-day";
        if (selected && iso === toISO(selected)) btn.classList.add("selected");
        if (iso === todayISO) btn.classList.add("today");
        btn.textContent = String(day);
        btn.dataset.iso = iso;
        if (iso === tabTargetIso) { btn.tabIndex = 0; tabTargetSet = true; }
        else btn.tabIndex = -1;
        grid.appendChild(btn);
      }
      if (!tabTargetSet) {
        const first = grid.querySelector(".date-day");
        if (first) first.tabIndex = 0;
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

    // Moves the grid's own keyboard focus to a specific day, switching
    // month (and re-rendering) first if that day isn't in the one
    // currently shown. render() rebuilds every .date-day button from
    // scratch each time, so the actual DOM node has to be re-queried
    // after — there's no button to just .focus() before that.
    function focusDay(d) {
      rovingDate = d;
      viewDate = new Date(d.getFullYear(), d.getMonth(), 1);
      render();
      const btn = panel.querySelector(`.date-day[data-iso="${toISO(d)}"]`);
      if (btn) btn.focus();
    }

    function open(moveFocusToGrid) {
      viewDate = parseISO(input.value) || viewDate;
      render();
      if (panel.hidden) {
        panel.hidden = false;
        document.addEventListener("mousedown", onDocMouseDown, true);
      }
      // Only when the trigger button (or a keyboard activation of it) asked
      // for the calendar explicitly — typing into the input also opens the
      // panel (as a live preview), and grabbing focus away mid-keystroke
      // would make typing a date directly impossible, which this widget
      // explicitly still needs to support (see the file's own top comment).
      if (moveFocusToGrid) focusDay(parseISO(input.value) || new Date());
    }

    // Set right before an internal input.focus() call that shouldn't
    // reopen the panel — Escape (below) closes it and returns focus to
    // the input, but the input's own "focus" listener is what opens the
    // panel in the first place, so without this that same .focus() call
    // would immediately reopen the panel it was just asked to close.
    let suppressOpenOnFocus = false;

    function close(returnFocus) {
      if (panel.hidden) return;
      panel.hidden = true;
      document.removeEventListener("mousedown", onDocMouseDown, true);
      if (returnFocus) {
        suppressOpenOnFocus = true;
        input.focus();
      }
    }

    function onDocMouseDown(e) {
      if (!wrap.contains(e.target)) close();
    }

    // Closes on Tab (or Shift+Tab) out of the whole widget. Without this
    // the panel had no keyboard-driven way to close at all — the existing
    // outside-click listener only ever fired on a mousedown, never on
    // tabbing away. Deliberately checks document.activeElement a tick
    // later rather than trusting focusout's own e.relatedTarget: arrow-key
    // navigation (below) re-renders the grid and refocuses the new day,
    // which means destroying the *old* focused button mid-render — that
    // fires this same focusout with relatedTarget briefly null (nothing
    // has focus for an instant, between the old button's removal and the
    // new one's .focus() call a few lines later), which read as "focus
    // left the widget" and closed the panel out from under its own
    // keyboard navigation. By the time the deferred check below runs,
    // that same-task refocus has already landed.
    wrap.addEventListener("focusout", () => {
      setTimeout(() => {
        if (!wrap.contains(document.activeElement)) close();
      }, 0);
    });

    trigger.addEventListener("click", () => (panel.hidden ? open(true) : close()));
    input.addEventListener("focus", () => {
      if (suppressOpenOnFocus) { suppressOpenOnFocus = false; return; }
      open(false);
    });
    // On wrap, not just input — Escape has to work from a day button too
    // (arrow-key navigation lands focus there, not back on the input),
    // and this is the one listener that covers both.
    wrap.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !panel.hidden) { e.preventDefault(); close(true); }
    });

    panel.addEventListener("click", (e) => {
      const day = e.target.closest(".date-day");
      if (day) { setValue(day.dataset.iso); close(true); return; }
      const nav = e.target.closest(".date-nav");
      if (nav) {
        viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() + Number(nav.dataset.dir), 1);
        render();
        return;
      }
      if (e.target.closest(".date-today")) { setValue(toISO(new Date())); close(true); }
    });

    // Arrow-key/Page/Home/End navigation once focus is actually on a day
    // cell — Tab already reaches every button in the panel one at a time,
    // but there was no faster way to move around the grid itself, and no
    // way to change month without reaching for the mouse.
    panel.addEventListener("keydown", (e) => {
      const day = e.target.closest(".date-day");
      if (!day) return;
      const current = parseISO(day.dataset.iso);
      const deltas = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
      if (e.key in deltas) {
        e.preventDefault();
        const next = new Date(current);
        next.setDate(next.getDate() + deltas[e.key]);
        focusDay(next);
      } else if (e.key === "PageUp" || e.key === "PageDown") {
        e.preventDefault();
        focusDay(addMonths(current, e.key === "PageUp" ? -1 : 1));
      } else if (e.key === "Home") {
        e.preventDefault();
        focusDay(new Date(current.getFullYear(), current.getMonth(), 1));
      } else if (e.key === "End") {
        e.preventDefault();
        focusDay(new Date(current.getFullYear(), current.getMonth(), daysInMonthOf(current)));
      }
      // Enter/Space need no handler here — they're native <button>
      // activation, which already fires the click listener above.
    });
  }

  function enhanceAll(root) {
    (root || document).querySelectorAll('input[type="date"]:not([data-enhanced])').forEach(enhanceDate);
  }

  document.addEventListener("DOMContentLoaded", () => enhanceAll());
  window.PostWardenDatePicker = { enhance: enhanceDate, enhanceAll };
})();
