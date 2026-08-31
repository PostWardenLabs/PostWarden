import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'

// Purely static prose, no backend calls at all. Every cross-reference
// that points at another screen (`/staging`, `/entries?new=1`,
// `/budget`, `/scenarios`, ...) is a real `<Link>` into that screen's
// own `/app/*` route; `/entries/export.csv` stays a plain `<a href>` for
// the same reason Connect BI's `.pbids` link and the plain Import
// screen's own CSV export links do — a real file download, not a
// client-fetched route. The in-page jump-nav anchors (`#journal`,
// `#scheduled`, ...) are plain `<a href="#...">`, no scroll-spy/`active`
// state.
//
// `ImportPage.tsx`'s own help icon links to
// `/app/help#import`, which needs a manual scroll on mount, since React
// Router doesn't scroll to a URL's hash on its own (no data
// router/`<ScrollRestoration>` in this app). First and only place this
// app needs that, so it's a plain local `useEffect` here rather than a
// shared hook with one caller.
export default function HelpPage() {
  const location = useLocation()

  useEffect(() => {
    if (!location.hash) return
    const el = document.getElementById(location.hash.slice(1))
    el?.scrollIntoView()
    // Mount-only, matching a real browser's own one-time jump-to-anchor
    // on page load — not meant to re-fire on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <>
      <p className="page-sub">
        How each screen works, in one place — so the screens themselves can stay short. For the reasoning behind
        the app&apos;s design (why double-entry, why scenarios work the way they do), see the{' '}
        <a href="https://github.com/PostWardenLabs/PostWarden" target="_blank" rel="noopener">README and SPEC</a>{' '}
        in the repo.
      </p>

      <div className="two-col">
        <nav className="side-nav">
          <a href="#journal">Journal</a>
          <a href="#scheduled">Scheduled Entries</a>
          <a href="#staging">Staging</a>
          <a href="#import">Import</a>
          <a href="#templates">Templates</a>
          <a href="#budget-grid">Budget grid</a>
          <a href="#reports">Reports &amp; simulated close</a>
          <a href="#variance">Variance</a>
          <a href="#scenarios">Scenarios</a>
          <a href="#accounts">Accounts &amp; levels</a>
          <a href="#payees">Payees</a>
          <a href="#tags">Tags</a>
        </nav>

        <div className="two-col-main">
          <h2 id="journal">Journal</h2>
          <p>
            Every posted entry, most recent first, 50 at a time. History here is append-only: fix a mistake with{' '}
            <strong>Reverse</strong>, never by editing a posted line — the database refuses edits and deletes
            outright, so this isn&apos;t just a convention. <strong>Select entries</strong> reveals a checkbox
            per entry (same mechanism as <Link to="/app/staging">Staging</Link>&apos;s own bulk actions) — check
            one or many and <strong>Reverse</strong> (or Alt+R) posts a reversal for each, after confirming;
            nothing about the original entry changes, this just adds an offsetting one. <strong>Edit tags</strong>{' '}
            opens a pill box for whatever&apos;s checked — adding a tag there adds it to every checked entry that
            doesn&apos;t already have it, removing one drops it from every checked entry that does, applied the
            moment you add or remove it rather than behind a separate save step. This one&apos;s deliberately not
            append-only the way the entry itself is: organizing old entries with a tag you only just thought of
            doesn&apos;t change what happened, just how you find it later, so it&apos;s fair game on a posted
            entry the same as a pending one — unlike the amounts and accounts an entry actually posted. For the
            same reason, expanding a posted entry shows an editable <strong>Description</strong> field — fixing a
            typo doesn&apos;t change what happened either, so it&apos;s not stuck there forever the way an amount
            or account is. <strong>+ New entry</strong> (or Alt+E, which toggles it open/closed) opens a
            keyboard-first form right on this page: Tab flows account → debit/credit → memo across a line,
            Enter/Shift+Enter move straight down/up the column you&apos;re already in, Alt+N adds a blank line
            (one also appears on its own once the last one is in use), <strong>Distribute</strong> (Alt+D) fills
            in whatever amount would balance the entry on whichever line has focus — or, from the first line,
            adds a new one and fills that instead, since distributing into the first line itself would just
            cancel out the amount you&apos;re there to enter — and Alt+S posts it (same shortcut for Save
            template/Save schedule/Save changes wherever this form shows up instead). <strong>Clear</strong>{' '}
            (Alt+C) resets the whole form back to how it looked on page load. Alt shortcuts use the physical key,
            so they work the same on a Mac even though Option+letter would otherwise type an accented character.
            Filters (scenario, dates, account, payee, amount — including an &quot;and&quot; between two bounds,
            tags, search) narrow the list and the CSV export alike. A dropdown, a date, a checkbox, or
            adding/removing a tag refreshes the list the moment it changes; Search and Amount are free-typed
            text, so those need Enter (or the magnifying glass right on the Search box) to apply — refreshing on
            every keystroke there would just be noise. <strong>Clear filters</strong> resets all of it in one
            click, and stays grayed out when there&apos;s nothing to clear. <strong>Hide reversed/reversals</strong>{' '}
            is its own checkbox for a related reason — a mistake you fixed with Reverse, and the reversal itself,
            both disappear together so a quick look through the ledger isn&apos;t cluttered with corrections you
            already made.
          </p>

          <h2 id="scheduled">Scheduled Entries</h2>
          <p>
            Recurring postings — rent, wages, subscriptions. Each occurrence lands in{' '}
            <Link to="/app/staging">Staging</Link> on its due date automatically; nothing touches your real books
            until you approve it from there. A schedule itself is just a template plus a repeat rule (every N
            days/weeks/months) and the scenario its occurrences should eventually land in once approved.
          </p>

          <h2 id="staging">Staging</h2>
          <p>
            A holding pen, not a scenario you ever post to directly — every entry here arrived from a schedule or
            a CSV import, never typed in by hand (the database enforces that, too). Check the ones you want, hit{' '}
            <strong>Approve</strong> (or Alt+A), and each one becomes a real, independent posting in its target
            scenario. Once approved, the staged copy itself is never deleted or edited again, just marked
            approved, so nothing can be approved twice.
          </p>
          <p>
            Before you approve one, though, it&apos;s still a draft — a schedule or an import proposed it,
            nobody&apos;s committed to it yet. <strong>Edit</strong> opens the same kind of grid{' '}
            <Link to="/app/entries?new=1">New entry</Link> uses, prefilled with whatever&apos;s there: fix an
            amount, change which account a line hit, add a line, drop one, correct a typo in the memo, all before
            it ever becomes a real posting. <strong>Reject</strong> (or Alt+R) deletes whatever&apos;s checked
            outright — for something that shouldn&apos;t have been proposed at all, not something to Approve and
            then immediately Reverse — the same checkboxes Approve uses, one entry checked or many. Both Approve
            and Reject stop being available the moment an entry is approved: from then on it&apos;s a real
            posting, and posted entries are never edited or deleted, only reversed.
          </p>
          <p>
            The filter bar above the list is the same fields the <Link to="/app/entries">Journal</Link>&apos;s
            own filter bar has — Scenario here means where each entry is <em>headed</em> once approved, since
            every row already shares the one real scenario, Staging itself. Useful for working through a big CSV
            import a scenario or a date range at a time instead of one long undifferentiated list.
          </p>

          <h2 id="import">Import</h2>
          <p>
            Brings entries in from a CSV — upload a file, then a wizard walks through matching it to a journal
            entry before anything lands anywhere. Imported entries always land in{' '}
            <Link to="/app/staging">Staging</Link> for review, exactly like a scheduled entry, targeting whichever
            scenario you pick on the upload form.
          </p>
          <p>
            After upload, pick the file&apos;s <strong>shape</strong>: whether each row is its own entry, or
            several rows sharing a group-key column (like <span className="mono">Entry #</span>) each combine
            into one; and whether the amount is one signed column or a separate Debit/Credit pair. The same
            column layout <a href="/entries/export.csv">Export CSV</a> produces — grouped rows, Debit/Credit,
            real account codes already in the file — is one shape among several, not a separate importer, so
            export → edit in a spreadsheet → re-import is still a real round trip. Below the shape, map each of
            the file&apos;s own columns onto a target field (date, description, account, amount, ...); an{' '}
            <span className="mono">Account</span> or <span className="mono">Category</span> column can be
            flagged as already holding real codes, or as labels (like a bank&apos;s own free-text category)
            that need mapping to a real account next.
          </p>
          <p>
            The review step lists the distinct values found in any label-mapped column and asks which account
            each one becomes — skipped entirely for a file that&apos;s all real codes already. Submitting from
            there checks every row before committing anything: a clean file stages immediately, but a file with
            row errors (an unbalanced group, an unmapped label, an unknown account code) shows a validation
            report instead, listing what failed and what would stage fine. From there, fix the mapping and
            re-check, or stage the rest and explicitly skip the bad rows — nothing partially stages without
            that choice.
          </p>

          <h2 id="templates">Templates</h2>
          <p>
            Reusable scaffolding for entries you post often. Save one here, then pick it from the &quot;Load
            template&quot; list on the <Link to="/app/entries?new=1">Journal&apos;s + New entry</Link> panel to
            fill the whole form in one click. A template isn&apos;t a posting and isn&apos;t tracked once
            loaded — it just fills in fields, the same as if you&apos;d typed them by hand.
          </p>

          <h2 id="budget-grid">Budget grid</h2>
          <p>
            Income/expense targets, one month at a time — no journal entries, no date, no counter-account, just
            how much. Budgeted is editable (type a number, tab to the next cell); Actual is what really posted to
            ACTUAL that month, and Variance is the difference. This only works for a scenario created as
            &quot;income statement only&quot; — see Scenarios below. <strong>Flip variance direction</strong>{' '}
            (also on Income Statement and Variance, wherever a % variance column shows up) swaps which figure the
            percentage is read against — default measures against the budgeted/compare figure (&quot;actual came
            in 12% ahead of budget&quot;), checked measures against the actual/baseline figure instead
            (&quot;budget came in 12% ahead of actual&quot;) — the dollar Variance column flips sign to match.
          </p>

          <h2 id="reports">Reports &amp; the simulated monthly close</h2>
          <p>
            Trial Balance and Balance Sheet default to a <strong>simulated close</strong>: Income/Expense
            activity shows only the current period (month-to-date on Trial Balance; fiscal-year-to-date on
            Balance Sheet, since a balance sheet has no Income Statement section to hold the rest), with
            everything before that folded into synthetic &quot;Current/Prior Year Earnings (Unclosed)&quot; lines
            under Equity — as if a real monthly close had run. It hasn&apos;t: no entries are ever posted for
            this, it&apos;s computed fresh on every page load. Check <strong>show true balances</strong> on
            either report to see the real, unmodified cumulative numbers instead. Income Statement is different
            from both — it&apos;s always a date <em>range</em> you pick, never a running balance since inception.
          </p>
          <p>
            Income Statement&apos;s <strong>Split</strong> dropdown (Monthly/Quarterly/Yearly) turns that one
            range into a column per period — pick &quot;This year&quot; and split Monthly to see all 12 months
            side by side instead of running the report 12 times. A period that doesn&apos;t line up to a whole
            calendar month/quarter/year at either edge of a custom range only totals what&apos;s actually inside
            it — marked with a <sup>*</sup> and explained in a footnote below the table — never expanding outward
            to a full calendar period you didn&apos;t ask for. Two columns always follow the real periods:{' '}
            <strong>Total</strong> (the whole range&apos;s own figures, labeled to match whatever the Period
            dropdown reads — &quot;This Quarter&quot;, &quot;Custom range&quot;, ...) and{' '}
            <strong>Average</strong> (Total divided by the number of periods shown). Both are bold with a tinted
            background so they read as aggregates rather than another real period at a glance; Average is also
            italic, to tell the two apart from each other.
          </p>

          <h2 id="variance">Variance</h2>
          <p>
            Compares two scenarios side by side, rolled up to a common level so a scenario entered straight
            against a summary account like &quot;Bank&quot; still lines up against a finer one that split
            Checking/Savings, instead of just not matching up at all.
          </p>

          <h2 id="scenarios">Scenarios</h2>
          <p>
            The OneStream idea, in a ledger: ACTUAL and any full scenario (a forecast or what-if actually
            modeling dated transactions, like &quot;what if I buy a house&quot;) are journal entries tagged with
            a scenario, and Variance is just a query across them. An <strong>income statement only</strong>{' '}
            scenario skips the ledger entirely — no dates, no counter-accounts, just income/expense amounts
            edited from the <Link to="/app/budget">Budget grid</Link>. <span className="mono">STAGING</span> is
            neither of these to configure yourself — it&apos;s a fixed holding pen only Scheduled Entries and
            Import can write to (see Staging above).
          </p>

          <p>
            The <Link to="/app/scenarios">New scenario</Link> form has two independent checkboxes —{' '}
            <strong>income statement only</strong> and <strong>require balanced entries</strong> — which looks
            like four possible combinations. In practice it&apos;s three: once a scenario is income statement
            only, it never takes a journal entry at all (the database refuses one regardless of what asks), so
            &quot;require balanced entries&quot; has nothing left to apply to and the checkbox itself hides on
            the form the moment you check the first one. Both are set once, at creation, and there&apos;s no edit
            screen for either afterward — the only thing you can ever change about an existing scenario is{' '}
            <strong>Lock</strong>/<strong>Unlock</strong> (blocks new entries or budget lines without touching
            what&apos;s already posted) on the <Link to="/app/scenarios">Scenarios</Link> list itself. Pick
            carefully; &quot;change my mind later&quot; means creating a new scenario, not editing this one.
          </p>

          <table className="ledger">
            <thead>
              <tr>
                <th>Income statement only</th><th>Require balanced entries</th><th>What you get</th>
                <th>Add numbers from</th><th>Use it for</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="mono dim">off</td><td className="mono dim">on</td>
                <td>A full scenario where every entry must net to zero, same rule ACTUAL always follows.</td>
                <td><Link to="/app/entries">Journal</Link></td>
                <td>
                  ACTUAL itself; STAGING; a <em>fully articulated</em> forecast or what-if you want to double as
                  a real projected balance sheet, not just an income statement — &quot;what if I buy a
                  house&quot; done properly credits Checking when it debits the mortgage, so a cash-flow
                  projection falls out of it for free.
                </td>
              </tr>
              <tr>
                <td className="mono dim">off</td><td className="mono dim">off</td>
                <td>
                  A full scenario that still posts to the Journal, but a single-sided line with no
                  counter-account is allowed to sit there unbalanced.
                </td>
                <td><Link to="/app/entries">Journal</Link></td>
                <td>
                  Rare on purpose. A loose, quick planning line (&quot;Groceries 6,000 in March,&quot; nothing on
                  the other side) when you don&apos;t want to invent a counter-account just to satisfy the
                  balance check. If what you actually want is a plain income/expense budget, the row below is
                  very likely the better fit — this one won&apos;t give you a matching balance sheet the way the
                  row above does, since a single-sided line never touches an asset or liability account.
                </td>
              </tr>
              <tr>
                <td className="mono dim">on</td><td className="mono dim">on</td>
                <td rowSpan={2}>
                  No journal entries, full stop — the database blocks every attempt regardless of which checkbox{' '}
                  <em>looks</em> set here. Numbers live one-per-(account, month) instead, with nothing to balance
                  by construction.
                </td>
                <td rowSpan={2}><Link to="/app/budget">Budget grid</Link></td>
                <td rowSpan={2}>
                  A plain income/expense budget: &quot;what do I plan to spend on Groceries this year.&quot; No
                  date beyond the month, no counter-account, freely editable in place (not append-only like a
                  posted entry) — it&apos;s a working assumption, not a transaction. This is what{' '}
                  <span className="mono">BUD2026</span> is.
                </td>
              </tr>
              <tr>
                <td className="mono dim">on</td><td className="mono dim">off</td>
              </tr>
            </tbody>
          </table>
          <p className="dim small">
            The last two rows are identical on purpose — the <span className="mono">enforce_balance</span>{' '}
            column always ends up holding some real value (the checkbox is hidden once income statement only is
            checked, not removed, so whatever state it was last in still gets saved), but nothing ever reads it
            for a scenario that doesn&apos;t post journal entries in the first place, so which value it happens
            to hold doesn&apos;t change anything observable.
          </p>

          <h2 id="accounts">Accounts &amp; levels</h2>
          <p>
            Summary accounts structure the chart; only postable leaves ever take a journal line. A child always
            inherits its parent&apos;s type (an Expense account can&apos;t have an Asset child) — the database
            enforces that, not just the form. <strong>Levels</strong> are just names for a depth in that
            hierarchy (depth 1 = every account&apos;s root, depth 2 their children, and so on) — purely labels
            over the same tree, useful mainly for picking a scenario&apos;s &quot;base level&quot; so it can post
            to a whole branch like &quot;Bank&quot; instead of every leaf underneath it.
          </p>

          <h2 id="payees">Payees</h2>
          <p>
            <strong>Edit</strong> renames a payee in place — click it, type the new name, press Enter.{' '}
            <strong>Archive</strong>/<strong>Unarchive</strong> only hides a payee from the New entry/Scheduled/
            Staging pickers going forward; entries that already used it are untouched either way, and its entry
            count is a link straight through to them. <strong>Delete</strong> is the one that actually removes
            the row — entries that used it just lose the payee label, they aren&apos;t deleted.{' '}
            <strong>Select</strong> reveals checkboxes for <strong>Merge</strong>, which folds two or more
            payees into one you name (defaulting to the first one picked) and repoints every entry, scheduled
            entry, and template that used any of them.
          </p>

          <h2 id="tags">Tags</h2>
          <p>
            Same Edit/Archive/Unarchive/Delete/Select+Merge as Payees, for tags instead — a tag can be assigned
            to more than one entry at once (unlike a payee, which is one per entry), created either here or
            inline while tagging an entry (typing an archived tag&apos;s name while tagging something quietly
            unarchives it, same as a payee typed into New entry&apos;s own combobox). Merging here folds every
            tag&apos;s entries onto the surviving name, without duplicating a tag an entry already carries.
          </p>
        </div>
      </div>
    </>
  )
}
