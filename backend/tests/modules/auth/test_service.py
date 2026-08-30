"""DB-backed tests of `modules.auth.service` — login/session lifecycle,
CSRF comparison, username/password change validation, and admin
bootstrap. `test_repository.py` already covers the raw SQL; this file
covers the behavior/validation `service.py` adds on top of it."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from postwarden.modules.auth import repository as repo
from postwarden.modules.auth import service

from .conftest import mk_user

# ---------------------------------------------------------------------------
# login / sessions
# ---------------------------------------------------------------------------


def test_login_happy_path_returns_a_new_session(conn, user):
    result = service.login(conn, user["username"], user["password"])
    assert result["user_id"] == user["id"]
    assert result["username"] == user["username"]
    row = repo.session_by_token(conn, result["token"])
    assert row["csrf_token"] == result["csrf_token"]


def test_login_is_case_and_whitespace_insensitive_on_username(conn, user):
    result = service.login(conn, f"  {user['username'].upper()}  ", user["password"])
    assert result["user_id"] == user["id"]


def test_login_rejects_wrong_password(conn, user):
    with pytest.raises(service.InvalidCredentialsError):
        service.login(conn, user["username"], "wrong password")


def test_login_rejects_unknown_username(conn):
    with pytest.raises(service.InvalidCredentialsError):
        service.login(conn, "nobody", "whatever")


def test_login_rejects_an_inactive_user(conn):
    inactive = mk_user(conn, "retired", is_active=False)
    with pytest.raises(service.InvalidCredentialsError):
        service.login(conn, inactive["username"], inactive["password"])


def test_login_rate_limited_after_max_attempts(conn, user):
    for _ in range(service.LOGIN_MAX_ATTEMPTS):
        with pytest.raises(service.InvalidCredentialsError):
            service.login(conn, user["username"], "wrong password")
    with pytest.raises(service.RateLimitedError):
        service.login(conn, user["username"], user["password"])


def test_login_clears_the_throttle_on_success(conn, user):
    service.record_failed_login(user["username"])
    service.login(conn, user["username"], user["password"])
    assert service.is_rate_limited(user["username"]) is False


def test_get_session_round_trips_a_freshly_created_one(conn, user):
    token, csrf_token = service.create_session(conn, user["id"])
    session = service.get_session(conn, token)
    assert session["user_id"] == user["id"]
    assert session["csrf_token"] == csrf_token


def test_get_session_none_for_no_token(conn):
    assert service.get_session(conn, None) is None
    assert service.get_session(conn, "") is None


def test_get_session_none_for_unknown_token(conn):
    assert service.get_session(conn, "no-such-token") is None


def test_get_session_deletes_and_returns_none_for_an_expired_one(conn, user):
    token, _ = service.create_session(conn, user["id"])
    conn.execute(text("UPDATE sessions SET expires_at = :past WHERE token = :token"),
                 {"past": datetime.now(timezone.utc) - timedelta(days=1), "token": token})
    assert service.get_session(conn, token) is None
    assert repo.session_by_token(conn, token) is None  # lazily cleaned up


def test_get_session_none_once_the_user_is_deactivated(conn, user):
    token, _ = service.create_session(conn, user["id"])
    conn.execute(text("UPDATE users SET is_active = FALSE WHERE id = :id"), {"id": user["id"]})
    assert service.get_session(conn, token) is None


def test_logout_deletes_the_session(conn, user):
    token, _ = service.create_session(conn, user["id"])
    service.logout(conn, token)
    assert repo.session_by_token(conn, token) is None


def test_logout_is_a_no_op_with_no_token(conn):
    service.logout(conn, None)  # doesn't raise


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


def test_require_csrf_passes_on_a_matching_token():
    service.require_csrf({"csrf_token": "abc"}, "abc")  # doesn't raise


@pytest.mark.parametrize("session, token", [
    (None, "abc"),
    ({"csrf_token": "abc"}, None),
    ({"csrf_token": "abc"}, "wrong"),
])
def test_require_csrf_raises_on_a_missing_or_mismatched_token(session, token):
    with pytest.raises(ValueError, match="expired or.*stale"):
        service.require_csrf(session, token)


# ---------------------------------------------------------------------------
# Account settings
# ---------------------------------------------------------------------------


def test_change_username_normalizes_and_updates(conn, user):
    new_name = service.change_username(conn, user["id"], "  DAVE  ")
    assert new_name == "dave"
    assert repo.user_by_id(conn, user["id"])["username"] == "dave"


def test_change_username_rejects_a_bad_pattern(conn, user):
    with pytest.raises(ValueError, match="3-32 characters"):
        service.change_username(conn, user["id"], "x")


def test_change_username_collision_raises_integrity_error(conn, user):
    other = mk_user(conn, "taken")
    with pytest.raises(IntegrityError):
        service.change_username(conn, user["id"], other["username"])


def test_change_password_happy_path_revokes_sessions(conn, user):
    token, _ = service.create_session(conn, user["id"])
    service.change_password(conn, user["id"], user["password"], "newpassword1", "newpassword1")
    assert repo.session_by_token(conn, token) is None
    row = repo.user_by_id(conn, user["id"])
    assert service.verify_password("newpassword1", row["password_hash"])


def test_change_password_rejects_wrong_current_password(conn, user):
    with pytest.raises(ValueError, match="Current password is incorrect"):
        service.change_password(conn, user["id"], "wrong", "newpassword1", "newpassword1")


def test_change_password_rejects_a_mismatched_confirmation(conn, user):
    with pytest.raises(ValueError, match="don't match"):
        service.change_password(conn, user["id"], user["password"], "newpassword1", "different")


def test_change_password_rejects_a_too_short_new_password(conn, user):
    with pytest.raises(ValueError, match="at least 8 characters"):
        service.change_password(conn, user["id"], user["password"], "short", "short")


# ---------------------------------------------------------------------------
# Admin bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_admin_from_env_creates_a_user_when_none_exist(conn):
    service.bootstrap_admin_from_env(conn, "admin", "devpassword")
    row = repo.user_by_username(conn, "admin")
    assert row is not None
    assert service.verify_password("devpassword", row["password_hash"])


def test_bootstrap_admin_from_env_noop_once_a_user_already_exists(conn, user):
    service.bootstrap_admin_from_env(conn, "admin", "devpassword")
    assert repo.user_by_username(conn, "admin") is None


@pytest.mark.parametrize("username, password", [("", "devpassword"), ("admin", "")])
def test_bootstrap_admin_from_env_noop_with_a_missing_env_var(conn, username, password):
    service.bootstrap_admin_from_env(conn, username, password)
    assert repo.any_user_exists(conn) is False
