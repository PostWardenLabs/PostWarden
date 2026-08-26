# Migrations

Empty on purpose right now, and staying that way for the moment — see
`CLAUDE.md`'s "Numbered migrations are on the shelf for now." Every
instance that exists today holds only dummy/test data, so a schema change
just ships straight into `db/schema.sql` and gets applied by wiping and
reinitializing (`docker compose down -v && docker compose up -d --build`)
rather than by a migration that preserves existing rows — there's nothing
worth preserving yet. `app/migrate.py` still runs on every app startup and
will apply anything it finds here (it's a harmless no-op against an empty
directory), so the mechanism itself hasn't been removed, just unused.

**Once some instance holds data worth keeping across a schema change**
(most likely the maintainer's own real ledger, eventually), resume this:
add `NNN_description.sql` here (next sequential number, zero-padded to 3
digits — `001_add_thing.sql`), forward SQL only, no down-migration. *Also*
fold the same change into `db/schema.sql` directly, and bump its
`schema_version` seed (`INSERT INTO schema_version (version) VALUES (N)`)
to match — a fresh install gets the full current state from `schema.sql`
in one shot, never by replaying every migration in order, so the two have
to move together. `app/migrate.py` is what applies these to an *existing*
database, once, at app startup — see its own docstring.
