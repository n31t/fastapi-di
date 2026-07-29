# Spec: Error Handling & Validation

**Date:** 2026-07-29
**Status:** Draft — pending review
**Scope:** Define project-wide error handling and validation conventions, and refactor the existing auth vertical to comply.

## Decisions (approved)

1. **Error backbone:** domain exception hierarchy raised in services/repositories, translated by centralized FastAPI exception handlers. Services never import `HTTPException`.
2. **Error response format:** RFC 9457 Problem Details (`application/problem+json`), hand-rolled in our own handlers (~30 lines) — no third-party library. Extension members: `code`, `request_id`, `errors[]`.
3. **Scope:** conventions + full refactor of the auth vertical (delete route decorators, replace `ValueError` usage, fix status codes, add `IntegrityError` handling).
4. **Testing:** unit + integration.

## Current state (why this spec exists)

- `src/core/exceptions.py` is empty. Services raise bare `ValueError` for semantically distinct failures (`src/services/auth_service.py:64,73,165,175,185,259,268,278,288,297`), so conflicts return 400 instead of 409 and failed logins 400 instead of 401.
- `HTTPException` is raised in three layers, including `src/services/shared/auth_helpers.py` (8 sites) — violating the CLAUDE.md layering rule.
- Route decorators `@handle_service_errors` / `@handle_auth_errors` (`src/api/exceptions/exception_handlers.py:184-279`) duplicate and shadow the globally registered handlers, with divergent behavior: one masks messages ("Invalid request"), the other leaks raw `str(e)`.
- The error body `{"status": "error", "code": ..., "message": ...}` is hand-rolled in 5 places; no machine-readable error code, no request correlation ID, no field-level validation details (422 returns a hardcoded "Invalid request data").
- No `IntegrityError` handling anywhere: a concurrent-register uniqueness race surfaces as an opaque 500. Repositories only `flush()`; the commit happens in DI session teardown after the route returns, outside any decorator scope.
- `UserResponse` uses Pydantic v1 `class Config` on Pydantic 2.11; request schemas allow unknown fields; password max length (100) exceeds bcrypt's 72-byte limit (bcrypt 5.x raises on longer input).

## Design

### 1. Domain exceptions — `src/core/exceptions.py`

Framework-agnostic; no FastAPI/Starlette imports.

```python
class AppError(Exception):
    """Base application error."""
    code: str = "app_error"          # stable, machine-readable, part of the API contract
    status_code: int = 500
    title: str = "Internal Server Error"
    headers: dict[str, str] | None = None   # e.g. auth challenge headers, emitted by the handler

    def __init__(self, message: str | None = None, **context: object) -> None:
        self.message = message or self.title
        self.context = context        # extra k/v for logging only, never sent to clients
        super().__init__(self.message)


class NotFoundError(AppError):
    code = "not_found"; status_code = 404; title = "Not Found"

class ConflictError(AppError):
    code = "conflict"; status_code = 409; title = "Conflict"

class UnauthorizedError(AppError):
    code = "unauthorized"; status_code = 401; title = "Unauthorized"
    headers = {"WWW-Authenticate": "Bearer"}   # RFC 9110 §11.6.1 — 401 MUST carry a challenge

class PermissionDeniedError(AppError):
    code = "permission_denied"; status_code = 403; title = "Forbidden"
```

`headers` exists because the current 401 paths send `WWW-Authenticate: Bearer` and RFC 9457 does not replace auth challenge headers; the `AppError` handler must merge `exc.headers` into the response. A `DomainValidationError` (422) class is deliberately **not** defined until a real use appears — its `code` would collide with the `RequestValidationError` handler's `validation_error` while producing a different envelope shape (no `errors[]`), which would break clients switching on `code`.

Auth-specific subclasses (defined in the same module or `src/core/exceptions.py` stays flat for now — one module until a second domain appears):

