"""Integration tests for the auth module — register, login, tokens, and admin guards."""

import pytest
from jwt import decode as jwt_decode

from core.config import settings


# ── Registration ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_success(async_client):
    """POST /auth/register with valid data returns 201 + user data."""
    response = await async_client.post(
        "/auth/register",
        json={"email": "newuser@test.com", "password": "securepass", "name": "New User"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "newuser@test.com"
    assert body["name"] == "New User"
    assert body["role"] == "student"
    assert "password" not in body
    assert "hashed_password" not in body
    assert "id" in body


@pytest.mark.asyncio
async def test_register_duplicate_email(async_client, student_user):
    """POST /auth/register with existing email returns 409."""
    response = await async_client.post(
        "/auth/register",
        json={"email": "student@test.com", "password": "securepass", "name": "Dup User"},
    )
    assert response.status_code == 409
    assert "already registered" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_weak_password(async_client):
    """POST /auth/register with password < 8 chars returns 422."""
    response = await async_client.post(
        "/auth/register",
        json={"email": "weak@test.com", "password": "1234567", "name": "Weak"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_privileged_role(async_client):
    """Public registration must not allow users to self-assign privileged roles."""
    response = await async_client.post(
        "/auth/register",
        json={
            "email": "attacker@test.com",
            "password": "securepass",
            "name": "Privilege Escalation",
            "role": "admin",
        },
    )
    assert response.status_code == 403
    assert "student" in response.json()["detail"].lower()


# ── Login ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_success(async_client, student_user):
    """POST /auth/login with valid credentials returns 200 + tokens + user."""
    response = await async_client.post(
        "/auth/login",
        json={"email": "student@test.com", "password": "testpassword"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "student@test.com"
    assert body["user"]["role"] == "student"


@pytest.mark.asyncio
async def test_login_invalid_password(async_client, student_user):
    """POST /auth/login with wrong password returns 401."""
    response = await async_client.post(
        "/auth/login",
        json={"email": "student@test.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_email(async_client):
    """POST /auth/login with unknown email returns 401."""
    response = await async_client.post(
        "/auth/login",
        json={"email": "nobody@test.com", "password": "somepassword"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_user(async_client, db_session):
    """POST /auth/login for an inactive user returns 403."""
    from dependencies.auth import hash_password
    from models.user import User

    user = User(
        email="inactive@test.com",
        hashed_password=hash_password("testpassword"),
        role="student",
        name="Inactive User",
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    response = await async_client.post(
        "/auth/login",
        json={"email": "inactive@test.com", "password": "testpassword"},
    )
    assert response.status_code == 403
    assert "inactive" in response.json()["detail"].lower()


# ── /me ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_me_authenticated(async_client, student_token):
    """GET /auth/me with valid Bearer token returns user data."""
    response = await async_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "student@test.com"
    assert body["role"] == "student"
    assert "password" not in body


@pytest.mark.asyncio
async def test_me_unauthenticated(async_client):
    """GET /auth/me without token returns 401."""
    response = await async_client.get("/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_expired_token(async_client):
    """GET /auth/me with an expired JWT returns 401."""
    import time

    import jwt as pyjwt

    # Craft a token that expired 1 hour ago
    payload = {
        "sub": "00000000-0000-0000-0000-000000000000",
        "exp": int(time.time()) - 3600,
        "iat": int(time.time()) - 7200,
    }
    expired_token = pyjwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )

    response = await async_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


# ── Refresh Token ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_success(async_client, student_user):
    """POST /auth/refresh returns a new token pair."""
    # First login to get a refresh token
    login_resp = await async_client.post(
        "/auth/login",
        json={"email": "student@test.com", "password": "testpassword"},
    )
    assert login_resp.status_code == 200
    refresh_token = login_resp.json()["refresh_token"]

    # Use refresh token
    response = await async_client.post(
        "/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    # Tokens should be different from the original
    assert body["access_token"] != login_resp.json()["access_token"]
    assert body["refresh_token"] != login_resp.json()["refresh_token"]


# ── Admin guards ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_as_student(async_client, student_token):
    """Access admin endpoint with student token returns 403."""
    response = await async_client.get(
        "/admin/professors",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_admin_as_admin(async_client, admin_token):
    """Access admin endpoint with admin token returns 200."""
    response = await async_client.get(
        "/admin/professors",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200


# ── Registration edge cases ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_missing_fields(async_client):
    """POST /auth/register with missing required fields returns 422."""
    response = await async_client.post("/auth/register", json={})
    assert response.status_code == 422

    # Also test partial data
    response = await async_client.post(
        "/auth/register",
        json={"email": "partial@test.com"},  # missing password and name
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_invalid_email(async_client):
    """POST /auth/register with an invalid email format returns 422."""
    response = await async_client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "securepass", "name": "No Email"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_long_password(async_client):
    """POST /auth/register with password >128 chars returns 422.

    GIVEN a password string longer than 128 characters
    WHEN the register endpoint processes it
    THEN the request SHALL be rejected with 422 (Pydantic validation).
    """
    long_pw = "a" * 129
    response = await async_client.post(
        "/auth/register",
        json={"email": "longpw@test.com", "password": long_pw, "name": "Long PW"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_race_condition(async_client):
    """GIVEN two simultaneous register requests with the same email
    WHEN both are sent concurrently
    THEN exactly one succeeds (201) and the other gets 409.
    """
    import asyncio

    async def _register():
        return await async_client.post(
            "/auth/register",
            json={
                "email": "race_condition@test.com",
                "password": "securepass",
                "name": "Race User",
            },
        )

    responses = await asyncio.gather(_register(), _register())
    statuses = [r.status_code for r in responses]

    assert 201 in statuses, "At least one registration should succeed"
    assert 409 in statuses, "The duplicate registration should be rejected"


# ── Token edge cases ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_me_malformed_token(async_client):
    """GET /auth/me with a malformed (invalid) JWT returns 401."""
    response = await async_client.get(
        "/auth/me",
        headers={"Authorization": "Bearer this.is.not.a.valid.jwt"},
    )
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_refresh_revoked_token_reuse_detection(async_client, student_user):
    """POST /auth/refresh with a revoked token returns 401.

    GIVEN a refresh token that has already been used (rotated)
    WHEN the same refresh token is presented again
    THEN the server detects reuse, revokes ALL tokens for that user,
    AND returns 401 with 'revoked' in the detail.
    """
    # First login to get a refresh token
    login_resp = await async_client.post(
        "/auth/login",
        json={"email": "student@test.com", "password": "testpassword"},
    )
    assert login_resp.status_code == 200
    original_refresh = login_resp.json()["refresh_token"]

    # Use the refresh token once (legitimate rotation — old token gets revoked)
    first_use = await async_client.post(
        "/auth/refresh",
        json={"refresh_token": original_refresh},
    )
    assert first_use.status_code == 200

    # Use the SAME (now revoked) refresh token again → reuse detection
    second_use = await async_client.post(
        "/auth/refresh",
        json={"refresh_token": original_refresh},
    )
    assert second_use.status_code == 401
    assert "revoked" in second_use.json()["detail"].lower()


@pytest.mark.asyncio
async def test_refresh_expired_token_in_db(async_client, db_session, student_user):
    """POST /auth/refresh with a token that expired in the DB returns 401.

    GIVEN a refresh token whose ``expires_at`` is in the past
    WHEN the refresh endpoint processes it
    THEN 401 is returned with 'expired' in the detail.
    """
    import time
    from models.user import RefreshToken
    from dependencies.auth import hash_token

    # Create an expired refresh token directly in the DB
    expired_raw = "expired-test-token"
    expired_token = RefreshToken(
        token_hash=hash_token(expired_raw),
        user_id=student_user.id,
        expires_at=__import__("datetime").datetime.fromtimestamp(
            time.time() - 3600, tz=__import__("datetime").timezone.utc
        ),
    )
    db_session.add(expired_token)
    await db_session.commit()

    response = await async_client.post(
        "/auth/refresh",
        json={"refresh_token": expired_raw},
    )
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()
