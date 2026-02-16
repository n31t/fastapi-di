# Paul Voice Backend

FastAPI backend for review management with multi-tenant support.

## Tech Stack
- Python 3.13, FastAPI, SQLAlchemy 2.0, PostgreSQL, Redis
- Dishka for dependency injection
- Alembic for migrations
- Pydantic for validation

## Architecture

Three-layer architecture with strict data flow:

```
Controller (schemas) → Service (DTOs) → Repository (models)
```

### Controllers (`src/api/v1/`)
- Handle HTTP requests/responses
- Use **schemas** for request/response validation
- Call services, never repositories directly

### Services (`src/services/`)
- Business logic and authorization
- Work only with **DTOs**
- Convert models to DTOs before returning

### Repositories (`src/repositories/`)
- Database operations only
- Work with **SQLAlchemy models**
- Return models to services

### Data Objects
- **Schemas** (`src/api/v1/schemas/`) - API request/response models
- **DTOs** (`src/dtos/`) - Internal data transfer between service layers
- **Models** (`src/models/`) - SQLAlchemy ORM models

## Project Structure
```
src/
├── api/v1/          # Controllers and schemas
├── services/        # Business logic
├── repositories/    # Data access
├── models/          # SQLAlchemy models
├── dtos/            # Data transfer objects
├── core/            # Config, security, logging
├── middlewares/     # Request middlewares
└── ioc/             # Dependency injection
```

## Commands
- Run: `uvicorn src.main:app --reload`
- Migrate: `alembic upgrade head`
- Test: `pytest`

## Code Style
- DO NOT WRITE LONG DOCSTRINGS. DO NOT ADD ARGS TO IT, MAKE IT SHORT AND SIMPLE
- Keep docstrings to 1-2 sentences max
- Use type hints everywhere

---

# Service Layer DTO Pattern (CRUD Rule)

## Core Principle
**All service functions for API endpoints MUST work with DTOs, not schemas or models directly.**

## Architecture Flow
```
API Endpoint (schemas) → Service (DTOs) → Repository (models)
```

## Rules

### 1. Service Function Parameters
- Services MUST accept DTOs as parameters, not Pydantic schemas
- Services MUST accept `AuthenticatedUserDTO` for user context
- Filter parameters MUST use FilterDTO classes (e.g., `ReviewFilterDTO`, `QrReviewsFilterDTO`)

**✅ Correct:**
```python
async def get_reviews(
    self,
    current_user: AuthenticatedUserDTO,
    filters: ReviewFilterDTO,
    relationships: Optional[ReviewRelationshipsDTO] = None
) -> ReviewListDTO:
```

**❌ Incorrect:**
```python
async def get_reviews(
    self,
    current_user: AuthenticatedUserDTO,
    filters: ReviewFilterParams,  # Schema, not DTO
    ...
) -> ReviewListDTO:
```

### 2. Service Function Return Types
- Services MUST return DTOs, never models or schemas directly
- Convert models to DTOs before returning

**✅ Correct:**
```python
async def get_reviews(...) -> ReviewListDTO:
    reviews = await self.repository.get_reviews_with_filters(...)
    review_dtos = [self._convert_review_to_dto(review) for review in reviews]
    return ReviewListDTO(reviews=review_dtos, total=total, ...)
```

**❌ Incorrect:**
```python
async def get_reviews(...) -> List[Review]:  # Model, not DTO
    return await self.repository.get_reviews_with_filters(...)
```

### 3. API Endpoint Responsibilities
- API endpoints convert schemas → DTOs before calling services
- API endpoints convert DTOs → response schemas after service calls
- Services never see schemas, only DTOs
- **All schema-to-DTO conversions MUST use `schema.model_dump()`**

**✅ Correct Pattern:**
```python
@router.get("/reviews")
async def get_reviews(
    filters: Annotated[ReviewFilterParams, Query()],  # Schema
    service: FromDishka[ReviewService]
):
    # Convert schema to DTO using model_dump()
    filter_dto = ReviewFilterDTO(**filters.model_dump())
    create_dto = CreateCustomerSuggestionDTO(**request.model_dump())
    
    # Service works with DTO
    result = await service.get_reviews(
        current_user=user,
        filters=filter_dto  # DTO, not schema
    )
    
    # Return DTO (FastAPI auto-converts to response schema)
    return result
```

**❌ Incorrect:**
```python
filter_dto = ReviewFilterDTO(**filters.dict())  # Old Pydantic v1 method
filter_dto = ReviewFilterDTO.parse_obj(filters.dict())  # Deprecated
```

