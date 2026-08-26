# Migrations

Empty right now — there's nothing to migrate yet, `db/schema.sql` is the
first and only version. This directory is where that changes.

**When a schema change ships**: add `NNN_description.sql` here (next
sequential number, zero-padded to 3 digits — `001_add_thing.sql`), forward
SQL only, no down-migration. *Also* fold the same change into
`db/schema.sql` directly, and bump its `schema_version` seed
(`INSERT INTO schema_version (version) VALUES (N)`) to match — a fresh
install gets the full current state from `schema.sql` in one shot, never by
replaying every migration in order, so the two have to move together.
`app/migrate.py` is what applies these to an *existing* database, once, at
app startup — see its own docstring.
