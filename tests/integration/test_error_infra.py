"""Cross-cutting error-infrastructure tests: races, wrapping, correlation, 500s."""

import asyncio
import uuid

from src.core.exceptions import AppError

VALID = {"username": "john", "email": "john@example.com", "password": "Secure123"}
REGISTER = "/api/v1/auth/register"


async def test_concurrent_register_same_username_one_409(client):
    # TOCTOU race: both pass the service pre-check, one insert wins, the other
    # blocks on the row lock until the winner's teardown commit, then gets
    # IntegrityError -> 409 via the repository mapping. Requires real Postgres.
    r1, r2 = await asyncio.gather(
        client.post(REGISTER, json=VALID),
        client.post(REGISTER, json={**VALID, "email": "other@example.com"}),
    )
    assert sorted([r1.status_code, r2.status_code]) == [201, 409]
    loser = r1 if r1.status_code == 409 else r2
    assert loser.json()["code"] in ("username_taken", "conflict")


async def test_success_path_still_wrapped(client):
    resp = await client.post(REGISTER, json=VALID)
    assert resp.status_code == 201
    assert resp.json() == {"data": {"message": "Registration successful"}}


async def test_request_id_echoed_on_success(client):
    supplied = str(uuid.uuid4())  # default middleware validator requires UUID form
    resp = await client.post(REGISTER, json=VALID, headers={"X-Request-ID": supplied})
    assert resp.headers["x-request-id"] == supplied


async def test_request_id_in_error_body(client):
    supplied = str(uuid.uuid4())
    await client.post(REGISTER, json=VALID)
    resp = await client.post(
        REGISTER,
        json={**VALID, "email": "other@example.com"},
        headers={"X-Request-ID": supplied},
    )
    assert resp.status_code == 409
    assert resp.json()["request_id"] == supplied


async def test_unhandled_exception_returns_generic_500(app, raw_client):
    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret internal detail")

    resp = await raw_client.get("/boom")
    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["code"] == "internal_error"
    assert body["detail"] == "An unexpected error occurred"
    assert "secret internal detail" not in resp.text
    assert body["request_id"]


async def test_base_app_error_returns_500_with_code(app, raw_client):
    @app.get("/app-error")
    async def app_error_route():
        raise AppError("Authentication service unavailable")

    resp = await raw_client.get("/app-error")
    assert resp.status_code == 500
    assert resp.json()["code"] == "app_error"
