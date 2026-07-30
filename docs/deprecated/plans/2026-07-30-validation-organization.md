# Validation Organization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the validation kernel (`src/core/`) and document the one-home-per-rule validation ownership convention, per `docs/deprecated/specs/2026-07-29-validation-organization.md` (Approach D: small shared kernel + layered ownership).

**Architecture:** Extract private validator functions from `src/core/types.py` into a public `src/core/validators.py`; add reusable schema base models in `src/core/schemas.py`; migrate `src/api/v1/schemas/user.py` onto them; write `docs/conventions/validation.md` and a CLAUDE.md ownership section. Zero endpoint behavior changes — the existing 75 tests must stay green unchanged.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, uv.

**Branch:** Create `refactor/validation-organization` from `feature/error-handling-validation` (the validation stack this restructures — `src/core/types.py`, `src/repositories/error_mapping.py`, schema configs — lives on that branch, not yet merged to main). If that branch has merged by execution time, branch from `main` instead.

**Environment note:** Tests run against the dedicated `fastapi_di_test` database on the native Postgres at `localhost:8888`; the root `conftest.py` hard-sets `DB_NAME=fastapi_di_test` automatically. No setup needed if `uv run pytest` already passes (75 tests: 43 unit + 22 integration + 10 db).

---

## Chunk 1: Kernel restructure (code)

### Task 1: Create `src/core/validators.py` (TDD)

Public, Pydantic-free validator functions, extracted verbatim from the private `_max_72_bytes` / `_check_complexity` in `src/core/types.py`. No test imports the private names, so the move is safe.

**Files:**
- Create: `src/core/validators.py`
- Test: `tests/unit/test_validators.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_validators.py`:

```python
"""Tests for plain validator functions in core/validators."""

import pytest

from src.core.validators import validate_password_complexity, validate_utf8_max_72_bytes


def test_72_ascii_bytes_accepted():
    v = "a" * 72
    assert validate_utf8_max_72_bytes(v) == v


def test_73_ascii_bytes_rejected():
    with pytest.raises(ValueError, match="72 bytes"):
        validate_utf8_max_72_bytes("a" * 73)


def test_multibyte_over_72_bytes_rejected():
    # 39 chars but 75 UTF-8 bytes: char-count checks pass, byte check must not.
    candidate = "A1a" + "é" * 36
    assert len(candidate) <= 72
    assert len(candidate.encode("utf-8")) > 72
    with pytest.raises(ValueError, match="72 bytes"):
        validate_utf8_max_72_bytes(candidate)


def test_complexity_valid_passes():
    assert validate_password_complexity("Secure123") == "Secure123"


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        ("alllower123", "uppercase"),
        ("ALLUPPER123", "lowercase"),
        ("NoDigitsHere", "digit"),
    ],
)
def test_complexity_missing_class_rejected(bad, message):
    with pytest.raises(ValueError, match=message):
        validate_password_complexity(bad)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_validators.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.core.validators'`

- [ ] **Step 3: Write the implementation**

Create `src/core/validators.py`:

```python
"""Reusable plain validator functions. Wrapped by Annotated types in core/types.py."""
import re


def validate_utf8_max_72_bytes(v: str) -> str:
    # bcrypt's limit is 72 BYTES, not chars; multibyte UTF-8 can exceed it
    # even when max_length=72 passes. bcrypt 5.x raises on longer input.
    if len(v.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return v


def validate_password_complexity(v: str) -> str:
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain at least one digit")
    return v
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_validators.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/core/validators.py tests/unit/test_validators.py
git commit -m "feat(core): extract public validator functions into core/validators"
```

### Task 2: Slim `src/core/types.py` to Annotated definitions only

**Files:**
- Modify: `src/core/types.py` (replace entire file)

- [ ] **Step 1: Replace the file contents**

Replace ALL of `src/core/types.py` with:

```python
"""Shared Annotated types for boundary schema validation. Format rules ONLY —
anything needing DB or tenant context is a dependency or service rule, not a type."""
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

from src.core.validators import validate_password_complexity, validate_utf8_max_72_bytes

Username = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_-]+$",
        strip_whitespace=True,
    ),
]

Password = Annotated[
    str,
    Field(min_length=8, max_length=72),
    AfterValidator(validate_utf8_max_72_bytes),
    AfterValidator(validate_password_complexity),
]
```

- [ ] **Step 2: Run the existing type tests to verify behavior is preserved**

Run: `uv run pytest tests/unit/test_types.py tests/unit/test_validators.py tests/unit/test_user_schemas.py -v`
Expected: all pass (behavior-preserving refactor; `test_types.py` exercises `Username`/`Password` end to end, including the 72-byte boundary)

- [ ] **Step 3: Commit**

```bash
git add src/core/types.py
git commit -m "refactor(core): slim types.py to Annotated definitions importing core/validators"
```

### Task 3: Create `src/core/schemas.py` base models (TDD)

**Files:**
- Create: `src/core/schemas.py`
- Test: `tests/unit/test_base_schemas.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_base_schemas.py`:

```python
"""Tests for shared API schema base models."""

import pytest
from pydantic import ValidationError

from src.core.schemas import ResponseModel, StrictRequestModel


class StrictChild(StrictRequestModel):
    name: str


class ResponseChild(ResponseModel):
    id: str
    name: str


def test_strict_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        StrictChild(name="ok", surprise="nope")


def test_strict_request_accepts_known_fields():
    assert StrictChild(name="ok").name == "ok"


def test_response_model_builds_from_attributes():
    class Obj:
        id = "01H"
        name = "john"

    m = ResponseChild.model_validate(Obj())
    assert m.id == "01H"
    assert m.name == "john"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_base_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.core.schemas'`

- [ ] **Step 3: Write the implementation**

Create `src/core/schemas.py`:

```python
"""Base models for all API schemas."""
from pydantic import BaseModel, ConfigDict


class StrictRequestModel(BaseModel):
    """Base for request bodies: unknown fields are rejected (422), not silently dropped."""

    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    """Base for response schemas: buildable from ORM/DTO attributes."""

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_base_schemas.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/core/schemas.py tests/unit/test_base_schemas.py
git commit -m "feat(core): add StrictRequestModel and ResponseModel schema bases"
```

### Task 4: Migrate `src/api/v1/schemas/user.py` onto the base models

**Files:**
- Modify: `src/api/v1/schemas/user.py` (replace entire file)

- [ ] **Step 1: Replace the file contents**

Replace ALL of `src/api/v1/schemas/user.py` with:

```python
from pydantic import EmailStr, Field

from src.core.schemas import ResponseModel, StrictRequestModel
from src.core.types import Password, Username


class UserRegister(StrictRequestModel):
    """User registration payload."""

    username: Username
    email: EmailStr
    password: Password


class UserLogin(StrictRequestModel):
    """User login payload. Deliberately loose: wrong credentials are a 401, never a 422."""

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserResponse(ResponseModel):
    """User response model."""

    id: str  # ULID
    username: str
    email: EmailStr
    is_active: bool
```

Field definitions are unchanged; only the base classes replace the per-schema `model_config` (`extra="forbid"` on the two requests, `from_attributes=True` on the response). `UserLogin` stays deliberately loose.

- [ ] **Step 2: Run the schema tests to verify behavior is preserved**

