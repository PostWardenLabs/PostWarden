"""Shared fixtures for `modules/auth/` tests. See `../../conftest.py`
for the `conn` fixture (real Postgres, rolled back after every test)."""
import pytest
from sqlalchemy import text

from postwarden.modules.auth import repository as repo
from postwarden.modules.auth import service


def mk_user(conn, username: str = "david", password: str = "devpassword12",
            is_active: bool = True) -> dict:
    user_id = repo.insert_user(conn, username, service.hash_password(password))
    if not is_active:
        conn.execute(text("UPDATE users SET is_active = FALSE WHERE id = :id"), {"id": user_id})
    return {"id": user_id, "username": username, "password": password}


@pytest.fixture
def user(conn) -> dict:
    return mk_user(conn)


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """`service._failed_logins` is a single-process module-level dict —
    real in production (see `service.py`'s own docstring on why), but it
    would otherwise leak failed-attempt counts between tests that reuse
    the same username, making a later test's rate-limit assertion depend
    on test execution order. Cleared before and after every test in this
    package."""
    service._failed_logins.clear()
    yield
    service._failed_logins.clear()
