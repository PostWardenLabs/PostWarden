"""DB-backed tests for `modules/auth/repository.py` — mostly SQL wiring
against a real Postgres, same scope every other module's own
`test_repository.py` keeps: prove each function returns/does what its
own docstring says, leave validation/assembly behavior to
`test_service.py`/`test_router.py`."""
from datetime import datetime, timedelta, timezone

from postwarden.modules.auth import repository as repo


def test_insert_user_and_lookup_by_username_and_id(conn):
    user_id = repo.insert_user(conn, "david", "hash-1")
    by_name = repo.user_by_username(conn, "david")
    by_id = repo.user_by_id(conn, user_id)
    assert by_name == {"id": user_id, "username": "david", "password_hash": "hash-1",
                        "is_active": True}
    assert by_id == by_name


def test_user_by_username_none_for_unknown(conn):
    assert repo.user_by_username(conn, "nobody") is None


def test_user_by_id_none_for_unknown(conn):
    assert repo.user_by_id(conn, 999999) is None


def test_any_user_exists_false_then_true(conn):
    assert repo.any_user_exists(conn) is False
    repo.insert_user(conn, "david", "hash-1")
    assert repo.any_user_exists(conn) is True


def test_update_username_changes_it(conn):
    user_id = repo.insert_user(conn, "david", "hash-1")
    repo.update_username(conn, user_id, "dave")
    assert repo.user_by_id(conn, user_id)["username"] == "dave"


def test_update_password_hash_changes_it(conn):
    user_id = repo.insert_user(conn, "david", "hash-1")
    repo.update_password_hash(conn, user_id, "hash-2")
    assert repo.user_by_id(conn, user_id)["password_hash"] == "hash-2"


def test_insert_session_and_session_by_token_joins_user(conn):
    user_id = repo.insert_user(conn, "david", "hash-1")
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    repo.insert_session(conn, user_id, "tok-1", "csrf-1", expires)
    row = repo.session_by_token(conn, "tok-1")
    assert row["user_id"] == user_id
    assert row["csrf_token"] == "csrf-1"
    assert row["username"] == "david"
    assert row["is_active"] is True
    assert row["expires_at"] == expires


def test_session_by_token_none_for_unknown(conn):
    assert repo.session_by_token(conn, "no-such-token") is None


def test_delete_session_removes_it(conn):
    user_id = repo.insert_user(conn, "david", "hash-1")
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    repo.insert_session(conn, user_id, "tok-1", "csrf-1", expires)
    repo.delete_session(conn, "tok-1")
    assert repo.session_by_token(conn, "tok-1") is None


def test_delete_sessions_for_user_removes_all(conn):
    user_id = repo.insert_user(conn, "david", "hash-1")
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    repo.insert_session(conn, user_id, "tok-1", "csrf-1", expires)
    repo.insert_session(conn, user_id, "tok-2", "csrf-2", expires)
    repo.delete_sessions_for_user(conn, user_id)
    assert repo.session_by_token(conn, "tok-1") is None
    assert repo.session_by_token(conn, "tok-2") is None
