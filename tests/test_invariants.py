"""Exercises the invariants SPEC.md claims the database enforces.

Each test hits Postgres directly (see conftest.py) so there is no code
path — app, psql, or otherwise — that can route around what's asserted
here.
"""
import psycopg
import pytest

from conftest import (BI_URL, expect_error, mk_account, mk_budget_line,
                     mk_entry, mk_line, mk_scenario)


# ---------------------------------------------------------------------------
# The balance invariant (deferred constraint trigger)
# ---------------------------------------------------------------------------
def test_balanced_entry_commits(conn, actual_scenario_id):
    with conn.cursor() as cur:
        a1 = mk_account(cur)
        a2 = mk_account(cur)
        eid = mk_entry(cur, actual_scenario_id)
        mk_line(cur, eid, a1["id"], 100, line_no=1)
        mk_line(cur, eid, a2["id"], -100, line_no=2)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT SUM(amount) AS s FROM journal_lines WHERE entry_id = %s",
                    (eid,))
        assert cur.fetchone()["s"] == 0


def test_unbalanced_entry_rejected_at_commit(conn, actual_scenario_id):
    with expect_error(conn, match="not balanced"):
        with conn.cursor() as cur:
            a1 = mk_account(cur)
            a2 = mk_account(cur)
            eid = mk_entry(cur, actual_scenario_id)
            mk_line(cur, eid, a1["id"], 100, line_no=1)
            mk_line(cur, eid, a2["id"], -40, line_no=2)
        conn.commit()


def test_entry_with_no_lines_rejected(conn, actual_scenario_id):
    with expect_error(conn, match="no lines"):
        with conn.cursor() as cur:
            mk_entry(cur, actual_scenario_id)
        conn.commit()


def test_non_enforcing_scenario_allows_single_sided_entry(conn):
    with conn.cursor() as cur:
        scen = mk_scenario(cur, enforce_balance=False)
        acct = mk_account(cur, account_type="expense")
        eid = mk_entry(cur, scen["id"])
        mk_line(cur, eid, acct["id"], 6000)
    conn.commit()  # must not raise

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM journal_lines WHERE entry_id = %s",
                    (eid,))
        assert cur.fetchone()["n"] == 1


def test_actual_scenario_must_enforce_balance(conn):
    with expect_error(conn):
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO scenarios (code, name, scenario_type, enforce_balance)
                   VALUES ('TACTUAL2', 'bad actual', 'actual', FALSE)""")


def test_actual_scenario_cannot_be_income_statement_only(conn):
    with expect_error(conn):
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO scenarios
                       (code, name, scenario_type, income_statement_only)
                   VALUES ('TACTUAL3', 'bad actual', 'actual', TRUE)""")


# ---------------------------------------------------------------------------
# Scenario locking
# ---------------------------------------------------------------------------
def test_locked_scenario_rejects_new_entries(conn):
    with expect_error(conn, match="locked"):
        with conn.cursor() as cur:
            scen = mk_scenario(cur, is_locked=True)
            mk_entry(cur, scen["id"])


# ---------------------------------------------------------------------------
# Income-statement-only scenarios — no journal entries, ever; only
# budget_lines, and only for a postable income/expense account.
# ---------------------------------------------------------------------------
def test_income_statement_only_scenario_rejects_journal_entry(conn):
    with expect_error(conn, match="income-statement-only"):
        with conn.cursor() as cur:
            scen = mk_scenario(cur, income_statement_only=True)
            mk_entry(cur, scen["id"])


def test_budget_line_commits_for_income_expense_leaf(conn):
    with conn.cursor() as cur:
        scen = mk_scenario(cur, income_statement_only=True)
        acct = mk_account(cur, account_type="expense")
        mk_budget_line(cur, scen["id"], acct["id"], 600)
    conn.commit()  # must not raise

    with conn.cursor() as cur:
        cur.execute("SELECT amount FROM budget_lines WHERE scenario_id = %s", (scen["id"],))
        assert cur.fetchone()["amount"] == 600