| Exception | Parent | `code` | HTTP |
|---|---|---|---|
| `UsernameTakenError` | `ConflictError` | `username_taken` | 409 |
| `EmailTakenError` | `ConflictError` | `email_taken` | 409 |
| `InvalidCredentialsError` | `UnauthorizedError` | `invalid_credentials` | 401 |
| `InvalidTokenError` | `UnauthorizedError` | `invalid_token` | 401 |
| `TokenExpiredError` | `UnauthorizedError` | `token_expired` | 401 |
| `InactiveUserError` | `PermissionDeniedError` | `inactive_user` | 403 |

There is deliberately no `UserNotFoundError` in the auth flows: "user vanished behind a valid token" (refresh, `/me`) is a token problem from the client's perspective and maps to `InvalidTokenError` (401), never 404 — a 404 from a token endpoint would leak account existence. `NotFoundError` subclasses appear when real resource endpoints (e.g. `/users/{id}`) exist.

Rules:
- Services and repositories raise these. Never `ValueError`, never `HTTPException`.
- Controllers **may** raise `HTTPException` for transport-level concerns (e.g. the health-check 503); services never. In practice the auth controllers use domain errors throughout for a uniform envelope (section 5).
- `code` values are a documented catalog; clients switch on `code`, never on message text (per Microsoft Azure guidelines / Google AIP-193).

### 2. Problem Details envelope + centralized handlers

Rewrite `src/api/exceptions/exception_handlers.py`. A single Pydantic schema replaces the five hand-rolled dicts:

```python
class ProblemDetail(BaseModel):
    """RFC 9457 problem details body with project extensions."""
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    code: str                          # extension: stable error code
    request_id: str | None = None      # extension: correlation ID
    errors: list[FieldError] | None = None  # extension: 422 field breakdown

class FieldError(BaseModel):
    field: str        # dotted path, source prefix ("body", "query") stripped
    code: str         # pydantic-core error type, e.g. "string_too_short"
    message: str
```

All error responses use `media_type="application/problem+json"`.

Registered handlers (`register_exception_handlers(app)` stays the entry point, called from `src/main.py`):

| Exception | Response | Logging |
|---|---|---|
| `AppError` | `exc.status_code`, `title`/`code` from class, `detail=exc.message`, `exc.headers` merged into response headers | WARNING (expected), with `code` + `context` |
| `RequestValidationError` | 422, `code="validation_error"`, `errors[]` built from `exc.errors()` | INFO |
| `StarletteHTTPException` | same envelope, `code="http_error"`, detail from exc | WARNING |
| `Exception` (catch-all) | 500, `code="internal_error"`, `detail="An unexpected error occurred"` — never internals | ERROR with `exc_info=True` |

Notes:
- Register against `starlette.exceptions.HTTPException`, not FastAPI's re-export (catches both).
- The bare-`Exception` handler is special-cased by Starlette (`ServerErrorMiddleware`); the exception is re-raised after the response is sent — expected, keeps test clients/ASGI servers seeing it.
- 422 `errors[].message` is the central place to rewrite stock Pydantic messages if product copy is ever needed (Pydantic has no per-constraint message override).
- **Delete** `@handle_service_errors` and `@handle_auth_errors` and all their usages in `src/api/v1/auth.py`. Global handlers are the single path.
- `StandardResponseMiddleware` already skips non-2xx responses, so success wrapping (`{"data": ...}`) is unaffected.
- Pydantic `ValidationError` escaping internal code (response serialization) stays a 500 via the catch-all — it signals a server bug, not client error.

### 3. Request-ID correlation

- Add dependency `asgi-correlation-id`; register `CorrelationIdMiddleware` in `src/main.py`.
- **Delete** the dead `request_id_ctx` / `set_request_context` machinery in `src/core/logging.py` (nothing in `src` calls it today). Instead, add a structlog processor (or per-request binding) that reads `asgi_correlation_id.context.correlation_id` so every log line carries `request_id`.
- Handlers read the same contextvar to fill `ProblemDetail.request_id` — this works even in the outermost 500 handler, since it shares the task context. The body is the reliable carrier on the 500 path (the middleware does not add the `X-Request-ID` header on unhandled-500 responses by default).
- Add `X-Request-ID` to the CORS `expose_headers` list so browser clients can read it.

