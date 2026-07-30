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