def test_budget_line_rejected_for_full_scenario(conn, actual_scenario_id):
    with expect_error(conn, match="not income-statement-only"):
        with conn.cursor() as cur:
            acct = mk_account(cur, account_type="expense")
            mk_budget_line(cur, actual_scenario_id, acct["id"], 600)


def test_budget_line_rejected_on_asset_account(conn):
    with expect_error(conn, match="not an income or expense account"):
        with conn.cursor() as cur:
            scen = mk_scenario(cur, income_statement_only=True)
            acct = mk_account(cur, account_type="asset")
            mk_budget_line(cur, scen["id"], acct["id"], 600)


def test_budget_line_rejected_on_summary_account(conn):
    with expect_error(conn, match="summary account"):
        with conn.cursor() as cur:
            scen = mk_scenario(cur, income_statement_only=True)
            summary = mk_account(cur, account_type="expense", postable=False)
            mk_budget_line(cur, scen["id"], summary["id"], 600)


def test_budget_line_rejected_when_scenario_locked(conn):
    with expect_error(conn, match="locked"):
        with conn.cursor() as cur:
            scen = mk_scenario(cur, income_statement_only=True, is_locked=True)
            acct = mk_account(cur, account_type="expense")
            mk_budget_line(cur, scen["id"], acct["id"], 600)


# ---------------------------------------------------------------------------
# Staging — a holding pen only an automated producer may write to; at most
# one such scenario ever exists.
# ---------------------------------------------------------------------------
def test_staging_scenario_rejects_manual_entry(conn):
    # seed.sql already seeds the one real Staging scenario — use it rather
    # than making a second (uq_one_staging_scenario forbids that anyway;
    # see test_only_one_staging_scenario_allowed below).
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM scenarios WHERE is_staging")
        staging_id = cur.fetchone()["id"]
    with expect_error(conn, match="never a manual posting"):
        with conn.cursor() as cur:
            mk_entry(cur, staging_id)


def test_staging_scenario_allows_a_scheduled_entry(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM scenarios WHERE is_staging")
        staging_id = cur.fetchone()["id"]
        target = mk_scenario(cur)
        acct1 = mk_account(cur)
        acct2 = mk_account(cur)
        cur.execute(
            """INSERT INTO scheduled_entries
                   (description, target_scenario_id, interval_unit, next_date)
               VALUES ('Test schedule', %s, 'month', CURRENT_DATE) RETURNING id""",
            (target["id"],))
        sched_id = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO journal_entries (scenario_id, entry_date, description, scheduled_entry_id)
               VALUES (%s, CURRENT_DATE, 'Materialized occurrence', %s) RETURNING id""",
            (staging_id, sched_id))
        eid = cur.fetchone()["id"]
        mk_line(cur, eid, acct1["id"], 25, line_no=1)
        mk_line(cur, eid, acct2["id"], -25, line_no=2)
    conn.commit()  # must not raise


def test_staging_scenario_allows_an_import_batch_entry(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM scenarios WHERE is_staging")
        staging_id = cur.fetchone()["id"]
        target = mk_scenario(cur)
        acct1 = mk_account(cur)
        acct2 = mk_account(cur)
        cur.execute(
            """INSERT INTO import_batches (filename, target_scenario_id, row_count)
               VALUES ('test.csv', %s, 1) RETURNING id""",
            (target["id"],))
        batch_id = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO journal_entries (scenario_id, entry_date, description, import_batch_id)
               VALUES (%s, CURRENT_DATE, 'Imported row', %s) RETURNING id""",
            (staging_id, batch_id))
        eid = cur.fetchone()["id"]
        mk_line(cur, eid, acct1["id"], 15, line_no=1)
        mk_line(cur, eid, acct2["id"], -15, line_no=2)
    conn.commit()  # must not raise