### 4. Validation strategy

Layered, per the syntax/semantics split (cosmicpython Appendix E):

| Rule type | Layer | Mechanism | HTTP |
|---|---|---|---|
| Shape, type, format, length, range | Controller schema | `Field()` constraints, shared `Annotated` types, `EmailStr` | 422 |
| Cross-field within one payload | Controller schema | `model_validator(mode="after")` | 422 |
| Entity existence | Service | repo lookup → `NotFoundError` subclass | 404 |
| Permission / active-user | Service | check → `UnauthorizedError` / `PermissionDeniedError` | 401/403 |
| State rules (revoked/expired token) | Service | check → domain error | 401 |
| Uniqueness | DB constraint (authoritative) + optional service pre-check for UX | `IntegrityError` → `ConflictError` in repository | 409 |

Concrete changes:

- **Shared types module `src/core/types.py`:** reusable `Annotated` types used by schemas (and available to future DTOs):
  ```python
  Username = Annotated[str, StringConstraints(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$", strip_whitespace=True)]

  def _max_72_bytes(v: str) -> str:
      if len(v.encode("utf-8")) > 72:          # bcrypt limit is 72 BYTES, not chars —
          raise ValueError("Password must be at most 72 bytes")  # multibyte UTF-8 can exceed it
      return v

  Password = Annotated[str, Field(min_length=8, max_length=72), AfterValidator(_max_72_bytes), AfterValidator(_check_complexity)]
  ```
  Password complexity (upper/lower/digit) stays as an `AfterValidator` function in this module. The byte-length check is required because `max_length` counts characters; a ≤72-char password with multibyte UTF-8 would still make bcrypt 5.x raise → 500. Prefer declarative constraints over imperative validators; raise `ValueError` (never `assert`) inside validators.
- **Schema fixes (`src/api/v1/schemas/user.py`):**
  - `UserResponse`: `model_config = ConfigDict(from_attributes=True)` (drop Pydantic v1 `class Config`), `email: EmailStr`.
  - Request schemas get `model_config = ConfigDict(extra="forbid")` so unknown fields 422 instead of being silently dropped.
  - `UserRegister` uses `Username` + `Password`. **`UserLogin` uses neither shared type** — both fields validate only non-empty (`min_length=1`): enforcing the registration policy at login would leak the policy through 422s and lock out existing users if it ever tightens; wrong credentials must stay a 401, not a 422.
  - Remove unused `TokenResponse` or mark its purpose.
- **DTOs stay thin** plain dataclasses (unchanged, per CLAUDE.md). Boundary schemas own input validation; no rule duplication in DTOs.
- **Uniqueness:** the DB unique indexes on `users.username` / `users.email` are the source of truth. Repository `create_user` wraps its `flush()` in `try/except IntegrityError`, rolls back, and raises `UsernameTakenError`/`EmailTakenError`. Identifier detection, pinned to the actual schema and driver:
  - The identifiers are unique **index** names from the initial migration: `ix_users_username` and `ix_users_email` (`alembic/versions/9bab9745873c_.py`), not named UNIQUE constraints.
  - With asyncpg, the name is **not** on `exc.orig` directly — it lives at `exc.orig.__cause__.constraint_name` (asyncpg's `UniqueViolationError` wrapped by SQLAlchemy's adapter). Implement one tested helper `map_integrity_error(exc) -> AppError` that reads that path, with a string-match fallback on `str(exc.orig)`, and returns generic `ConflictError` when the identifier is unrecognized.
  - `refresh_tokens.token` is also unique, but no mapping is specified for `create_refresh_token`: the token is `token_urlsafe(32)`, so a collision is cryptographically negligible and may surface as the generic 500. Accepted.
