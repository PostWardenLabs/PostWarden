"""Unit tests for errors.pg_message — no database needed, same as
test_json.py's direct-encoder tests: fake objects shaped like a psycopg
diagnostic, not a real Postgres round-trip (that's what
modules/entries/test_service.py's `check_deferred_constraints` tests
exercise instead)."""
from sqlalchemy.exc import IntegrityError

from postwarden.errors import pg_message


class _FakeDiag:
    def __init__(self, message: str | None):
        self.message_primary = message


class _FakePgError(Exception):
    """Shaped like psycopg.Error just enough for pg_message: a `.diag`
    attribute with a `.message_primary`."""
    def __init__(self, message: str):
        super().__init__(message)
        self.diag = _FakeDiag(message)


def test_unwraps_sqlalchemy_dbapi_error_to_the_trigger_message():
    orig = _FakePgError("Journal lines are immutable. Post a reversing entry instead (entry ABC123)")
    exc = IntegrityError("INSERT INTO journal_lines ...", {}, orig)
    assert pg_message(exc) == "Journal lines are immutable. Post a reversing entry instead (entry ABC123)"


def test_a_bare_driver_error_is_used_directly_not_just_dbapi_error():
    orig = _FakePgError("boom")
    assert pg_message(orig) == "boom"


def test_falls_back_to_the_first_line_when_there_is_no_diag_message():
    exc = ValueError("plain message\nsecond line the caller never sees")
    assert pg_message(exc) == "plain message"


def test_dbapi_error_with_no_diag_message_falls_back_to_str_of_orig():
    orig = _FakePgError("connection refused")
    orig.diag = _FakeDiag(None)  # some psycopg errors carry a diag with no message_primary
    exc = IntegrityError("SELECT 1", {}, orig)
    assert pg_message(exc) == "connection refused"