def test_only_one_staging_scenario_allowed(conn):
    # seed.sql already seeded the real one — a second is rejected outright.
    with expect_error(conn):
        with conn.cursor() as cur:
            mk_scenario(cur, is_staging=True)


def test_staging_scenario_cannot_be_income_statement_only(conn):
    with expect_error(conn):
        with conn.cursor() as cur:
            mk_scenario(cur, is_staging=True, income_statement_only=True)


def _mk_pending_staging_entry(cur, description="Pending entry"):
    """A balanced, still-unapproved Staging entry — scheduled_entry_id
    set (same shape materialize_due_schedules() itself produces) so
    fn_staging_manual_entry_guard allows it, two lines so the deferred
    balance trigger is happy at commit."""
    cur.execute("SELECT id FROM scenarios WHERE is_staging")
    staging_id = cur.fetchone()["id"]
    target = mk_scenario(cur)
    acct1 = mk_account(cur)
    acct2 = mk_account(cur)
    cur.execute(
        """INSERT INTO scheduled_entries
               (description, target_scenario_id, interval_unit, next_date)
           VALUES ('Test schedule', %s, 'month', CURRENT_DATE) RETURNING id""",
        (target["id"],))
    sched_id = cur.fetchone()["id"]
    cur.execute(
        """INSERT INTO journal_entries (scenario_id, entry_date, description, scheduled_entry_id)
           VALUES (%s, CURRENT_DATE, %s, %s) RETURNING id""",
        (staging_id, description, sched_id))
    eid = cur.fetchone()["id"]
    mk_line(cur, eid, acct1["id"], 30, line_no=1)
    mk_line(cur, eid, acct2["id"], -30, line_no=2)
    return eid, target["id"]


def test_pending_staging_line_can_be_deleted(conn):
    # Delete-then-reinsert with a different amount — the shape the app's
    # own Staging edit route uses — rather than deleting down to zero
    # lines: that would (correctly) trip the separate "an entry needs at
    # least one line" invariant, which is unrelated to immutability and
    # isn't relaxed by any of this.
    with conn.cursor() as cur:
        eid, _ = _mk_pending_staging_entry(cur)
        cur.execute(
            "SELECT account_id FROM journal_lines WHERE entry_id = %s AND line_no = 1",
            (eid,))
        acct1_id = cur.fetchone()["account_id"]
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id FROM journal_lines WHERE entry_id = %s AND line_no = 2",
            (eid,))
        acct2_id = cur.fetchone()["account_id"]
        cur.execute("DELETE FROM journal_lines WHERE entry_id = %s", (eid,))
        mk_line(cur, eid, acct1_id, 45, line_no=1)   # replaces the deleted 30/-30 pair
        mk_line(cur, eid, acct2_id, -45, line_no=2)
    conn.commit()  # must not raise
    with conn.cursor() as cur:
        cur.execute(
            "SELECT amount FROM journal_lines WHERE entry_id = %s AND line_no = 1", (eid,))
        assert cur.fetchone()["amount"] == 45


def test_pending_staging_line_still_cannot_be_updated_in_place(conn):
    # The exception is delete-only — editing a line is delete-then-
    # reinsert (see app/main.py's staging edit route), never an in-place
    # UPDATE, even while still pending.
    with conn.cursor() as cur:
        eid, _ = _mk_pending_staging_entry(cur)
    conn.commit()
    with expect_error(conn):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE journal_lines SET amount = 99 WHERE entry_id = %s AND line_no = 1",
                (eid,))


