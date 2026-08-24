"""Exercises the invariants SPEC.md claims the database enforces.

Each test hits Postgres directly (see conftest.py) so there is no code
path — app, psql, or otherwise — that can route around what's asserted
here.
"""
from conftest import expect_error, mk_account, mk_entry, mk_line, mk_scenario


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


# ---------------------------------------------------------------------------
# Scenario locking
# ---------------------------------------------------------------------------
def test_locked_scenario_rejects_new_entries(conn):
    with expect_error(conn, match="locked"):
        with conn.cursor() as cur:
            scen = mk_scenario(cur, is_locked=True)
            mk_entry(cur, scen["id"])


# ---------------------------------------------------------------------------
# Postable / active account guard
# ---------------------------------------------------------------------------
def test_line_rejected_on_summary_account(conn, actual_scenario_id):
    with expect_error(conn, match="summary account"):
        with conn.cursor() as cur:
            summary = mk_account(cur, postable=False)
            eid = mk_entry(cur, actual_scenario_id)
            mk_line(cur, eid, summary["id"], 10)


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
