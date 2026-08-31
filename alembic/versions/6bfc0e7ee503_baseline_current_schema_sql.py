"""baseline: current schema.sql

Revision ID: 6bfc0e7ee503
Revises:
Create Date: 2026-08-29 17:00:38.518263

REBUILD.md §5 decision 5: Alembic replaces the hand-rolled runner in
app/migrate.py, with db/schema.sql as the baseline revision. schema.sql
itself stays the source of truth for a fresh install — this migration does
not re-derive the schema in SQLAlchemy's own metadata language, it just
applies the exact same file, so "alembic upgrade head" and "psql -f
schema.sql" are guaranteed to produce identical databases (there is only
one definition, not two that could drift).

schema.sql is 1,259 lines of plain SQL including PL/pgSQL functions in
dollar-quoted bodies (fn_generate_entry_id, fn_entry_balanced, etc.) and
its own explicit BEGIN/COMMIT wrapping the whole file. It cannot go through
op.execute(sqlalchemy.text(...)): SQLAlchemy's own statement layer treats
literal '%' (used in the schema's NUMERIC/CHECK expressions and comments)
as a paramstyle placeholder and raises before the query ever reaches
Postgres. Dropping to the raw DBAPI cursor bypasses that layer entirely —
the file is sent to Postgres exactly as psql would send it, which is also
exactly how docker-entrypoint-initdb.d already applies it for a fresh
docker compose install (see docker-compose.yml).

schema.sql's own BEGIN/COMMIT also means this can't run inside Alembic's
usual wrapping transaction (nesting a real BEGIN/COMMIT under Alembic's
own would let the file's COMMIT quietly close Alembic's transaction out
from under it). `autocommit_block()` steps out of that wrapping for this
one migration, so schema.sql's BEGIN/COMMIT are the only transaction
control in effect, exactly as when psql runs the file directly.

Confirmed: a fresh database + `alembic upgrade head` reproduces the same
table/function/trigger counts as loading schema.sql directly.
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '6bfc0e7ee503'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# alembic/versions/<this file>.py -> repo root is 3 levels up.
SCHEMA_SQL = Path(__file__).resolve().parents[2] / "db" / "schema.sql"


def upgrade() -> None:
    """Apply db/schema.sql verbatim, via the raw DBAPI cursor (see module docstring)."""
    schema_sql = SCHEMA_SQL.read_text()
    with op.get_context().autocommit_block():
        raw_conn = op.get_bind().connection.dbapi_connection
        raw_conn.cursor().execute(schema_sql)


def downgrade() -> None:
    """Drop everything. There is no prior revision to go back to — this is the baseline."""
    with op.get_context().autocommit_block():
        op.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