def test_pending_staging_entry_header_is_editable(conn):
    with conn.cursor() as cur:
        eid, _ = _mk_pending_staging_entry(cur)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE journal_entries
                   SET description = 'Edited', entry_date = CURRENT_DATE - 1
                 WHERE id = %s""",
            (eid,))
    conn.commit()  # must not raise
    with conn.cursor() as cur:
        cur.execute("SELECT description FROM journal_entries WHERE id = %s", (eid,))
        assert cur.fetchone()["description"] == "Edited"


def test_pending_staging_entry_scenario_change_still_rejected(conn):
    # Editable, but not into a different scenario — that's what the
    # schedule/import's own target_scenario_id at approval time is for.
    with conn.cursor() as cur:
        eid, other_scenario_id = _mk_pending_staging_entry(cur)
    conn.commit()
    with expect_error(conn):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE journal_entries SET scenario_id = %s WHERE id = %s",
                (other_scenario_id, eid))


def test_pending_staging_entry_can_be_deleted(conn):
    with conn.cursor() as cur:
        eid, _ = _mk_pending_staging_entry(cur)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM journal_lines WHERE entry_id = %s", (eid,))
        cur.execute("DELETE FROM journal_entries WHERE id = %s", (eid,))
    conn.commit()  # must not raise
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM journal_entries WHERE id = %s", (eid,))
        assert cur.fetchone()["n"] == 0


def test_approving_a_staging_entry_sets_promoted_entry_id(conn, actual_scenario_id):
    # The one write the approve flow itself needs (see app/main.py) —
    # confirms the mutability exception doesn't accidentally block the
    # very transition it exists to allow.
    with conn.cursor() as cur:
        eid, _ = _mk_pending_staging_entry(cur)
        real_id = mk_entry(cur, actual_scenario_id, "Approved copy")
        real_acct1, real_acct2 = mk_account(cur), mk_account(cur)
        # ACTUAL always enforces balance — two lines, not one.
        mk_line(cur, real_id, real_acct1["id"], 30, line_no=1)
        mk_line(cur, real_id, real_acct2["id"], -30, line_no=2)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE journal_entries SET promoted_entry_id = %s WHERE id = %s",
            (real_id, eid))
    conn.commit()  # must not raise


def test_promoted_staging_entry_is_immutable_again(conn, actual_scenario_id):
    with conn.cursor() as cur:
        eid, _ = _mk_pending_staging_entry(cur)
        real_id = mk_entry(cur, actual_scenario_id, "Approved copy")
        real_acct1, real_acct2 = mk_account(cur), mk_account(cur)
        # ACTUAL always enforces balance — two lines, not one.
        mk_line(cur, real_id, real_acct1["id"], 30, line_no=1)
        mk_line(cur, real_id, real_acct2["id"], -30, line_no=2)
        cur.execute(
            "UPDATE journal_entries SET promoted_entry_id = %s WHERE id = %s",
            (real_id, eid))
    conn.commit()

    with expect_error(conn):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM journal_lines WHERE entry_id = %s AND line_no = 1", (eid,))

    with expect_error(conn):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM journal_entries WHERE id = %s", (eid,))


# ---------------------------------------------------------------------------
# Postable / active account guard
# ---------------------------------------------------------------------------
def test_line_rejected_on_summary_account(conn, actual_scenario_id):
    with expect_error(conn, match="summary account"):
        with conn.cursor() as cur:
            summary = mk_account(cur, postable=False)
            eid = mk_entry(cur, actual_scenario_id)
            mk_line(cur, eid, summary["id"], 10)


# ---------------------------------------------------------------------------
# Account levels — a scenario's base_level relaxes fn_line_account_guard
# for accounts sitting exactly at that depth, additively (see
# app/main.py's postable_accounts_for_pickers()/create_scenario). seed.sql
# already defines depths 1/2/3 ("Top Level Accounts"/"Subaccounts"/
# "Account Detail") and depth is UNIQUE, so these reuse those rather than
# insert colliding ones.
# ---------------------------------------------------------------------------
def test_line_allowed_on_summary_account_at_scenario_base_level(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM account_levels WHERE depth = 2")
        level2_id = cur.fetchone()["id"]
        parent = mk_account(cur, postable=False)             # depth 1
        child = mk_account(cur, parent_id=parent["id"], postable=False)  # depth 2
        scen = mk_scenario(cur, base_level_id=level2_id, enforce_balance=False)
        eid = mk_entry(cur, scen["id"])
        mk_line(cur, eid, child["id"], 10)
    conn.commit()  # would raise here if the trigger still rejected it

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM journal_lines WHERE entry_id = %s", (eid,))
        assert cur.fetchone() is not None


def test_line_rejected_on_summary_account_not_at_scenario_base_level(conn):
    with expect_error(conn, match="summary account"):
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM account_levels WHERE depth = 2")
            level2_id = cur.fetchone()["id"]
            root = mk_account(cur, postable=False)  # depth 1, not depth 2
            scen = mk_scenario(cur, base_level_id=level2_id, enforce_balance=False)
            eid = mk_entry(cur, scen["id"])
            mk_line(cur, eid, root["id"], 10)


def test_line_allowed_on_true_leaf_regardless_of_scenario_base_level(conn):
    # Additive only: a scenario's base_level never blocks a real leaf,
    # even one deeper than base_level.
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM account_levels WHERE depth = 2")
        level2_id = cur.fetchone()["id"]
        leaf = mk_account(cur, postable=True)  # depth 1, a true leaf
        scen = mk_scenario(cur, base_level_id=level2_id, enforce_balance=False)
        eid = mk_entry(cur, scen["id"])
        mk_line(cur, eid, leaf["id"], 10)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM journal_lines WHERE entry_id = %s", (eid,))
        assert cur.fetchone() is not None


def test_account_level_depth_must_be_unique(conn):
    with expect_error(conn):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO account_levels (name, depth) VALUES ('Dup', 2)")


def test_account_level_delete_rejected_while_scenario_uses_it(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM account_levels WHERE depth = 3")
        level3_id = cur.fetchone()["id"]
        mk_scenario(cur, base_level_id=level3_id)
    conn.commit()

    with expect_error(conn):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM account_levels WHERE id = %s", (level3_id,))


def test_trial_balance_shows_summary_account_with_direct_postings(conn):
    # fn_trial_balance used to filter to is_postable accounts only — a
    # posting legitimately made to a summary account (via a scenario's
    # base_level) would silently vanish from the report despite being
    # real data. Confirms it now shows up, and that an *untouched*
    # summary account still doesn't clutter the report.
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM account_levels WHERE depth = 2")
        level2_id = cur.fetchone()["id"]
        parent = mk_account(cur, postable=False)
        posted_summary = mk_account(cur, parent_id=parent["id"], postable=False)
        untouched_summary = mk_account(cur, parent_id=parent["id"], postable=False)
        scen = mk_scenario(cur, base_level_id=level2_id, enforce_balance=False)
        eid = mk_entry(cur, scen["id"])
        mk_line(cur, eid, posted_summary["id"], 250)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT account_code, debit_balance FROM fn_trial_balance(%s)",
                    (scen["code"],))
        rows = {r["account_code"]: r["debit_balance"] for r in cur.fetchall()}
        assert rows.get(posted_summary["code"]) == 250
        assert untouched_summary["code"] not in rows


def test_rollup_balance_sums_leaves_under_a_common_ancestor(conn):
    # The budget-vs-actual base: two leaves under the same parent roll up
    # into that parent's own row when a depth is requested, and a posting
    # already shallower than the requested depth stays at its own account
    # (there's nothing to push it deeper into) rather than disappearing.
    with conn.cursor() as cur:
        cur.execute("SELECT id, depth FROM account_levels WHERE depth = 2")
        level2 = cur.fetchone()
        parent = mk_account(cur, postable=False)          # depth 1
        leaf1 = mk_account(cur, parent_id=parent["id"])    # depth 2
        leaf2 = mk_account(cur, parent_id=parent["id"])    # depth 2
        scen = mk_scenario(cur, enforce_balance=False)
        eid = mk_entry(cur, scen["id"])
        mk_line(cur, eid, leaf1["id"], 30, line_no=1)
        mk_line(cur, eid, leaf2["id"], 70, line_no=2)
    conn.commit()

    with conn.cursor() as cur:
        # Rolled up to depth 2 (the leaves' own depth): each keeps its own row.
        cur.execute("SELECT account_code, net FROM fn_rollup_balance(%s, 2::smallint)", (scen["code"],))
        rows = {r["account_code"]: r["net"] for r in cur.fetchall()}
        assert rows[leaf1["code"]] == 30
        assert rows[leaf2["code"]] == 70

        # Rolled up to depth 1 (the parent): both leaves merge into it.
        cur.execute("SELECT account_code, net FROM fn_rollup_balance(%s, 1::smallint)", (scen["code"],))
        rows = {r["account_code"]: r["net"] for r in cur.fetchall()}
        assert rows[parent["code"]] == 100
        assert leaf1["code"] not in rows

        # No depth given: native depth, same as each leaf's own row.
        cur.execute("SELECT account_code, net FROM fn_rollup_balance(%s, NULL)", (scen["code"],))
        rows = {r["account_code"]: r["net"] for r in cur.fetchall()}
        assert rows[leaf1["code"]] == 30
        assert rows[leaf2["code"]] == 70


def test_line_rejected_on_inactive_account(conn, actual_scenario_id):
    with expect_error(conn, match="inactive"):
        with conn.cursor() as cur:
            acct = mk_account(cur, active=False)
            eid = mk_entry(cur, actual_scenario_id)
            mk_line(cur, eid, acct["id"], 10)


# ---------------------------------------------------------------------------
# Account hierarchy: typed parent/child, acyclic
# ---------------------------------------------------------------------------
def test_child_account_type_must_match_parent(conn):
    with expect_error(conn, match="must have the same type"):
        with conn.cursor() as cur:
            parent = mk_account(cur, account_type="asset")
            mk_account(cur, account_type="liability", parent_id=parent["id"])


def test_account_hierarchy_cycle_rejected(conn):
    with conn.cursor() as cur:
        a = mk_account(cur, account_type="asset")
        b = mk_account(cur, account_type="asset", parent_id=a["id"])
    conn.commit()

    with expect_error(conn, match="cycle"):
        with conn.cursor() as cur:
            cur.execute("UPDATE accounts SET parent_id = %s WHERE id = %s",
                        (b["id"], a["id"]))


# ---------------------------------------------------------------------------
# Immutability: lines and entries are append-only
# ---------------------------------------------------------------------------
def test_journal_line_update_rejected(conn, actual_scenario_id):
    with conn.cursor() as cur:
        acct1 = mk_account(cur)
        acct2 = mk_account(cur)
        eid = mk_entry(cur, actual_scenario_id)
        mk_line(cur, eid, acct1["id"], 50, line_no=1)
        mk_line(cur, eid, acct2["id"], -50, line_no=2)
    conn.commit()

    with expect_error(conn, match="immutable"):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE journal_lines SET amount = 999 WHERE entry_id = %s AND line_no = 1",
                (eid,))


def test_journal_line_delete_rejected(conn, actual_scenario_id):
    with conn.cursor() as cur:
        acct1 = mk_account(cur)
        acct2 = mk_account(cur)
        eid = mk_entry(cur, actual_scenario_id)
        mk_line(cur, eid, acct1["id"], 50, line_no=1)
        mk_line(cur, eid, acct2["id"], -50, line_no=2)
    conn.commit()

    with expect_error(conn, match="immutable"):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM journal_lines WHERE entry_id = %s AND line_no = 1",
                        (eid,))


def test_journal_entry_delete_rejected(conn, actual_scenario_id):
    with conn.cursor() as cur:
        eid = mk_entry(cur, actual_scenario_id)
        acct = mk_account(cur)
        mk_line(cur, eid, acct["id"], 1)
        mk_line(cur, eid, mk_account(cur)["id"], -1, line_no=2)
    conn.commit()

    with expect_error(conn, match="cannot be deleted"):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM journal_entries WHERE id = %s", (eid,))


def test_journal_entry_only_description_and_reference_editable(conn, actual_scenario_id):
    with conn.cursor() as cur:
        eid = mk_entry(cur, actual_scenario_id)
        acct1 = mk_account(cur)
        acct2 = mk_account(cur)
        mk_line(cur, eid, acct1["id"], 1, line_no=1)
        mk_line(cur, eid, acct2["id"], -1, line_no=2)
    conn.commit()

    with expect_error(conn, match="only description and reference"):
        with conn.cursor() as cur:
            cur.execute("UPDATE journal_entries SET entry_date = entry_date + 1 WHERE id = %s",
                        (eid,))

    with conn.cursor() as cur:
        cur.execute("UPDATE journal_entries SET description = 'edited' WHERE id = %s",
                    (eid,))
    conn.commit()  # must not raise

    with conn.cursor() as cur:
        cur.execute("SELECT description FROM journal_entries WHERE id = %s", (eid,))
        assert cur.fetchone()["description"] == "edited"


# ---------------------------------------------------------------------------
# Reversal integrity (added on top of the original schema)
# ---------------------------------------------------------------------------
def test_self_reversal_rejected(conn, actual_scenario_id):
    with expect_error(conn):
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO journal_entries
                       (id, scenario_id, entry_date, description, reverses_entry_id)
                   OVERRIDING SYSTEM VALUE
                   SELECT nextval(pg_get_serial_sequence('journal_entries', 'id')),
                          %s, CURRENT_DATE, 'self reversal', currval(
                              pg_get_serial_sequence('journal_entries', 'id'))""",
                (actual_scenario_id,))


