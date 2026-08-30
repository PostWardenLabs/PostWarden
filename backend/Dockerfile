# Two stages: a Node build stage that produces frontend/'s built output
# (straight into src/postwarden/static/, per frontend/vite.config.ts's own
# outDir), and the actual runtime image, which never installs Node at all —
# the builder stage is discarded once its output is copied over. This is
# REBUILD.md §5 decision 1's own "No Node at runtime" made real, not just
# stated: `docker history` on the final image has no node/npm layer, and its
# CMD below only ever invokes uvicorn.
#
# Build context is the *repo root*, not backend/ — see backend/docker-
# compose.yml's own comment on why (this stage needs to COPY ../frontend,
# which is out of reach of a backend/-scoped context). WORKDIR here is
# /repo, mirroring the real repo root layout (frontend/ and backend/ as
# siblings), so vite.config.ts's `outDir: '../backend/src/postwarden/
# static'` resolves to the same legible /repo/backend/... path a local,
# non-Docker `npm run build` would write to — not an unrelated absolute
# path a reader would have to work out by tracing the relative `..`.
FROM node:22-slim AS frontend-build
WORKDIR /repo
# package.json + package-lock.json first, alone, so `npm ci` is cached
# across rebuilds that only touch src/ — the same layer-ordering reasoning
# the runtime stage below already applies to pyproject.toml/src.
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./frontend/
RUN npm --prefix frontend ci
COPY frontend/ ./frontend/
RUN npm --prefix frontend run build

FROM python:3.12-slim
WORKDIR /srv/postwarden
COPY backend/pyproject.toml .
COPY backend/src ./src
RUN pip install --no-cache-dir -e .
COPY backend/alembic.ini .
COPY backend/alembic ./alembic
# Read by GET /config (Phase 3.1) for the footer/login-page version
# string — same file the legacy root Dockerfile already COPYs in for
# the identical reason. Lands at WORKDIR directly (not under src/),
# which is exactly the second candidate path config.py's own
# `postwarden_version_file` tries — see that field's own comment for
# why a plain repo-root-relative path wouldn't resolve the same way in
# this image as it does in a local checkout.
COPY VERSION .
# Lands at src/postwarden/static — same relative path frontend-build's own
# `npm run build` already wrote to directly (vite.config.ts's outDir), so a
# non-Docker local run (`npm run build` then a bare `uvicorn postwarden.
# main:app`) serves the identical layout with no extra step. main.py only
# mounts this if it's actually present, so nothing here is load-bearing —
# a build that somehow skipped the frontend-build stage would still produce
# a working, API-only image.
COPY --from=frontend-build /repo/backend/src/postwarden/static ./src/postwarden/static
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