Run: `uv run pytest tests/unit/test_user_schemas.py -v`
Expected: all pass — in particular `test_register_rejects_unknown_fields`, `test_login_rejects_unknown_fields` (extra="forbid" via base), and `test_user_response_from_attributes` (from_attributes via base)

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest`
Expected: 85 passed (75 existing + 7 from Task 1 + 3 from Task 3), 0 failed

- [ ] **Step 4: Commit**

```bash
git add src/api/v1/schemas/user.py
git commit -m "refactor(api): migrate user schemas onto shared base models"
```

## Chunk 2: Documentation

### Task 5: Write `docs/conventions/validation.md`

**Files:**
- Create: `docs/conventions/validation.md`

- [ ] **Step 1: Create the conventions doc**

Create `docs/conventions/validation.md` with exactly this content:

````markdown
# Validation Ownership Conventions

Every validation rule has exactly **one authoritative home**. Other layers may repeat a check for UX or defense in depth, but only one layer is the enforcement point.

## One home per rule

| Kind of rule | Authoritative home | Where in this repo |
|---|---|---|
| Syntactic / format / shape | API schemas, via shared `Annotated` types | `src/api/v1/schemas/`, `src/core/types.py` |
| Reusable field rules | Shared `Annotated` types module, format-only | `src/core/types.py` (wrapping `src/core/validators.py`) |
| Business rules (state, tenancy, workflow) | Services, raising domain exceptions | `src/services/`, `src/core/exceptions.py` |
| Uniqueness / cross-entity invariants | **DB constraint is authoritative**; `IntegrityError` → domain `ConflictError` | `src/models/`, `src/repositories/error_mapping.py` |
| DB-backed request checks (existence, ownership) | FastAPI dependencies | `src/api/v1/dependencies/` (created when first needed) |
| DTOs | Validation-free containers | `src/dtos/` |

## Rules

1. **Format rules live in schemas via shared `Annotated` types.** Add a new shared type to `src/core/types.py` when ≥2 schemas need the same rule, **or** when the rule is security-critical / defines the canonical format for a domain-wide field (as with `Password` and `Username`). Otherwise keep the rule inline in the schema that needs it.

2. **`src/core/types.py` stays format-only.** If a "type" needs DB, request, or tenant context, it is not a type — it is a FastAPI dependency or a service rule. Plain validator functions live in `src/core/validators.py` (public, Pydantic-free) so workers/CLI/service code can import them directly.

3. **Business rules live in services** and raise the `AppError` hierarchy from `src/core/exceptions.py`. Never in schemas, never in DTOs.

4. **DTOs are validation-free containers.** In this boilerplate they are stdlib dataclasses (see `src/dtos/user_dto.py`), constructed by services from models. Adding validation or business rules to DTOs is the primary drift vector and is forbidden. (Whether to migrate DTOs to Pydantic `BaseModel` — enabling `model_validate(model, from_attributes=True)` conversion per CLAUDE.md's service-layer pattern — is an open question left as future work.)

5. **Every uniqueness / cross-entity invariant gets a DB constraint** plus an entry in `_CONSTRAINT_MAP` (`src/repositories/error_mapping.py`). A service pre-check is optional and purely for UX; the constraint is the enforcement — pre-checks race, constraints don't.

6. **DB-backed request checks (existence, ownership) go in FastAPI dependencies** under `src/api/v1/dependencies/`. Create the package when the first path-ID endpoint appears — do not scaffold it empty. Worked example (illustrative — no `Review` entity exists yet; with Dishka, dependencies resolve services from the request-scoped container):

   ```python
   from typing import Annotated

   from fastapi import Depends, Request

   from src.dtos.review_dto import ReviewDTO
   from src.services.review_service import ReviewService


   async def valid_review_id(review_id: str, request: Request) -> ReviewDTO:
       """Resolve a path review_id or let the service raise NotFoundError (→ 404)."""
       container = request.state.dishka_container
       service: ReviewService = await container.get(ReviewService)
       return await service.get_review(review_id)


   ReviewById = Annotated[ReviewDTO, Depends(valid_review_id)]
   # Usage: async def get_review(review: ReviewById) -> ReviewResponse: ...
   ```

7. **API schema base models.** Request schemas inherit `StrictRequestModel` (unknown fields → 422); response schemas inherit `ResponseModel` (buildable from attributes). Both live in `src/core/schemas.py` — do not repeat `model_config` per schema.

## Scaling triggers

- **Split `src/core/types.py` per domain** (or restructure to per-domain packages, Netflix Dispatch / Polar style) when: more than 3 teams touch it, or it exceeds ~200 lines, or merge conflicts in it become routine.
- **Promote a type to a real value object** (frozen, behavior-carrying class) only when it accrues behavior (e.g. `Money` with currency arithmetic), per cosmicpython — not preemptively.

## Multi-error business validation

When a business flow must report multiple failures at once (bulk imports, multi-field forms) instead of failing on the first `AppError`, reach for Fowler's [Notification / result-object pattern](https://www.martinfowler.com/articles/replaceThrowWithNotification.html). No current use case in this boilerplate — documented here so the first implementer doesn't invent an ad-hoc variant.

## References

- [Pydantic: Types](https://docs.pydantic.dev/latest/concepts/types/) and [Validators](https://docs.pydantic.dev/latest/concepts/validators/)
- [Parse, don't validate — Alexis King](https://lexi-lambda.github.io/blog/2019/11/05/parse-dont-validate/)
- [Netflix Dispatch shared kernel (`models.py`/`enums.py`)](https://github.com/Netflix/dispatch/tree/main/src/dispatch)
- [cosmicpython ch.1 — Domain modeling](https://www.cosmicpython.com/book/chapter_01_domain_model)
- [Microsoft — Design validations in the domain model layer](https://learn.microsoft.com/en-us/dotnet/architecture/microservices/microservice-ddd-cqrs-patterns/domain-model-layer-validations)
- [Khorikov — Handling unique constraint violations](https://enterprisecraftsmanship.com/posts/handling-unique-constraint-violations/)
- [zhanymkanov/fastapi-best-practices](https://github.com/zhanymkanov/fastapi-best-practices)
- [Pydantic at the edge, dataclasses in the core](https://hrekov.com/blog/dataclasses-or-pydantic-basemodels)
- [Fowler — Replacing throwing exceptions with notification](https://www.martinfowler.com/articles/replaceThrowWithNotification.html)
````

- [ ] **Step 2: Commit**

```bash
git add docs/conventions/validation.md
git commit -m "docs(conventions): add validation ownership conventions"
```

### Task 6: Add `## Validation Ownership` section to CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Insert the section**