def test_self_promotion_rejected(conn, actual_scenario_id):
    # Mirrors the reverses_entry_id self-check above — promoted_entry_id is
    # the same kind of "points at another journal_entries row" column (see
    # app/main.py's Scheduled entries "post" flow), so it gets the same
    # sanity guard.
    with expect_error(conn):
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO journal_entries
                       (id, scenario_id, entry_date, description, promoted_entry_id)
                   OVERRIDING SYSTEM VALUE
                   SELECT nextval(pg_get_serial_sequence('journal_entries', 'id')),
                          %s, CURRENT_DATE, 'self promotion', currval(
                              pg_get_serial_sequence('journal_entries', 'id'))""",
                (actual_scenario_id,))


# ---------------------------------------------------------------------------
# Scheduled entries — the template + recurrence rule a schedule materializes
# from (see app/main.py's materialize_due_schedules()/create_schedule).
# ---------------------------------------------------------------------------
def test_scheduled_entry_line_amount_cannot_be_zero(conn):
    with expect_error(conn):
        with conn.cursor() as cur:
            acct = mk_account(cur)
            scen = mk_scenario(cur, scenario_type="actual")
            cur.execute(
                """INSERT INTO scheduled_entries
                       (description, target_scenario_id, interval_unit, next_date)
                   VALUES ('Test schedule', %s, 'month', CURRENT_DATE) RETURNING id""",
                (scen["id"],))
            sid = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO scheduled_entry_lines
                       (scheduled_entry_id, line_no, account_id, amount)
                   VALUES (%s, 1, %s, 0)""",
                (sid, acct["id"]))


