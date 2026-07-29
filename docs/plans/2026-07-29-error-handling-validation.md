# Error Handling & Validation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ad-hoc `ValueError`/`HTTPException` error handling with a domain exception hierarchy translated to RFC 9457 problem+json by centralized handlers, add request-ID correlation, and tighten input validation — refactoring the whole auth vertical to comply.

**Architecture:** Services/repositories raise `AppError` subclasses (framework-agnostic, defined in `src/core/exceptions.py`); four global FastAPI handlers translate them to `application/problem+json` bodies carrying a stable `code`, `request_id`, and 422 `errors[]`. Validation is layered: shape/format in controller schemas (shared `Annotated` types), semantics in services, uniqueness enforced by DB constraints with `IntegrityError → ConflictError` mapping in the repository.

**Tech Stack:** FastAPI, Pydantic 2.11, SQLAlchemy 2.0 async (asyncpg), Dishka DI, structlog, asgi-correlation-id, pytest + pytest-asyncio (auto mode) + httpx.

**Spec:** `docs/deprecated/specs/2026-07-29-error-handling-validation.md` — read it before starting. The error-code catalog and the commit-at-teardown invariant live there.

**Sequencing note:** Tasks 1–4 are pure additions (tree stays green). Tasks 5–9 are the refactor; between Task 5 (handlers rewritten, `ValueError` handler deleted) and Task 8 (service stops raising `ValueError`), auth failure paths temporarily return 500 when exercised live. That window only exists inside this branch; unit tests stay green throughout, and integration tests (Tasks 10–12) run after the vertical is consistent. Do not merge mid-way.

---

## Chunk 1: Foundations (no behavior change)

### Task 1: Dependencies and test scaffolding

**Files:**
- Modify: `pyproject.toml` (via `uv add`)
- Create: `tests/unit/__init__.py`, `tests/integration/__init__.py`

- [ ] **Step 1: Add runtime and test dependencies**

Run: `uv add asgi-correlation-id && uv add --dev httpx`
Expected: both resolve into `pyproject.toml` / `uv.lock` — `asgi-correlation-id` as a runtime dependency, `httpx` as a dev dependency (it is only used by `tests/integration` and is not currently in the lock file).

- [ ] **Step 2: Create test package dirs**

Run: `mkdir -p tests/unit tests/integration && touch tests/unit/__init__.py tests/integration/__init__.py`

Note: `pytest.ini` already sets `asyncio_mode = auto`, so async tests need no `@pytest.mark.asyncio` marker.

- [ ] **Step 3: Sanity-check the suite still collects**

Run: `uv run pytest --collect-only -q | tail -5`
Expected: existing `tests/db/*` tests collected, no errors.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock tests/unit/__init__.py tests/integration/__init__.py
git commit -m "chore: add asgi-correlation-id and httpx, scaffold test packages"
```

### Task 2: Domain exception hierarchy

**Files:**
- Modify: `src/core/exceptions.py` (currently empty, 0 bytes)
- Test: `tests/unit/test_exceptions.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the domain exception hierarchy."""

from src.core.exceptions import (
    AppError,
    ConflictError,
    EmailTakenError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
    NotFoundError,
    PermissionDeniedError,
    TokenExpiredError,
    UnauthorizedError,
    UsernameTakenError,
)


def test_app_error_defaults():
    err = AppError()
    assert err.code == "app_error"
    assert err.status_code == 500
    assert err.title == "Internal Server Error"
    assert err.headers is None
    assert err.message == "Internal Server Error"
    assert err.context == {}


def test_app_error_message_and_context():
    err = AppError("boom", user_id="u1")
    assert err.message == "boom"
    assert str(err) == "boom"
    assert err.context == {"user_id": "u1"}


def test_base_classes():
    assert (NotFoundError.code, NotFoundError.status_code) == ("not_found", 404)
    assert (ConflictError.code, ConflictError.status_code) == ("conflict", 409)
    assert (UnauthorizedError.code, UnauthorizedError.status_code) == ("unauthorized", 401)
    assert (PermissionDeniedError.code, PermissionDeniedError.status_code) == ("permission_denied", 403)


def test_unauthorized_carries_www_authenticate_challenge():
    assert UnauthorizedError.headers == {"WWW-Authenticate": "Bearer"}
    assert InvalidCredentialsError().headers == {"WWW-Authenticate": "Bearer"}


def test_auth_catalog():
    assert (UsernameTakenError.code, UsernameTakenError.status_code) == ("username_taken", 409)
    assert (EmailTakenError.code, EmailTakenError.status_code) == ("email_taken", 409)
    assert (InvalidCredentialsError.code, InvalidCredentialsError.status_code) == ("invalid_credentials", 401)
    assert (InvalidTokenError.code, InvalidTokenError.status_code) == ("invalid_token", 401)
    assert (TokenExpiredError.code, TokenExpiredError.status_code) == ("token_expired", 401)
    assert (InactiveUserError.code, InactiveUserError.status_code) == ("inactive_user", 403)


def test_catch_by_base_class():
    assert isinstance(UsernameTakenError(), ConflictError)
    assert isinstance(TokenExpiredError(), UnauthorizedError)
    assert isinstance(InactiveUserError(), PermissionDeniedError)
    assert isinstance(InactiveUserError(), AppError)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_exceptions.py -q`
Expected: FAIL with `ImportError: cannot import name 'AppError'`

- [ ] **Step 3: Implement `src/core/exceptions.py`**

Framework-agnostic: no FastAPI/Starlette imports allowed in this module.

```python
"""Domain exception hierarchy. Raised by services/repositories, translated by API handlers."""


class AppError(Exception):
    """Base application error."""

    code: str = "app_error"  # stable, machine-readable, part of the API contract
    status_code: int = 500
    title: str = "Internal Server Error"
    headers: dict[str, str] | None = None  # e.g. auth challenge, emitted by the handler

    def __init__(self, message: str | None = None, **context: object) -> None:
        self.message = message or self.title
        self.context = context  # extra k/v for logging only, never sent to clients
        super().__init__(self.message)


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404
    title = "Not Found"


class ConflictError(AppError):
    code = "conflict"
    status_code = 409
    title = "Conflict"


class UnauthorizedError(AppError):
    code = "unauthorized"
    status_code = 401
    title = "Unauthorized"
    headers = {"WWW-Authenticate": "Bearer"}  # RFC 9110 §11.6.1: 401 MUST carry a challenge


class PermissionDeniedError(AppError):
    code = "permission_denied"
    status_code = 403
    title = "Forbidden"


class UsernameTakenError(ConflictError):
    code = "username_taken"


class EmailTakenError(ConflictError):
    code = "email_taken"


class InvalidCredentialsError(UnauthorizedError):
    code = "invalid_credentials"


class InvalidTokenError(UnauthorizedError):
    code = "invalid_token"


class TokenExpiredError(UnauthorizedError):
    code = "token_expired"


class InactiveUserError(PermissionDeniedError):
    code = "inactive_user"
```

Do NOT add `UserNotFoundError` or `DomainValidationError` — deliberate omissions, see spec section 1.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_exceptions.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/exceptions.py tests/unit/test_exceptions.py
git commit -m "feat: domain exception hierarchy with stable error codes"
```

### Task 3: Shared validation types

**Files:**
- Create: `src/core/types.py`
- Test: `tests/unit/test_types.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for shared Annotated validation types."""

