"""End-to-end tests of modules.auth.router — real HTTP requests through a
throwaway FastAPI() + include_router(), same pattern every prior
module's own test_router.py established. `TestClient` persists
Set-Cookie headers across requests on the same client instance, which is
what lets a test log in once and then exercise a cookie-protected route
without threading the token through by hand."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from postwarden.db import get_connection
from postwarden.modules.auth import service
from postwarden.modules.auth.router import router


def client_for(conn) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_connection] = lambda: conn
    return TestClient(app)


def test_login_returns_200_sets_cookie_and_csrf_token(conn, user):
    client = client_for(conn)
    resp = client.post("/login", json={"username": user["username"], "password": user["password"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == user["id"]
    assert body["username"] == user["username"]
    assert body["csrf_token"]
    assert client.cookies.get("postwarden_session")


def test_login_wrong_password_returns_401(conn, user):
    resp = client_for(conn).post(
        "/login", json={"username": user["username"], "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_username_returns_401(conn):
    resp = client_for(conn).post("/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401


def test_login_rate_limited_returns_429(conn, user):
    client = client_for(conn)
    for _ in range(service.LOGIN_MAX_ATTEMPTS):
        client.post("/login", json={"username": user["username"], "password": "wrong"})
    resp = client.post("/login", json={"username": user["username"], "password": user["password"]})
    assert resp.status_code == 429


def test_logout_clears_cookie_and_is_idempotent_with_no_session(conn, user):
    client = client_for(conn)
    client.post("/login", json={"username": user["username"], "password": user["password"]})
    resp = client.post("/logout")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # No session cookie at all this time — still succeeds.
    resp = client_for(conn).post("/logout")
    assert resp.status_code == 200


def test_me_returns_401_without_a_session(conn):
    assert client_for(conn).get("/me").status_code == 401


def test_me_returns_the_logged_in_user(conn, user):
    client = client_for(conn)
    login = client.post("/login", json={"username": user["username"],
                                         "password": user["password"]}).json()
    resp = client.get("/me")
    assert resp.status_code == 200
    assert resp.json() == {"id": user["id"], "username": user["username"],
                            "csrf_token": login["csrf_token"]}


def test_me_returns_401_after_logout(conn, user):
    client = client_for(conn)
    client.post("/login", json={"username": user["username"], "password": user["password"]})
    client.post("/logout")
    assert client.get("/me").status_code == 401


def test_change_username_requires_a_matching_csrf_header(conn, user):
    client = client_for(conn)
    login = client.post(
        "/login", json={"username": user["username"], "password": user["password"]}).json()
    resp = client.post("/settings/username", json={"username": "dave"})
    assert resp.status_code == 400
    resp = client.post("/settings/username", json={"username": "dave"},
                        headers={"X-CSRF-Token": "wrong"})
    assert resp.status_code == 400
    resp = client.post("/settings/username", json={"username": "dave"},
                        headers={"X-CSRF-Token": login["csrf_token"]})
    assert resp.status_code == 200
    assert resp.json() == {"username": "dave"}


def test_change_username_collision_returns_400(conn, user):
    from .conftest import mk_user
    mk_user(conn, "taken")
    client = client_for(conn)
    login = client.post(
        "/login", json={"username": user["username"], "password": user["password"]}).json()
    resp = client.post("/settings/username", json={"username": "taken"},
                        headers={"X-CSRF-Token": login["csrf_token"]})
    assert resp.status_code == 400


def test_change_password_wrong_current_returns_400(conn, user):
    client = client_for(conn)
    login = client.post(
        "/login", json={"username": user["username"], "password": user["password"]}).json()
    resp = client.post("/settings/password", headers={"X-CSRF-Token": login["csrf_token"]}, json={
        "current_password": "wrong", "new_password": "newpassword1",
        "confirm_password": "newpassword1"})
    assert resp.status_code == 400


def test_change_password_happy_path_revokes_session_and_clears_cookie(conn, user):
    client = client_for(conn)
    login = client.post(
        "/login", json={"username": user["username"], "password": user["password"]}).json()
    resp = client.post("/settings/password", headers={"X-CSRF-Token": login["csrf_token"]}, json={
        "current_password": user["password"], "new_password": "newpassword1",
        "confirm_password": "newpassword1"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # The very session that just changed the password no longer works.
    assert client.get("/me").status_code == 401