In `CLAUDE.md`, immediately after the "## Code Style" section's last bullet (`- Use type hints everywhere`) and **before** the `---` separator that precedes `# Service Layer DTO Pattern (CRUD Rule)`, insert:

```markdown
## Validation Ownership

Each validation rule has exactly ONE authoritative home — full rules in `docs/conventions/validation.md`:
- Format/shape rules → API schemas, via shared Annotated types in `src/core/types.py` (format-only module)
- Business rules (state, tenancy, workflow) → services, raising the `AppError` hierarchy from `src/core/exceptions.py`
- Uniqueness / cross-entity invariants → DB constraint + `src/repositories/error_mapping.py`; service pre-checks are UX only
- DTOs are validation-free containers — never add validators or business rules to DTOs
```

(Blank line before and after the inserted block.)

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): add validation ownership section"
```

### Task 7: Final verification

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest`
Expected: 85 passed, 0 failed (75 pre-existing tests unchanged and green — `tests/unit/test_types.py` and `tests/unit/test_user_schemas.py` prove the refactor preserved behavior)

- [ ] **Step 2: Confirm no private validator names remain**

Run: `grep -rnw "_max_72_bytes\|_check_complexity" src/ tests/`
Expected: no output, exit code 1 (the private names are gone; `-w` is required so the new public `validate_utf8_max_72_bytes` doesn't substring-match)

- [ ] **Step 3: Confirm no schema declares its own `model_config` for extra/from_attributes**

Run: `grep -rn "model_config" src/api/v1/schemas/`
Expected: no output, exit code 1 (all config now inherited from `src/core/schemas.py` bases)

## Out of scope (from the spec)

- Per-domain package restructure (Option C) and value-objects package (Option B) — scaling triggers documented instead.
- Scaffolding `src/api/v1/dependencies/` — convention documented only.
- Notification/result-object implementation — link-only.
- Any change to endpoint behavior, DTO shapes, or the error-handling stack.