- Because the session commit currently happens in DI teardown (`src/ioc/database_provider.py`), the repository must `flush()` inside the try block so constraint violations surface within the request scope, not after the response.
- **Commit-at-teardown invariant (must hold for every service method):** when an `AppError` is converted to a response by Starlette's `ExceptionMiddleware`, the Dishka request scope exits *cleanly* — `get_session`'s `except Exception` never fires and `session.commit()` runs even though the response is a 4xx. Therefore: **raise domain errors before performing writes, or roll back in the repository before raising.** Today's flows satisfy this (pre-checks raise before writes; the repo rolls back on `IntegrityError`), but any future edit that writes before a validation raise (e.g. revoking an old refresh token before discovering a problem) would silently commit the partial write.
- The existing service pre-checks (`exists_by_username`/`email`) stay as best-effort UX — field-specific errors on the common path; the repository mapping closes the TOCTOU race that currently produces a 500.

### 5. Auth vertical refactor

- `src/services/auth_service.py`: every `raise ValueError(...)` becomes the matching domain exception (register conflicts → `UsernameTakenError`/`EmailTakenError`; login failures → `InvalidCredentialsError`; inactive → `InactiveUserError`; refresh-token invalid/revoked/expired → `InvalidTokenError`/`TokenExpiredError`). The refresh flow's "user not found behind a valid token" case (`auth_service.py:288`) becomes `InvalidTokenError` (401) — **not** 404 — see the catalog note in section 1.
- `src/services/shared/auth_helpers.py`: rewritten, not just per-raise substituted. Target structure of the credential-checking function:

  ```python
  async def get_current_user(...) -> AuthenticatedUserDTO:
      # 6 auth-failure raises become domain errors:
      #   missing/invalid/expired JWT -> InvalidTokenError / TokenExpiredError
      #   unknown user               -> InvalidTokenError   (not 404 — don't leak existence)
      #   inactive user              -> InactiveUserError
      # The 2 current 500-paths (missing Dishka container, catch-all) stay 500:
      #   raise AppError("Authentication service unavailable")  # code=app_error
      try:
          ...checks...
      except AppError:
          raise                      # MUST re-raise BEFORE the generic catch —
      except Exception as e:         # otherwise every 401/403 collapses into a 500
          logger.error(...)
          raise AppError("Authentication failed") from e
  ```

  The current `except HTTPException: raise / except Exception: 500` ordering must become `except AppError: raise / except Exception: raise AppError`, or the outer catch-all swallows the domain errors. The file remains usable as a FastAPI dependency because the global `AppError` handler performs the HTTP translation (including `WWW-Authenticate: Bearer` on 401s via `UnauthorizedError.headers`).
- `src/api/v1/auth.py`: remove decorator usage; the missing-refresh-cookie check uses `UnauthorizedError` for a uniform envelope.
- `src/main.py` health check 503 keeps `HTTPException` (transport-level, controller layer).
- Resulting status-code fixes: register conflict 400→409, failed login 400→401, expired/revoked refresh 400→401, refresh with vanished user 400→401, inactive user →403. All 401s keep the `WWW-Authenticate: Bearer` challenge header (RFC 9110 §11.6.1).

### 6. Error-code catalog

Maintained as a table in this spec (section 1) and kept in sync with `src/core/exceptions.py`. Adding an error = adding a subclass; the handler needs no changes. `code` strings are immutable once shipped.

## Testing

Framework: `pytest` + `httpx.AsyncClient` against the app with the DI container overridden (fake repositories / test database).