import pytest
from pydantic import BaseModel, ValidationError

from src.core.types import Password, Username


class UsernameModel(BaseModel):
    v: Username


class PasswordModel(BaseModel):
    v: Password


def test_username_valid():
    assert UsernameModel(v="john_doe-1").v == "john_doe-1"


def test_username_strips_whitespace():
    assert UsernameModel(v="  john  ").v == "john"


@pytest.mark.parametrize("bad", ["ab", "a" * 51, "has space", "bad!char"])
def test_username_invalid(bad):
    with pytest.raises(ValidationError):
        UsernameModel(v=bad)


def test_password_valid():
    assert PasswordModel(v="Secure123").v == "Secure123"


@pytest.mark.parametrize(
    "bad",
    [
        "Short1A",        # 7 chars: too short
        "alllower123",    # no uppercase
        "ALLUPPER123",    # no lowercase
        "NoDigitsHere",   # no digit
        "A1" + "a" * 71,  # 73 chars: over max_length
    ],
)
def test_password_invalid(bad):
    with pytest.raises(ValidationError):
        PasswordModel(v=bad)


def test_password_multibyte_over_72_bytes_rejected():
    # 24 chars of 'é' (2 bytes each) + 'A1a...' padding: <=72 CHARS but >72 BYTES.
    candidate = "A1a" + "é" * 36  # 39 chars, 3 + 72 = 75 bytes
    assert len(candidate) <= 72
    assert len(candidate.encode("utf-8")) > 72
    with pytest.raises(ValidationError, match="72 bytes"):
        PasswordModel(v=candidate)


def test_password_exactly_72_bytes_accepted():
    candidate = "A1" + "a" * 70  # 72 ASCII chars = 72 bytes
    assert PasswordModel(v=candidate).v == candidate
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_types.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.core.types'`

- [ ] **Step 3: Implement `src/core/types.py`**

```python
"""Shared Annotated types for boundary schema validation."""

import re
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

Username = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_-]+$",
        strip_whitespace=True,
    ),
]


def _max_72_bytes(v: str) -> str:
    # bcrypt's limit is 72 BYTES, not chars; multibyte UTF-8 can exceed it
    # even when max_length=72 passes. bcrypt 5.x raises on longer input.
    if len(v.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return v


def _check_complexity(v: str) -> str:
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain at least one digit")
    return v


Password = Annotated[
    str,
    Field(min_length=8, max_length=72),
    AfterValidator(_max_72_bytes),
    AfterValidator(_check_complexity),
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_types.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/types.py tests/unit/test_types.py
git commit -m "feat: shared Username/Password validation types with 72-byte bcrypt guard"
```

### Task 4: Request schema fixes

