"""Auth endpoint error-path contract tests: status, problem+json body, code."""

import pytest

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
ME = "/api/v1/auth/me"

VALID = {"username": "john", "email": "john@example.com", "password": "Secure123"}


def assert_problem(resp, status_code: int, code: str):
    assert resp.status_code == status_code
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["code"] == code
    assert body["status"] == status_code
    assert body["request_id"]
    # never leak internals
    assert "Traceback" not in resp.text
    assert "sqlalchemy" not in resp.text.lower()
    return body


async def register(client, **overrides):
    return await client.post(REGISTER, json={**VALID, **overrides})


async def test_register_duplicate_username(client):
    assert (await register(client)).status_code == 201
    resp = await register(client, email="other@example.com")
    assert_problem(resp, 409, "username_taken")


async def test_register_duplicate_email(client):
    assert (await register(client)).status_code == 201
    resp = await register(client, username="jane")
    assert_problem(resp, 409, "email_taken")


async def test_login_wrong_password(client):
    await register(client)
    resp = await client.post(LOGIN, json={"username": "john", "password": "Wrong456x"})
    assert_problem(resp, 401, "invalid_credentials")
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_login_unknown_user(client):
    resp = await client.post(LOGIN, json={"username": "ghost", "password": "Wrong456x"})
    assert_problem(resp, 401, "invalid_credentials")


async def test_login_with_short_username_is_401_not_422(client):
    # UserLogin deliberately does not enforce the registration policy
    resp = await client.post(LOGIN, json={"username": "ab", "password": "x"})
    assert_problem(resp, 401, "invalid_credentials")


async def test_refresh_missing_cookie(client):
    resp = await client.post(REFRESH)
    assert_problem(resp, 401, "unauthorized")
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_refresh_unknown_token(client):
    client.cookies.set("refresh_token", "not-a-real-token")
    resp = await client.post(REFRESH)
    assert_problem(resp, 401, "invalid_token")


async def test_refresh_expired_token(client, app):
    await register(client)
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncEngine

    engine: AsyncEngine = await app.state.dishka_container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE refresh_tokens SET expires_at = now() - interval '1 day'")
        )
    resp = await client.post(REFRESH)
    assert_problem(resp, 401, "token_expired")
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_refresh_reuse_after_rotation_is_revoked(client):
    await register(client)
    old_refresh = client.cookies["refresh_token"]
    resp = await client.post(REFRESH)
    assert resp.status_code == 200
    # rotate happened; replaying the old cookie must 401
    client.cookies.set("refresh_token", old_refresh)
    resp = await client.post(REFRESH)
    assert_problem(resp, 401, "invalid_token")


async def test_me_without_cookie(client):
    resp = await client.get(ME)
    assert_problem(resp, 401, "invalid_token")
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_me_with_malformed_jwt(client):
    client.cookies.set("access_token", "garbage.not.jwt")
    resp = await client.get(ME)
    assert_problem(resp, 401, "invalid_token")
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_me_with_expired_jwt(client):
    from src.core.config import config
    from src.core.security import create_access_token

    expired_config = config.model_copy(update={"access_token_expire_minutes": -5})
    token = create_access_token(
        data={"sub": "01HGHOST", "username": "ghost"}, config=expired_config
    )
    client.cookies.set("access_token", token)
    resp = await client.get(ME)
    assert_problem(resp, 401, "token_expired")
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_me_with_valid_token_for_deleted_user(client, app):
    await register(client)
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncEngine

    engine: AsyncEngine = await app.state.dishka_container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM refresh_tokens"))
        await conn.execute(text("DELETE FROM users"))
    resp = await client.get(ME)
    assert_problem(resp, 401, "invalid_token")


async def test_me_inactive_user(client, app):
    await register(client)
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncEngine

    engine: AsyncEngine = await app.state.dishka_container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE users SET is_active = false"))
    resp = await client.get(ME)
    assert_problem(resp, 403, "inactive_user")


async def test_422_shape(client):
    resp = await register(client, password="weak")
    body = assert_problem(resp, 422, "validation_error")
    assert body["errors"], "422 must carry a field breakdown"
    err = next(e for e in body["errors"] if e["field"] == "password")
    assert err["code"]  # pydantic-core type, e.g. "string_too_short"
    assert err["message"]


async def test_422_unknown_extra_field(client):
    resp = await register(client, unexpected="field")
    body = assert_problem(resp, 422, "validation_error")
    assert any(e["code"] == "extra_forbidden" for e in body["errors"])
