from dataclasses import replace

from fastapi.testclient import TestClient

import backend.security.auth as auth
from backend.db import database
from backend.main import app


def _enable_local_auth(monkeypatch):
    monkeypatch.setattr(
        auth,
        "settings",
        replace(
            auth.settings,
            auth_mode="demo",
            environment="test",
            cookie_secure=False,
            demo_admin_username="test-admin",
            initial_admin_password="Test-Admin-Password-1!",
            login_attempt_limit=2,
        ),
    )
    monkeypatch.setattr(auth, "SessionLocal", database.SessionLocal)
    auth.ensure_bootstrap_admin()


def _login(client, username, password):
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()


def test_authentication_enforces_roles_csrf_and_revokes_logout(monkeypatch):
    _enable_local_auth(monkeypatch)
    admin = TestClient(app)
    assert admin.get("/api/stats").status_code == 401

    admin_session = _login(admin, "test-admin", "Test-Admin-Password-1!")
    csrf = admin_session["csrf_token"]
    assert admin.cookies.get("vidyutsetu_session")
    assert admin_session["user"]["role"] == "admin"

    created = admin.post(
        "/auth/users",
        json={"username": "auditor", "password": "Auditor-Password-1!", "role": "viewer"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    assert "password_hash" not in created.json()

    viewer = TestClient(app)
    _login(viewer, "auditor", "Auditor-Password-1!")
    assert viewer.get("/api/stats").status_code == 200
    assert viewer.post("/api/generate?vendor_id=alpha-hes").status_code == 403
    assert viewer.post(
        "/api/generate?vendor_id=alpha-hes",
        headers={"X-CSRF-Token": "invalid"},
    ).status_code == 403

    assert admin.post("/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert admin.get("/api/stats").status_code == 401


def test_authentication_limits_failed_logins_and_protects_last_admin(monkeypatch):
    _enable_local_auth(monkeypatch)
    admin = TestClient(app)
    csrf = _login(admin, "test-admin", "Test-Admin-Password-1!")["csrf_token"]
    user_id = admin.get("/auth/users").json()[0]["id"]
    client = TestClient(app)

    assert client.post("/auth/login", json={"username": "test-admin", "password": "wrong"}).status_code == 401
    assert client.post("/auth/login", json={"username": "test-admin", "password": "wrong"}).status_code == 401
    assert client.post("/auth/login", json={"username": "test-admin", "password": "wrong"}).status_code == 429

    response = admin.patch(
        f"/auth/users/{user_id}",
        json={"role": "viewer"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 409
