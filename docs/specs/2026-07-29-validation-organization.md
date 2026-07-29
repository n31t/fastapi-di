# Validation Organization for a Scalable Boilerplate

**Date:** 2026-07-29
**Status:** Draft
**Repo purpose:** Team boilerplate — the structure defined here is the pattern every service cloned from this repo should follow, and it must stay clean at 20+ entities.

## Problem

Validation logic currently works but its organization is implicit. Rules live in four places — Pydantic schemas (format), `src/core/types.py` (shared `Annotated` types), services (business checks like duplicate username), and DB constraints (unique indexes mapped via `src/repositories/error_mapping.py`) — with no written convention saying which layer owns which kind of rule, no reusable base models (each schema repeats `model_config`), and validator functions coupled to the types module (private names, not reusable from workers/CLI).

For a boilerplate, the missing piece is the **documented, enforced pattern**, plus a small kernel restructure that demonstrates it.

## Research Summary

Web research across Netflix Dispatch, Polar, cosmicpython, Pydantic v2 docs, zhanymkanov/fastapi-best-practices, Fowler, Khorikov, and Microsoft DDD guidance converges on **defense in depth with exactly one authoritative home per rule**:

| Kind of rule | Authoritative home | Key reference |
|---|---|---|
| Syntactic / format / shape | API schemas, via shared `Annotated` types | [Pydantic types](https://docs.pydantic.dev/latest/concepts/types/), [Parse, don't validate](https://lexi-lambda.github.io/blog/2019/11/05/parse-dont-validate/) |
| Reusable field rules | Shared `Annotated` types module, format-only | [Pydantic validators](https://docs.pydantic.dev/latest/concepts/validators/), [Dispatch shared kernel (`models.py`/`enums.py`)](https://github.com/Netflix/dispatch/tree/main/src/dispatch) |
| Business rules (state, tenancy, workflow) | Services, raising domain exceptions | [cosmicpython ch.1](https://www.cosmicpython.com/book/chapter_01_domain_model), [Microsoft DDD validations](https://learn.microsoft.com/en-us/dotnet/architecture/microservices/microservice-ddd-cqrs-patterns/domain-model-layer-validations) |
| Uniqueness / cross-entity invariants | **DB constraint is authoritative**; `IntegrityError` → domain `ConflictError` mapping; service pre-check optional, UX only | [Khorikov](https://enterprisecraftsmanship.com/posts/handling-unique-constraint-violations/) |
| DB-backed request checks (existence, ownership) | FastAPI dependencies | [fastapi-best-practices](https://github.com/zhanymkanov/fastapi-best-practices) |
| DTOs | Validation-free containers — never business validators (drift vector) | ["Pydantic at the edge, dataclasses in the core"](https://hrekov.com/blog/dataclasses-or-pydantic-basemodels) |

Organizational options evaluated:

- **A — single shared `core/types.py`** (current state): zero duplication but becomes a dumping ground at scale.
- **B — DDD value-objects package**: strongest guarantees, but heavy ceremony (mapping at every boundary); cosmicpython itself warns it isn't warranted for CRUD-heavy apps. Deferred.
- **C — per-domain packages** (`src/auth/`, `src/reviews/` — Dispatch/Polar layout): best organizational scaling, but a full restructure away from the current layer-first layout, and shared formats drift without a kernel. Deferred; this spec encodes the trigger for moving there.
- **D — hybrid: small shared kernel + layered ownership** ✅ chosen. What Dispatch and Polar actually converge on (domain packages *plus* a small `types.py`/`kit/` kernel). Incremental from the current layout and forward-compatible with C.

## Design (Approach D)

### 1. Kernel restructure — `src/core/`

**Create `src/core/validators.py`** — plain validator functions, public names, zero Pydantic-type coupling so workers/CLI/service code can import them directly:

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

**Slim `src/core/types.py`** to `Annotated` definitions only, importing from `core.validators`:

```python
"""Shared Annotated types for boundary schema validation. Format rules ONLY —
anything needing DB or tenant context is a dependency or service rule, not a type."""
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

from src.core.validators import validate_password_complexity, validate_utf8_max_72_bytes

Username = Annotated[
    str,
    StringConstraints(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$", strip_whitespace=True),
]

Password = Annotated[
    str,
    Field(min_length=8, max_length=72),
    AfterValidator(validate_utf8_max_72_bytes),
    AfterValidator(validate_password_complexity),
]
```

**Create `src/core/schemas.py`** — two base models every API schema inherits, replacing per-schema `model_config` duplication:

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

`src/core/exceptions.py` is unchanged.

### 2. Layer-ownership conventions doc — the main boilerplate deliverable

**Create `docs/conventions/validation.md`** containing:

1. The one-home-per-rule table (from Research Summary above), with repo-relative pointers (`src/core/types.py`, `src/services/`, `src/repositories/error_mapping.py`, `src/models/`).
2. **Rules:**
   - Format rules live in schemas via shared `Annotated` types; add a new shared type when ≥2 schemas need the same rule, **or** when the rule is security-critical / defines the canonical format for a domain-wide field (as with `Password` and `Username` today); otherwise keep it inline in the schema.
   - `core/types.py` stays format-only. If a "type" needs DB, request, or tenant context, it is a FastAPI dependency or a service rule.
   - Business rules live in services and raise the `AppError` hierarchy from `src/core/exceptions.py`. Never in schemas, never in DTOs.
   - DTOs are validation-free containers — in this boilerplate they are stdlib dataclasses (see `src/dtos/user_dto.py`), constructed by services from models. Adding validation or business rules to DTOs is the primary drift vector and is forbidden. (Whether to migrate DTOs to Pydantic `BaseModel` — enabling `model_validate(model, from_attributes=True)` conversion per CLAUDE.md's service-layer pattern — is an open question the doc flags as future work; this spec changes nothing about DTOs.)
   - Every uniqueness/cross-entity invariant gets a DB constraint plus an entry in `_CONSTRAINT_MAP` (`src/repositories/error_mapping.py`). A service pre-check is optional and purely for UX; the constraint is the enforcement (races).
   - DB-backed request checks (existence, ownership) go in FastAPI dependencies under `src/api/v1/dependencies/` — with the worked example below included verbatim *in the doc*. The package is created when the first path-ID endpoint appears, not scaffolded empty now.

   Worked example for the conventions doc (illustrative — no `Review` entity exists yet; with Dishka, dependencies resolve services from the request-scoped container):

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
3. **Scaling triggers (when to evolve the structure):**
   - Split `core/types.py` per domain (or restructure to per-domain packages, Dispatch/Polar style) when: >3 teams touch it, or it exceeds ~200 lines, or merge conflicts become routine.
   - Promote a type to a real value object (frozen, behavior-carrying) only when it accrues behavior (e.g. `Money`), per cosmicpython.
4. **Multi-error business validation:** a short subsection naming Fowler's [Notification/result-object pattern](https://www.martinfowler.com/articles/replaceThrowWithNotification.html) as the approach to reach for when a business flow must report multiple failures at once (bulk imports, multi-field forms) instead of failing on the first `AppError`. Documented with a link only — no current use case, no implementation.
5. References list (URLs from Research Summary).

**Update `CLAUDE.md`** — insert the following section immediately after the "Code Style" section (i.e. before the "Service Layer DTO Pattern (CRUD Rule)" section), verbatim:

```markdown
## Validation Ownership

Each validation rule has exactly ONE authoritative home — full rules in `docs/conventions/validation.md`:
- Format/shape rules → API schemas, via shared Annotated types in `src/core/types.py` (format-only module)
- Business rules (state, tenancy, workflow) → services, raising the `AppError` hierarchy from `src/core/exceptions.py`
- Uniqueness / cross-entity invariants → DB constraint + `src/repositories/error_mapping.py`; service pre-checks are UX only
- DTOs are validation-free containers — never add validators or business rules to DTOs
```

### 3. Migration of existing schemas

`src/api/v1/schemas/user.py`:
- `UserRegister(StrictRequestModel)`, `UserLogin(StrictRequestModel)` — drop their local `model_config`.
- `UserResponse(ResponseModel)` — drop its local `model_config`.
- Field definitions unchanged. `UserLogin` stays deliberately loose (wrong creds → 401, never 422).

No endpoint behavior changes. No changes to services, repositories, DTOs, or exception handlers.

## Testing (unit only — approved)

- `tests/unit/test_validators.py` — direct tests of `validate_utf8_max_72_bytes` (72-byte ASCII passes; multibyte UTF-8 over 72 bytes fails; boundary) and `validate_password_complexity` (missing upper/lower/digit each fail; valid passes).
- `tests/unit/test_base_schemas.py` — `StrictRequestModel` subclass rejects unknown fields; `ResponseModel` subclass builds from an object via attributes.
- Existing suite (75 tests: 43 unit + 22 integration + 10 db) must stay green unchanged — `tests/unit/test_types.py` and `test_user_schemas.py` in particular prove the refactor preserved behavior.

## Out of Scope

- Per-domain package restructure (Option C) — trigger conditions documented instead.
- Value-objects package (Option B) — deferred until a concept accrues behavior.
- Scaffolding `src/api/v1/dependencies/` — documented convention only; no current path-ID endpoint.
- Notification/result-object pattern for multi-error business validation (Fowler) — mentioned in the conventions doc as the pattern to reach for on bulk imports/multi-field flows; no current use case.
- Any change to endpoint behavior, DTO shapes, or the error-handling stack shipped in `feature/error-handling-validation`.