**Files:**
- Modify: `src/api/v1/schemas/user.py` (full rewrite, 63 lines)
- Test: `tests/unit/test_user_schemas.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for auth request/response schemas."""

import pytest
from pydantic import ValidationError

from src.api.v1.schemas.user import UserLogin, UserRegister, UserResponse


def test_register_valid():
    m = UserRegister(username="john", email="john@example.com", password="Secure123")
    assert m.username == "john"


def test_register_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        UserRegister(
            username="john", email="john@example.com", password="Secure123", extra="x"
        )


def test_register_rejects_weak_password():
    with pytest.raises(ValidationError):
        UserRegister(username="john", email="john@example.com", password="alllower1")


def test_login_allows_any_nonempty_credentials():
    # Login must NOT enforce the registration policy: wrong creds are a 401,
    # not a 422, and a policy change must not lock out existing users.
    m = UserLogin(username="ab", password="x")
    assert m.username == "ab"


def test_login_rejects_empty_fields():
    with pytest.raises(ValidationError):
        UserLogin(username="", password="x")
    with pytest.raises(ValidationError):
        UserLogin(username="ab", password="")


def test_login_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        UserLogin(username="ab", password="x", extra="y")


def test_user_response_from_attributes():
    class Obj:
        id = "01H"
        username = "john"
        email = "john@example.com"
        is_active = True

    m = UserResponse.model_validate(Obj())
    assert m.id == "01H"


def test_token_response_removed():
    with pytest.raises(ImportError):
        from src.api.v1.schemas.user import TokenResponse  # noqa: F401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_user_schemas.py -q`
Expected: FAIL — `test_register_rejects_unknown_fields`, `test_login_rejects_unknown_fields`, `test_token_response_removed` fail against the current schemas (extra fields silently allowed; `TokenResponse` exists). `test_login_allows_any_nonempty_credentials` also fails (current `UserLogin.username` has `min_length=3`).

- [ ] **Step 3: Rewrite `src/api/v1/schemas/user.py`**

Replace the entire file. `TokenResponse` is deleted — verified unused anywhere in `src/`.

```python
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.core.types import Password, Username


class UserRegister(BaseModel):
    """User registration payload."""

    model_config = ConfigDict(extra="forbid")

    username: Username
    email: EmailStr
    password: Password


class UserLogin(BaseModel):
    """User login payload. Deliberately loose: wrong credentials are a 401, never a 422."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserResponse(BaseModel):
    """User response model."""

    model_config = ConfigDict(from_attributes=True)

    id: str  # ULID
    username: str
    email: EmailStr
    is_active: bool
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_user_schemas.py tests/unit/test_types.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/v1/schemas/user.py tests/unit/test_user_schemas.py
git commit -m "feat: schemas use shared types, forbid extra fields, drop Pydantic v1 Config"
```

---

## Chunk 2: Handlers and the auth vertical refactor

### Task 5: RFC 9457 handlers rewrite (delete decorators)

**Files:**
- Modify: `src/api/exceptions/exception_handlers.py` (full rewrite, 280 lines → ~150)
- Modify: `src/api/v1/auth.py` (remove decorator import at line 11 and usages at lines 28, 76, 119, 176, 186)

The `@handle_service_errors` / `@handle_auth_errors` decorators duplicate and shadow the global handlers with divergent behavior. They are deleted, so their usages in `auth.py` must be removed in the same commit to keep the tree importable.

- [ ] **Step 1: Rewrite `src/api/exceptions/exception_handlers.py`**

Replace the entire file:

```python
"""RFC 9457 problem+json exception handlers. The single error-translation path."""

from http import HTTPStatus

from asgi_correlation_id.context import correlation_id
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core.exceptions import AppError
from src.core.logging import get_logger

logger = get_logger(__name__)

PROBLEM_JSON_MEDIA_TYPE = "application/problem+json"


class FieldError(BaseModel):
    """Single field failure inside a 422 response."""

    field: str  # dotted path, source prefix ("body", "query") stripped
    code: str  # pydantic-core error type, e.g. "string_too_short"
    message: str


class ProblemDetail(BaseModel):
    """RFC 9457 problem details body with project extensions."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    code: str  # extension: stable error code
    request_id: str | None = None  # extension: correlation ID
    errors: list[FieldError] | None = None  # extension: 422 field breakdown


def _problem_response(
    status_code: int,
    *,
    title: str,
    code: str,
    detail: str | None = None,
    errors: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    problem = ProblemDetail(
        title=title,
        status=status_code,
        detail=detail,
        code=code,
        request_id=correlation_id.get(),
        errors=errors,
    )
    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(exclude_none=True),
        media_type=PROBLEM_JSON_MEDIA_TYPE,
        headers=headers,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Translate domain errors. Expected failures: logged at WARNING."""
    logger.warning(
        "app_error",
        code=exc.code,
        status_code=exc.status_code,
        path=request.url.path,
        method=request.method,
        detail=exc.message,
        context=exc.context,
    )
    return _problem_response(
        exc.status_code,
        title=exc.title,
        code=exc.code,
        detail=exc.message,
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Translate request validation failures with a field-level breakdown."""
    errors = [
        FieldError(
            field=".".join(str(loc) for loc in err["loc"][1:]) or "__root__",
            code=err["type"],
            message=err["msg"],
        )
        for err in exc.errors()
    ]
    logger.info(
        "request_validation_failed",
        path=request.url.path,
        method=request.method,
        errors=[e.model_dump() for e in errors],
    )
    return _problem_response(
        422,
        title="Unprocessable Entity",
        code="validation_error",
        detail="Request validation failed",
        errors=errors,
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Translate transport-level HTTPExceptions (controllers/framework only)."""
    logger.warning(
        "http_exception",
        path=request.url.path,
        method=request.method,
        status_code=exc.status_code,
        detail=exc.detail,
    )
    try:
        title = HTTPStatus(exc.status_code).phrase
    except ValueError:  # non-standard status code must not crash the handler
        title = "Error"
    return _problem_response(
        exc.status_code,
        title=title,
        code="http_error",
        detail=str(exc.detail) if exc.detail else None,
        headers=dict(exc.headers) if exc.headers else None,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all: 500, generic body, full traceback in logs. Never leaks internals."""
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        error_type=type(exc).__name__,
        exc_info=True,
    )
    return _problem_response(
        500,
        title="Internal Server Error",
        code="internal_error",
        detail="An unexpected error occurred",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers. Called once from create_app()."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    # Starlette's class, not FastAPI's re-export: catches both.
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    # Special-cased by Starlette's ServerErrorMiddleware: the response is sent,
    # then the exception is re-raised (test clients see it unless configured not to).
    app.add_exception_handler(Exception, unhandled_exception_handler)
```

