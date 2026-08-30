"""Application settings — one place for every env var the app reads.

The legacy app read `os.environ.get(...)` ad hoc, in four different files,
each with its own default spelled out inline (`app/db.py`'s `DATABASE_URL`,
`app/auth.py`'s `POSTWARDEN_COOKIE_SECURE`, `app/main.py`'s
`POSTWARDEN_ADMIN_USER`/`POSTWARDEN_ADMIN_PASSWORD`/`POSTWARDEN_DEMO_MODE`/
`POSTWARDEN_BI_PORT`). Centralizing them here means a typo'd var name is a
`pydantic.ValidationError` at startup instead of a silently-empty default
three request handlers deep, and every consumer (routers, `db.py`, tests)
gets the same parsed/typed value instead of re-parsing the raw string.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    @field_validator("postwarden_cookie_secure", "postwarden_demo_mode", mode="before")
    @classmethod
    def _parse_legacy_bool(cls, value: object) -> object:
        """Same truthy set as legacy `os.environ.get(...).lower() in
        ("1", "true", "yes")`: those three spellings (any case) are True,
        every other string — including "", which is what an env var set but
        left blank in a .env file becomes — is False. Pydantic's own bool
        coercion is both looser (also accepts "on"/"off"/"t"/"f") and
        stricter (raises on "" instead of treating it as falsy); matching
        legacy exactly here avoids a startup crash on a blank-but-set var
        that used to be a harmless no-op.
        """
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes")
        return value

    # Same env var name as legacy app/db.py, but the SQLAlchemy-flavored
    # "postgresql+psycopg://" scheme, not legacy's plain "postgresql://" —
    # already the established convention here as of Phase 0.4's
    # alembic/env.py and backend/docker-compose.yml (both set/expect the
    # driver explicitly; SQLAlchemy would otherwise try psycopg2, which
    # this project doesn't install, instead of the psycopg3 that's pinned).
    database_url: str = Field(
        default="postgresql+psycopg://postwarden:postwarden@localhost:5432/postwarden",
        alias="DATABASE_URL",
    )

    # Cookies default to not-Secure. See legacy app/auth.py's comment on
    # why: an IAP tunnel or a plain-HTTP Docker network both present as
    # http://localhost to the *browser*, even though the outer hop is
    # encrypted — set this true only if uvicorn itself terminates real TLS.
    postwarden_cookie_secure: bool = Field(default=False, alias="POSTWARDEN_COOKIE_SECURE")

    # The one seeded login for demo/beta instances. app/cli.py's
    # `create-user` is the normal path for a real instance; this pair is
    # what demo's nightly reset re-seeds and what the login page banner
    # shows back to the visitor when POSTWARDEN_DEMO_MODE is set.
    postwarden_admin_user: str = Field(default="", alias="POSTWARDEN_ADMIN_USER")
    postwarden_admin_password: str = Field(default="", alias="POSTWARDEN_ADMIN_PASSWORD")

    # Shows the "you're on the public demo" banner and the credentials
    # inline on the login page — see legacy app/main.py's template globals.
    postwarden_demo_mode: bool = Field(default=False, alias="POSTWARDEN_DEMO_MODE")

    # Port shown to the user for connecting Power BI / psql directly to the
    # same Postgres instance (docker-compose maps this externally; the app
    # itself never connects out on it, just displays it).
    postwarden_bi_port: str = Field(default="5432", alias="POSTWARDEN_BI_PORT")

    # Where main.py looks for the built frontend (REBUILD_STATUS.md Phase
    # 2.1) — `frontend/`'s own vite.config.ts `build.outDir` points at this
    # exact path by convention, so a plain `npm run build` followed by a
    # plain `uvicorn postwarden.main:app` serves the SPA with zero wiring
    # locally, and the Dockerfile's multi-stage build (a Node build stage,
    # discarded before the final image — "no Node process at runtime" is the
    # actual gate) copies to this same relative spot inside the image. Not
    # required to exist: main.py only mounts it if the directory is actually
    # there, so a backend-only checkout (CI, a module's own tests, anyone
    # who hasn't run `npm run build` yet) is unaffected.
    postwarden_static_dir: Path = Field(
        default=Path(__file__).resolve().parent / "static",
        alias="POSTWARDEN_STATIC_DIR",
    )

    # Read by GET /config (Phase 3.1) for the footer's "PostWarden vX.Y.Z"
    # and login.html's own auth-brand corner — the same file legacy's
    # `app/main.py` reads once at startup (`(BASE.parent / "VERSION").
    # read_text().strip()`), just resolved at Settings-construction time
    # instead of module-import time. Two candidate locations, tried in
    # order, because this file's own distance from VERSION differs
    # between a local checkout and the built image: a repo-root
    # checkout has `backend/src/postwarden/config.py` three directories
    # under VERSION, but `backend/Dockerfile`'s runtime stage COPYs
    # VERSION straight into WORKDIR (`/srv/postwarden`) alongside
    # `pyproject.toml` — the same directory `pip install -e .` puts
    # `src/` under — which is only two directories up from here. Neither
    # candidate is required to exist (a backend-only checkout with no
    # VERSION file at all is a real, tolerated case — see `main.py`'s
    # own `/config` route for how an unreadable file degrades).
    postwarden_version_file: Path = Field(
        default_factory=lambda: next(
            (p for p in (
                Path(__file__).resolve().parents[3] / "VERSION",  # repo-root checkout
                Path(__file__).resolve().parents[2] / "VERSION",  # Docker image (WORKDIR)
            ) if p.is_file()),
            Path(__file__).resolve().parents[2] / "VERSION",  # default; may not exist
        ),
        alias="POSTWARDEN_VERSION_FILE",
    )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton, read from the environment once.

    A FastAPI dependency (`Depends(get_settings)`) rather than a bare
    module-level `settings = Settings()` so tests can override it per-test
    via `app.dependency_overrides[get_settings]` instead of mutating process
    env vars (which `lru_cache` would otherwise make sticky for the rest of
    the test run).
    """
    return Settings()