def test_scheduled_entry_interval_unit_must_be_recognized(conn):
    with expect_error(conn):
        with conn.cursor() as cur:
            scen = mk_scenario(cur, scenario_type="actual")
            cur.execute(
                """INSERT INTO scheduled_entries
                       (description, target_scenario_id, interval_unit, next_date)
                   VALUES ('Test schedule', %s, 'fortnight', CURRENT_DATE)""",
                (scen["id"],))


# ---------------------------------------------------------------------------
# Entry templates — reusable scaffolding for New entry's "Load template"
# (see app/main.py's create_template/templates_full()).
# ---------------------------------------------------------------------------
def test_entry_template_line_amount_cannot_be_zero(conn):
    with expect_error(conn):
        with conn.cursor() as cur:
            acct = mk_account(cur)
            cur.execute(
                """INSERT INTO entry_templates (name, description)
                   VALUES ('Test template', 'Test') RETURNING id""")
            tid = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO entry_template_lines
                       (template_id, line_no, account_id, amount)
                   VALUES (%s, 1, %s, 0)""",
                (tid, acct["id"]))


def test_entry_template_name_must_be_unique(conn):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO entry_templates (name, description) VALUES ('Dup', 'a')")
    conn.commit()
    with expect_error(conn):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO entry_templates (name, description) VALUES ('Dup', 'b')")


def test_double_reversal_rejected(conn, actual_scenario_id):
    with conn.cursor() as cur:
        acct1 = mk_account(cur)
        acct2 = mk_account(cur)
        eid = mk_entry(cur, actual_scenario_id)
        mk_line(cur, eid, acct1["id"], 75, line_no=1)
        mk_line(cur, eid, acct2["id"], -75, line_no=2)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO journal_entries
                   (scenario_id, entry_date, description, reverses_entry_id)
               VALUES (%s, CURRENT_DATE, 'reversal 1', %s) RETURNING id""",
            (actual_scenario_id, eid))
        rid = cur.fetchone()["id"]
        mk_line(cur, rid, acct1["id"], -75, line_no=1)
        mk_line(cur, rid, acct2["id"], 75, line_no=2)
    conn.commit()

    with expect_error(conn):
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO journal_entries
                       (scenario_id, entry_date, description, reverses_entry_id)
                   VALUES (%s, CURRENT_DATE, 'reversal 2', %s)""",
                (actual_scenario_id, eid))

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM journal_entries WHERE reverses_entry_id = %s",
                    (eid,))
        assert cur.fetchone()["n"] == 1


# ---------------------------------------------------------------------------
# postwarden_bi — the read-only BI role (SPEC.md decision 14). Connects
# as its own login, BI_URL, rather than
# through the `conn` fixture (the superuser-ish `postwarden`) — the point is to
# exercise the grants Postgres actually enforces for this role, not just
# what the app happens to query.
# ---------------------------------------------------------------------------
def test_bi_role_can_select_reporting_objects():
    with psycopg.connect(BI_URL) as bi_conn:
        with bi_conn.cursor() as cur:
            for stmt in [
                "SELECT * FROM v_dim_account LIMIT 1",
                "SELECT * FROM v_fact_lines LIMIT 1",
                "SELECT * FROM v_dim_date LIMIT 1",
                "SELECT * FROM v_monthly_activity LIMIT 1",
                "SELECT * FROM fn_trial_balance('ACTUAL', CURRENT_DATE)",
            ]:
                cur.execute(stmt)  # must not raise


def test_bi_role_cannot_write_a_journal_entry(actual_scenario_id):
    with psycopg.connect(BI_URL) as bi_conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with bi_conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO journal_entries (scenario_id, entry_date, description) "
                    "VALUES (%s, CURRENT_DATE, 'postwarden_bi should not be able to do this')",
                    (actual_scenario_id,))


def test_bi_role_cannot_read_base_tables():
    """Not just journal_lines — v_fact_lines joins through `users` for
    posted_by, so the base table (password_hash included) is one careless
    `information_schema` query away if the grant were on the schema instead
    of the four reporting views specifically."""
    with psycopg.connect(BI_URL) as bi_conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with bi_conn.cursor() as cur:
                cur.execute("SELECT password_hash FROM users")
