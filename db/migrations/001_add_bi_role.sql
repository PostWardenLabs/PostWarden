-- Read-only Postgres role for BI tools (Power BI, Excel, psql) that connect
-- straight to the database instead of through the app. SELECT-only on the
-- reporting views/function (SPEC.md decision 14) — never the base tables,
-- so a BI connection string handed out to Power BI can't write a journal
-- line or read a password hash out of `users`, even though it reads
-- `v_fact_lines`, which joins through `users` for `posted_by`.
--
-- CREATE ROLE has no IF NOT EXISTS (unlike CREATE TABLE), and roles are
-- cluster-wide rather than per-database, so this has to be a guarded DO
-- block to stay safe to run against a cluster that already has the role
-- from a previous database in it (e.g. the test suite, which recreates
-- libro_test from db/schema.sql on every run against the same cluster).
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'libro_bi') THEN
        CREATE ROLE libro_bi LOGIN PASSWORD 'libro_bi';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE libro TO libro_bi;
GRANT USAGE ON SCHEMA public TO libro_bi;
GRANT SELECT ON v_dim_account, v_fact_lines, v_dim_date, v_monthly_activity TO libro_bi;
GRANT EXECUTE ON FUNCTION fn_trial_balance(TEXT, DATE, DATE) TO libro_bi;

UPDATE schema_version SET version = 1;