### 4. DTO Locations
- **Filter DTOs**: `src/dtos/*_filter_dto.py` (e.g., `ReviewFilterDTO`, `QrReviewsFilterDTO`)
- **Data DTOs**: `src/dtos/*_dto.py` (e.g., `ReviewDTO`, `ReviewListDTO`)
- **Schemas**: `src/api/v1/schemas/` (API request/response models)

### 5. Conversion Methods
- Services should have private helper methods to convert models → DTOs
- Pattern: `_model_to_dto()` or `_convert_model_to_dto()`

**Example:**
```python
def _convert_review_to_dto(self, review: Review, relationships: Optional[ReviewRelationshipsDTO] = None) -> ReviewDTO:
    """Convert Review model to ReviewDTO."""
    # Conversion logic here
    return ReviewDTO(...)
```

### 6. Model to DTO Conversion in Services
- Services MUST use `DTO.model_validate(model, from_attributes=True)` for converting models to DTOs
- This applies to both single objects and lists
- Avoid manual dictionary construction or `DTO(**dict)` patterns
- Use clean mapping instead of raw mapping

**✅ Correct - Direct model_validate() (when model fields match DTO):**
```python
# Single object
qr_credentials_dto = QrReviewCredentialsDTO.model_validate(qr_credentials, from_attributes=True)
user_dto = UserDTO.model_validate(user, from_attributes=True)

# List of objects
city_dtos = [CityDTO.model_validate(city, from_attributes=True) for city in cities]
photo_dtos = [PhotoDTO.model_validate(photo, from_attributes=True) for photo in review.photos]
review_dtos = [QrReviewDTO.model_validate(review, from_attributes=True) for review in reviews]
```

**✅ Correct - model_validate() with dict (when DTO has extra fields or type conversions needed):**
```python
# When DTO has extra fields not on the model (e.g., relationship_type from join)
company_dict = {
    "id": company.id,
    "name": company.name,
    "slug": company.slug,
    "business_type": company.business_type,
    "brand_name": company.brand_name,
    "priority": company.priority,
    "is_active": company.is_active,
    "relationship_type": rel_type  # Extra field from join
}
company_dto = CompanyDTO.model_validate(company_dict)

# When type conversions are needed (enum to string, datetime to ISO string)
location_dict = {
    "id": branch.id,
    "name": branch.name,
    "city_id": branch.city_id,
    "city_name": city_name,  # Extra field
    "platform": ext_id.platform.value,  # Enum to string
    "created_at": ext_id.created_at.isoformat() if ext_id.created_at else "",  # Datetime to string
}
location_dto = QrLocationDTO.model_validate(location_dict)

# When using computed fields - validate first, then set computed fields
user_dto = UserDTO.model_validate(user, from_attributes=True)
user_dto.role_name = user.role.name if user.role else "user"  # Computed field
user_dto.company_ids = company_ids  # Computed field
```

**✅ Correct - model_validate() with dict from query results:**
```python
# When repository returns tuples/rows instead of models
branch_dtos = [
    NearestBranchDTO.model_validate({
        "company_id": row.company_id,
        "company_name": row.company_name,
        "branch_id": row.branch_id,
        "branch_name": row.branch_name,
        "longitude": float(row.longitude) if row.longitude else None,
        "latitude": float(row.latitude) if row.latitude else None,
        "distance_km": float(row.distance) if row.distance else None
    })
    for row in competitors
]

# When repository returns dictionaries
data = [
    ClicksTimeSeriesPointDTO.model_validate(p)
    for p in raw  # raw is a list of dicts
]
```

**❌ Incorrect:**
```python
# Raw mapping - avoid
city_dtos = [CityDTO(**city.__dict__) for city in cities]
city_dtos = [CityDTO(id=city.id, name=city.name, ...) for city in cities]  # Manual construction
return ReviewDTO(**data)  # Dictionary unpacking

# Manual construction when model_validate() can be used
company_dto = CompanyDTO(
    id=company.id,
    name=company.name,
    slug=company.slug,
    # ... all fields manually
)
```

## Violations to Avoid
1. ❌ Service accepting schema types instead of DTOs
2. ❌ Service returning models instead of DTOs
3. ❌ Service directly using Pydantic schemas
4. ❌ API endpoint passing schemas directly to services
5. ❌ Missing DTO conversion in service methods
6. ❌ Using raw dictionary unpacking (`DTO(**dict)`) instead of `model_validate()` in services
7. ❌ Manual field-by-field DTO construction in services (use `model_validate()` instead)
8. ❌ Using `dict()` or `parse_obj()` instead of `model_dump()` in controllers
9. ❌ Calling `model_validate()` on dataclasses (dataclasses don't have `model_validate()` - convert to Pydantic model or construct manually)
10. ❌ Using `model_validate()` when DTO has required fields not on the model without creating a dict first