**Unit tests**
- `AppError` subclasses expose the expected `code`/`status_code`/`title`/`headers` (including `WWW-Authenticate` on `UnauthorizedError`).
- `AuthService` methods raise the correct domain exception per failure mode (mocked repositories): duplicate username/email, wrong password, inactive user, revoked/expired/unknown refresh token, vanished user on refresh → `InvalidTokenError`.
- `map_integrity_error` helper: simulated `IntegrityError` carrying `ix_users_username` / `ix_users_email` / unknown identifier → `UsernameTakenError` / `EmailTakenError` / generic `ConflictError`; both the `exc.orig.__cause__.constraint_name` path and the string-match fallback.
- Shared validator functions: password complexity, username pattern, and the 72-**byte** check (a ≤72-char multibyte password must be rejected).

**Integration tests**
- Each auth endpoint's error paths assert exact status code **and** problem+json body: `content-type: application/problem+json`, correct `code`, `request_id` present, no internal details leaked.
- Register duplicate → 409 `username_taken` / `email_taken`; bad login → 401 `invalid_credentials`; expired refresh → 401 `token_expired`; inactive user → 403 `inactive_user`.
- Refactored `auth_helpers` paths via `GET /me`: missing cookie, malformed JWT, expired JWT, token for a deleted user, inactive user — each asserts status, `code`, and that 401s carry `WWW-Authenticate: Bearer`.
- 422 shape: invalid register payload returns `errors[]` with dotted `field`, pydantic `code`, message; unknown extra field → 422 (extra="forbid").
- Concurrency: two concurrent registers with the same username — one 201, one 409 (not 500). **Requires real Postgres** (constraints don't exist in fakes) and orchestration: the second insert blocks on the first's row lock until the first request's teardown commit, so the test must let request A complete before asserting B, or use two sessions with explicit commit ordering.
- Success-path regression: a 2xx response is still wrapped by `StandardResponseMiddleware` (`{"data": ...}`) with the new handlers registered.
- Unhandled-exception path: a route forced to raise returns 500 with generic body + `request_id`.
- `X-Request-ID` echo: supplied header is returned on success responses and appears in error bodies (including the 500 path, where the body is the only carrier).

## Out of scope

- Sentry / external error tracking (envelope and logging are structured to make this a drop-in later).
- OpenAPI 422 schema customization (FastAPI's generated 422 schema will not match the custom envelope — known FastAPI gap, fastapi#3650; accepted for now).
- Result/Either pattern (dry-python/returns) — researched and rejected: fights Python idiom and every exception-based library boundary.
- Roles/permissions modeling beyond the existing `is_active` check.

## References

- FastAPI error handling (official): https://fastapi.tiangolo.com/tutorial/handling-errors/
- RFC 9457 Problem Details (obsoletes RFC 7807): https://datatracker.ietf.org/doc/html/rfc9457
- Pydantic v2 validators: https://docs.pydantic.dev/latest/concepts/validators/
- Pydantic v2 fields / Annotated: https://docs.pydantic.dev/latest/concepts/fields/
- Pydantic strict mode: https://docs.pydantic.dev/latest/concepts/strict_mode/
- zhanymkanov/fastapi-best-practices: https://github.com/zhanymkanov/fastapi-best-practices
- Netflix Dispatch (production FastAPI): https://github.com/Netflix/dispatch/blob/main/src/dispatch/main.py
- Validation layering — cosmicpython Appendix E: https://www.cosmicpython.com/book/appendix_validation.html
- Microsoft Azure REST API guidelines (error codes as contract): https://github.com/microsoft/api-guidelines/blob/vNext/azure/Guidelines.md
- Google AIP-193 error model: https://google.aip.dev/193
- asgi-correlation-id: https://github.com/snok/asgi-correlation-id
- Uniqueness race prior art: https://code.djangoproject.com/ticket/24009 · https://www.bennadel.com/blog/3321-considering-uniqueness-constraints-and-database-abstractions-in-application-business-logic.htm
- BetterStack FastAPI error-handling guide: https://betterstack.com/community/guides/scaling-python/error-handling-fastapi/
- dry-python/returns (evaluated, rejected): https://github.com/dry-python/returns
