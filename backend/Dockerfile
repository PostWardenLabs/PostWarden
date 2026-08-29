FROM python:3.12-slim
WORKDIR /srv/postwarden
COPY pyproject.toml .
COPY src ./src
RUN pip install --no-cache-dir -e .
COPY alembic.ini .
COPY alembic ./alembic
EXPOSE 8000
# alembic stamp head, not upgrade head: docker-compose.yml's db service
# loads schema.sql directly via docker-entrypoint-initdb.d, which already
# *is* the baseline schema — running upgrade here would try to re-create
# tables that already exist. Stamping just records "this database is
# already at the baseline revision" so later migrations apply cleanly on
# top, matching REBUILD.md §5 decision 5's "existing installs get alembic
# stamp head" language. A database that reached this point some other way
# (e.g. restored from a backup with no schema at all) would need `upgrade
# head` instead — not this dev-compose path.
CMD ["sh", "-c", "alembic stamp head && uvicorn postwarden.main:app --host 0.0.0.0 --port 8000"]