Deleted along with the old content: the `ValueError` handler (services stop raising `ValueError` in Task 8) and the pydantic-`ValidationError` handler (an internal `ValidationError` is a server bug — the catch-all's 500 is correct).

- [ ] **Step 2: Remove decorators from `src/api/v1/auth.py`**

- Delete line 11: `from src.api.exceptions.exception_handlers import handle_auth_errors, handle_service_errors`
- Delete the 5 decorator lines: `@handle_service_errors` (register, `/me`, `/profile`) and `@handle_auth_errors` (login, refresh)

Nothing else changes in this task (the missing-cookie `HTTPException` is replaced in Task 9).

- [ ] **Step 3: Verify the app still imports and unit tests pass**

Run: `uv run python -c "from src.main import app" && uv run pytest tests/unit -q`
Expected: import OK, all unit tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/api/exceptions/exception_handlers.py src/api/v1/auth.py
git commit -m "feat: RFC 9457 problem+json handlers, delete route decorators"
```

### Task 6: Request-ID correlation

**Files:**
- Modify: `src/main.py` (middleware registration, lines 74–84)
- Modify: `src/core/logging.py` (delete dead contextvar machinery, rewire processor)

- [ ] **Step 1: Register `CorrelationIdMiddleware` and expose the header**

In `src/main.py`, add the import:

```python
from asgi_correlation_id import CorrelationIdMiddleware
```

and change the middleware block in `create_app()` to:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(StandardResponseMiddleware)
app.add_middleware(CorrelationIdMiddleware)
```

`add_middleware` prepends: last-added runs outermost. `CorrelationIdMiddleware` must be outermost so the contextvar is set before any other middleware logs and the `X-Request-ID` header lands on every normally-handled response. (On the unhandled-500 path the header is absent — the body's `request_id` is the carrier there; see spec section 3.)

- [ ] **Step 2: Rewire logging, delete dead code**

In `src/core/logging.py`:

1. Delete the contextvar block (lines 17–20): `request_id_ctx`, `tenant_id_ctx`, `user_id_ctx` — and the now-unused `from contextvars import ContextVar` and `import uuid`.
2. Delete `generate_request_id()`, `set_request_context()`, `clear_request_context()` (lines 115–138). Verified: nothing in `src/` calls any of them.
3. Replace `add_request_context` with a processor that reads the correlation contextvar:

```python
from asgi_correlation_id.context import correlation_id


def add_request_context(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add the request correlation ID to log entries."""
    request_id = correlation_id.get()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict
```

The processor list in `setup_logging` already includes `add_request_context` — no change there. Keep `bind_context`/`clear_context` and everything else.

- [ ] **Step 3: Verify**

Run: `uv run python -c "from src.main import app" && uv run pytest tests/unit -q && ! grep -rn "request_id_ctx\|set_request_context\|generate_request_id" src/`
Expected: import OK, tests PASS, grep finds nothing (exit 0 overall)

- [ ] **Step 4: Commit**

```bash
git add src/main.py src/core/logging.py
git commit -m "feat: request-ID correlation via asgi-correlation-id, delete dead context machinery"
```

### Task 7: IntegrityError → ConflictError mapping

**Files:**
- Create: `src/repositories/error_mapping.py`
- Modify: `src/repositories/auth_repository.py` (`create_user`, lines 43–55)
- Test: `tests/unit/test_error_mapping.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for IntegrityError → domain error mapping."""

from sqlalchemy.exc import IntegrityError

from src.core.exceptions import ConflictError, EmailTakenError, UsernameTakenError
from src.repositories.error_mapping import map_integrity_error


class FakeUniqueViolation(Exception):
    """Stands in for asyncpg.exceptions.UniqueViolationError."""

    def __init__(self, constraint_name: str | None):
        self.constraint_name = constraint_name


def make_integrity_error(
    constraint_name: str | None = None, orig_text: str = "duplicate key"
) -> IntegrityError:
    # SQLAlchemy's asyncpg adapter wraps the driver error: the constraint name
    # lives at exc.orig.__cause__.constraint_name, not on exc.orig itself.
    orig = Exception(orig_text)
    if constraint_name is not None:
        orig.__cause__ = FakeUniqueViolation(constraint_name)
    return IntegrityError("INSERT INTO users ...", {}, orig)


def test_maps_username_index():
    err = map_integrity_error(make_integrity_error("ix_users_username"))
    assert isinstance(err, UsernameTakenError)


def test_maps_email_index():
    err = map_integrity_error(make_integrity_error("ix_users_email"))
    assert isinstance(err, EmailTakenError)


def test_unknown_constraint_falls_back_to_generic_conflict():
    err = map_integrity_error(make_integrity_error("some_other_constraint"))
    assert type(err) is ConflictError


def test_string_fallback_when_no_constraint_attr():
    err = map_integrity_error(
        make_integrity_error(None, 'duplicate key value violates "ix_users_email"')
    )
    assert isinstance(err, EmailTakenError)


def test_no_signal_at_all_returns_generic_conflict():
    err = map_integrity_error(make_integrity_error(None, "something opaque"))
    assert type(err) is ConflictError
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_error_mapping.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.repositories.error_mapping'`

- [ ] **Step 3: Implement `src/repositories/error_mapping.py`**

```python
"""Map database integrity violations to domain errors."""

from sqlalchemy.exc import IntegrityError

from src.core.exceptions import ConflictError, EmailTakenError, UsernameTakenError

# Unique INDEX names from the initial migration (alembic/versions/9bab9745873c_.py).
_CONSTRAINT_MAP: dict[str, type[ConflictError]] = {
    "ix_users_username": UsernameTakenError,
    "ix_users_email": EmailTakenError,
}


def map_integrity_error(exc: IntegrityError) -> ConflictError:
    """Return the domain error for a uniqueness violation."""
    # asyncpg's UniqueViolationError is wrapped by SQLAlchemy's adapter:
    # the name lives at exc.orig.__cause__.constraint_name.
    constraint = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
    if constraint is None:
        text = str(exc.orig)
        constraint = next((name for name in _CONSTRAINT_MAP if name in text), None)
    error_cls = _CONSTRAINT_MAP.get(constraint, ConflictError)
    return error_cls()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_error_mapping.py -q`
Expected: all PASS

- [ ] **Step 5: Wire into `AuthRepository.create_user`**

Replace the body of `create_user` in `src/repositories/auth_repository.py`:

```python
async def create_user(self, username: str, email: str, hashed_password: str) -> User:
    """Create a new user; raises a ConflictError subclass on uniqueness violation."""
    user = User(
        username=username,
        email=email,
        hashed_password=hashed_password,
        is_active=True
    )

    self.session.add(user)
    try:
        # flush() inside the try: the commit happens later in DI teardown,
        # so the constraint violation must surface within the request scope.
        await self.session.flush()
    except IntegrityError as exc:
        await self.session.rollback()
        raise map_integrity_error(exc) from exc
    await self.session.refresh(user)
    return user
```

Add the imports at the top of the file:

```python
from sqlalchemy.exc import IntegrityError

from src.repositories.error_mapping import map_integrity_error
```

`create_refresh_token` deliberately stays unmapped: `token_urlsafe(32)` collisions are cryptographically negligible (spec section 4).

**Commit-at-teardown invariant (spec section 4):** an `AppError` converted to a response means the Dishka scope exits cleanly and `session.commit()` runs even on a 4xx. The rollback above is what keeps the 409 path clean; any future code must raise domain errors before writes or roll back first.

- [ ] **Step 6: Run the full unit suite**

Run: `uv run pytest tests/unit -q`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/repositories/error_mapping.py src/repositories/auth_repository.py tests/unit/test_error_mapping.py
git commit -m "feat: map uniqueness IntegrityError to domain conflicts in repository"
```

### Task 8: AuthService raises domain errors

**Files:**
- Modify: `src/services/auth_service.py` (10 `ValueError` sites)
- Test: `tests/unit/test_auth_service.py`

- [ ] **Step 1: Write the failing tests**

Mock the repository with `AsyncMock`; no DB needed. `hash_password`/`verify_password`/token helpers run for real (pure functions).

```python
"""AuthService failure-mode tests with mocked repository."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.config import config
from src.core.exceptions import (
    EmailTakenError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
    TokenExpiredError,
    UsernameTakenError,
)
from src.core.security import hash_password
from src.dtos import UserLoginDTO, UserRegisterDTO
from src.services.auth_service import AuthService


def make_user(**overrides):
    defaults = dict(
        id="01HUSER",
        username="john",
        email="john@example.com",
        hashed_password=hash_password("Secure123"),
        is_active=True,
    )
    return SimpleNamespace(**{**defaults, **overrides})


def make_token_record(**overrides):
    defaults = dict(
        user_id="01HUSER",
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    return SimpleNamespace(**{**defaults, **overrides})


@pytest.fixture
def repo():
    r = AsyncMock()
    r.get_user_by_username.return_value = None
    r.get_user_by_email.return_value = None
    return r


@pytest.fixture
def service(repo):
    return AuthService(auth_repository=repo, config=config)


REGISTER_DTO = UserRegisterDTO(username="john", email="john@example.com", password="Secure123")
LOGIN_DTO = UserLoginDTO(username="john", password="Secure123")


async def test_register_duplicate_username(service, repo):
    repo.get_user_by_username.return_value = make_user()
    with pytest.raises(UsernameTakenError):
        await service.register_user(REGISTER_DTO)


async def test_register_duplicate_email(service, repo):
    repo.get_user_by_email.return_value = make_user()
    with pytest.raises(EmailTakenError):
        await service.register_user(REGISTER_DTO)


async def test_login_unknown_user(service, repo):
    with pytest.raises(InvalidCredentialsError):
        await service.login_user(LOGIN_DTO)


async def test_login_wrong_password(service, repo):
    repo.get_user_by_username.return_value = make_user()
    with pytest.raises(InvalidCredentialsError):
        await service.login_user(UserLoginDTO(username="john", password="Wrong456x"))


async def test_login_inactive_user(service, repo):
    repo.get_user_by_username.return_value = make_user(is_active=False)
    with pytest.raises(InactiveUserError):
        await service.login_user(LOGIN_DTO)


async def test_refresh_unknown_token(service, repo):
    repo.get_refresh_token.return_value = None
    with pytest.raises(InvalidTokenError):
        await service.refresh_token("nope")


async def test_refresh_revoked_token(service, repo):
    repo.get_refresh_token.return_value = make_token_record(is_revoked=True)
    with pytest.raises(InvalidTokenError):
        await service.refresh_token("tok")


async def test_refresh_expired_token(service, repo):
    repo.get_refresh_token.return_value = make_token_record(
        expires_at=datetime.now(timezone.utc) - timedelta(days=1)
    )
    with pytest.raises(TokenExpiredError):
        await service.refresh_token("tok")


async def test_refresh_vanished_user_is_401_not_404(service, repo):
    repo.get_refresh_token.return_value = make_token_record()
    repo.get_user_by_id.return_value = None
    with pytest.raises(InvalidTokenError):
        await service.refresh_token("tok")


async def test_refresh_inactive_user(service, repo):
    repo.get_refresh_token.return_value = make_token_record()
    repo.get_user_by_id.return_value = make_user(is_active=False)
    with pytest.raises(InactiveUserError):
        await service.refresh_token("tok")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_auth_service.py -q`
Expected: FAIL — the service still raises `ValueError`, so every `pytest.raises(<DomainError>)` fails.

Note: `src.core.config` reads env at import; the existing `tests/db` suite already imports it, so no extra setup should be needed. If config import fails locally, export the same env vars `tests/db` uses.

- [ ] **Step 3: Replace the `ValueError` sites in `src/services/auth_service.py`**

Add the import:

```python
from src.core.exceptions import (
    EmailTakenError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
    TokenExpiredError,
    UsernameTakenError,
)
```

Replacements (keep the surrounding `logger.warning` calls as they are):

| Line (current) | Current | New |
|---|---|---|
| 64 | `raise ValueError("Username already exists")` | `raise UsernameTakenError("Username already exists")` |
| 73 | `raise ValueError("Email already exists")` | `raise EmailTakenError("Email already exists")` |
| 165 | `raise ValueError("Invalid username or password")` | `raise InvalidCredentialsError("Invalid username or password")` |
| 175 | `raise ValueError("Invalid username or password")` | `raise InvalidCredentialsError("Invalid username or password")` |
| 185 | `raise ValueError("Account is inactive")` | `raise InactiveUserError("Account is inactive")` |
| 259 | `raise ValueError("Invalid refresh token")` | `raise InvalidTokenError("Invalid refresh token")` |
| 268 | `raise ValueError("Refresh token has been revoked")` | `raise InvalidTokenError("Refresh token has been revoked")` |
| 278 | `raise ValueError("Refresh token has expired")` | `raise TokenExpiredError("Refresh token has expired")` |
| 288 | `raise ValueError("User not found")` | `raise InvalidTokenError("Invalid refresh token")` — 401, never 404: a token endpoint must not leak account existence |
| 297 | `raise ValueError("Account is inactive")` | `raise InactiveUserError("Account is inactive")` |

Also update the three docstrings' `Raises:` lines (e.g. `ValueError: If username or email already exists` → `UsernameTakenError / EmailTakenError: on duplicate username/email`). Keep them to one line each.

The pre-checks at lines 58–73 stay: they give field-specific 409s on the common path; the repository mapping from Task 7 closes the TOCTOU race.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/auth_service.py tests/unit/test_auth_service.py
git commit -m "refactor: AuthService raises domain errors instead of ValueError"
```

### Task 9: auth_helpers rewrite + controller cleanup

**Files:**
- Modify: `src/services/shared/auth_helpers.py` (full rewrite, 139 lines)
- Modify: `src/api/v1/auth.py` (missing-refresh-cookie check, lines 127–131)

- [ ] **Step 1: Rewrite `src/services/shared/auth_helpers.py`**

Replace the entire file. Critical: `except AppError: raise` MUST come before `except Exception` — with the old ordering pattern, every 401/403 would collapse into a 500. Note that domain `InvalidTokenError` and `jwt.InvalidTokenError` share a name; `jwt.` stays qualified so there is no clash.

```python
"""
Authentication helper functions for FastAPI endpoints with DishkaRoute.

Since DishkaRoute doesn't support Depends() with FromDishka parameters, these are
helper functions (not FastAPI dependencies) that can be called manually in endpoints.
"""

from typing import TYPE_CHECKING, Optional

import jwt
from fastapi import Request

from src.core.config import Config
from src.core.exceptions import (
    AppError,
    InactiveUserError,
    InvalidTokenError,
    TokenExpiredError,
)
from src.core.logging import get_logger
from src.core.security import decode_access_token
from src.dtos.user_dto import AuthenticatedUserDTO
from src.models.auth import User as UserModel
from src.repositories.auth_repository import AuthRepository

if TYPE_CHECKING:
    from dishka import AsyncContainer

logger = get_logger(__name__)


async def get_authenticated_user_dependency(request: Request) -> AuthenticatedUserDTO:
    """Authenticate the user from the access-token cookie and return a DTO."""
    container: Optional["AsyncContainer"] = getattr(request.state, "dishka_container", None)

    if not container:
        logger.error("dishka_container_not_found", has_state=hasattr(request, "state"))
        raise AppError("Authentication service unavailable")

    try:
        config: Config = await container.get(Config)

        token = request.cookies.get("access_token")
        if not token:
            raise InvalidTokenError("Not authenticated")

        try:
            payload = decode_access_token(token, config)
            user_id: Optional[str] = payload.get("sub")
            if user_id is None:
                logger.warning("token_missing_user_id")
                raise InvalidTokenError("Invalid authentication credentials")
        except jwt.ExpiredSignatureError:
            logger.warning("token_expired")
            raise TokenExpiredError("Token has expired")
        except jwt.InvalidTokenError as e:
            logger.warning("invalid_token", error=str(e))
            raise InvalidTokenError("Invalid authentication credentials")

        auth_repository: AuthRepository = await container.get(AuthRepository)
        user_model: Optional[UserModel] = await auth_repository.get_user_by_id(user_id)

        if user_model is None:
            # 401, not 404: an auth endpoint must not leak account existence
            logger.warning("user_not_found", user_id=user_id)
            raise InvalidTokenError("Invalid authentication credentials")

        if not user_model.is_active:
            logger.warning("user_inactive", user_id=user_model.id)
            raise InactiveUserError("Inactive user account")

        user_dto = AuthenticatedUserDTO(
            id=user_model.id,
            username=user_model.username,
            email=user_model.email,
            is_active=user_model.is_active,
            created_at=user_model.created_at,
            updated_at=user_model.updated_at,
        )

        container.context[UserModel] = user_model
        container.context[AuthenticatedUserDTO] = user_dto
        request.state.user_id = user_model.id

        logger.debug("user_authenticated", user_id=user_dto.id, username=user_dto.username)
        return user_dto

    except AppError:
        raise  # domain errors pass through; the catch-all below must never see them
    except Exception as e:
        logger.error("authentication_error", error=str(e), error_type=type(e).__name__, exc_info=True)
        raise AppError("Authentication failed") from e
```

Behavior mapping (all previously `HTTPException`):
- missing cookie / malformed JWT / missing `sub` / unknown user → `InvalidTokenError` (401 + `WWW-Authenticate: Bearer` via class headers)
- expired JWT → `TokenExpiredError` (401)
- inactive user → `InactiveUserError` (403)
- missing Dishka container, unexpected exception → base `AppError` (500, `code="app_error"`)

- [ ] **Step 2: Replace the missing-cookie check in `src/api/v1/auth.py`**

In `refresh_token` (lines 127–131), replace:

```python
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing"
        )
```

with:

```python
    if not refresh_token:
        raise UnauthorizedError("Refresh token missing")
```

Update imports in `auth.py`: add `from src.core.exceptions import UnauthorizedError`; remove `HTTPException` from the `fastapi` import (it is now unused in this file — keep `status`, still used by the route decorators' `status_code=` arguments).

The health-check 503 in `src/main.py:111` keeps `HTTPException` — transport-level, controller layer, allowed.

- [ ] **Step 3: Verify layering — no HTTPException outside controllers**

Run: `uv run python -c "from src.main import app" && ! grep -rn "HTTPException" src/services/ && uv run pytest tests/unit -q`
Expected: import OK, grep finds nothing in `src/services/`, all unit tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/services/shared/auth_helpers.py src/api/v1/auth.py
git commit -m "refactor: auth helpers raise domain errors, drop HTTPException from services"
```

---

## Chunk 3: Integration tests

### Task 10: Testable app factory + integration conftest

**Files:**
- Modify: `src/main.py` (`create_app` signature, line 60)
- Create: `tests/integration/conftest.py`

Integration tests run against the real app with a **real Postgres** database (uniqueness constraints don't exist in fakes, and the concurrency test needs real row locking). Use the database from `docker-compose.yml` with a dedicated test DB, migrated via alembic.

- [ ] **Step 1: Make `create_app` accept an injected container AND own route registration**

Today all route registration happens at module level on the singleton (`src/main.py`: `@app.get("/health")` at line 92, `app.include_router(health_router)` / `app.include_router(auth_router, ...)` at lines 123–124). An app built by calling `create_app(container)` directly would have **no routes** — every test would 404. Fix both problems in `src/main.py`:

1. Change the factory signature and move ALL route registration inside it:

```python
from dishka import AsyncContainer, make_async_container


def create_app(container: AsyncContainer | None = None) -> FastAPI:
    """
    Create and configure FastAPI application with Dishka DI container.
    """
    if container is None:
        container = make_async_container(AppProvider(), context={Config: config})

    app = FastAPI(
        title=config.app_name,
        description="FastAPI application with structured logging and monitoring",
        version="0.1.0",
        lifespan=lifespan,
    )

    fastapi_integration.setup_dishka(container, app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(StandardResponseMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(auth_router, prefix="/api/v1", tags=["Authentication"])

    return app
```

2. Move the plain `/health` endpoint onto `health_router` (module level, defined BEFORE `create_app` is first called), so nothing is registered on the singleton directly. `DishkaRoute` handles dependency-free endpoints fine:

```python
health_router = APIRouter(route_class=DishkaRoute, tags=["Health"])


@health_router.get("/health")
async def health_check():
    """
    Basic liveness check endpoint.
    """
    return {"status": "healthy", "service": config.app_name}


@health_router.get("/health/ready")
async def readiness_check(engine: FromDishka[AsyncEngine]):
    ...  # unchanged body
```

3. Module bottom becomes just:

```python
app = create_app()
```

Delete the old module-level `@app.get("/health")` block and both old `app.include_router(...)` lines. Verify with `uv run python -c "from src.main import app; print([r.path for r in app.routes])"` — the list must include `/health`, `/health/ready`, and the `/api/v1/auth/*` paths.

- [ ] **Step 2: Write `tests/integration/conftest.py`**

```python
"""Integration test fixtures: real app, real Postgres, ASGI-level httpx client."""

import pytest
from dishka import make_async_container
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.config import Config, config
from src.ioc import AppProvider
from src.main import create_app


@pytest.fixture
async def app():
    container = make_async_container(AppProvider(), context={Config: config})
    application = create_app(container)
    yield application
    await container.close()


@pytest.fixture
async def client(app):
    # ASGITransport does not run lifespan: the startup DB ping is skipped,
    # but routes hit the real database through the container.
    # base_url MUST be https: auth cookies are set with secure=True, and
    # httpx's cookie jar refuses to send Secure cookies over an http:// URL.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as c:
        yield c


@pytest.fixture
async def raw_client(app):
    """Client that surfaces the app's 500 responses instead of re-raising."""
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="https://test") as c:
        yield c


@pytest.fixture(autouse=True)
async def clean_db(app):
    yield
    engine: AsyncEngine = await app.state.dishka_container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE refresh_tokens, users CASCADE"))
```

**Environment:** point the app's DB config at a test database before running (same env mechanism `src/core/config.py` / the existing `tests/db` suite uses), and run `uv run alembic upgrade head` against it once. Never point tests at a database with real data — `clean_db` truncates tables.

- [ ] **Step 3: Smoke-test the fixtures**

Create a trivial test inside `tests/integration/test_smoke.py`:

```python
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
```

Run: `uv run pytest tests/integration/test_smoke.py -q`
Expected: PASS (requires the test Postgres to be up: `docker compose up -d` first). Delete `test_smoke.py` after it passes — Task 12 covers the real success paths.

- [ ] **Step 4: Commit**

```bash
git add src/main.py tests/integration/conftest.py
git commit -m "test: integration fixtures with injectable DI container"
```

### Task 11: Integration tests — error paths

**Files:**
- Create: `tests/integration/test_auth_errors.py`

Every test asserts three things: exact status code, `content-type: application/problem+json`, and the stable `code` — plus `request_id` present and no internal details leaked.

- [ ] **Step 1: Write the tests**

```python
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
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/integration/test_auth_errors.py -q`
Expected: all PASS. If any fail, first check the test infrastructure (fixtures must use `https://test` — Secure cookies are silently dropped over `http://`; routes must be registered inside `create_app`, Task 10), then look for bugs in Tasks 5–9 code. Never weaken the assertions.

Note: `register()` sets cookies on the shared `client` via `Set-Cookie`; httpx's cookie jar persists them across requests in the same test.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_auth_errors.py
git commit -m "test: auth error-path contract tests (status, problem+json, codes)"
```

### Task 12: Integration tests — concurrency, regression, correlation

**Files:**
- Create: `tests/integration/test_error_infra.py`

- [ ] **Step 1: Write the tests**

```python
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
```

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest tests/unit tests/integration -q`
Expected: all PASS

Notes if the concurrency test misbehaves:
- Both requests share the app's engine pool (`pool_size=10`), so the loser's blocked insert can't starve the winner's commit. If it flakes, do NOT serialize the requests — that defeats the test; investigate lock ordering instead (spec Testing section).
- The 500-path tests use `raw_client` because Starlette re-raises after sending the 500 (`raise_app_exceptions=False` keeps httpx from propagating it).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_error_infra.py
git commit -m "test: uniqueness race, response wrapping, request-ID correlation, 500 paths"
```

### Task 13: Final verification

- [ ] **Step 1: Full suite + layering checks**

```bash
uv run pytest -q
! grep -rn "HTTPException" src/services/
! grep -rn "raise ValueError" src/services/ src/repositories/
! grep -rn "handle_service_errors\|handle_auth_errors" src/
```

Expected: everything passes, all greps empty.

- [ ] **Step 2: Manual smoke (optional but recommended)**

```bash
docker compose up -d
uv run uvicorn src.main:app --port 8001 &
curl -si -X POST localhost:8001/api/v1/auth/login -H 'content-type: application/json' -d '{"username":"ghost","password":"x"}' | head -20
```

Expected: `HTTP/1.1 401`, `content-type: application/problem+json`, `www-authenticate: Bearer`, body with `"code":"invalid_credentials"` and a `request_id`.

- [ ] **Step 3: Commit anything outstanding**

```bash
git status --short  # should be clean; commit stragglers if any
```
