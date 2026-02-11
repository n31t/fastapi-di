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
