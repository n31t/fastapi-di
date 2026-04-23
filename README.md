# FastAPI DI Template

A FastAPI backend template with cookie-based JWT auth, Dishka dependency injection, and a strict layered architecture (Controller → Service → Repository).

## Tech Stack

- **Python 3.13** with [uv](https://docs.astral.sh/uv/) for dependency management
- **FastAPI** for the HTTP layer
- **Dishka** for dependency injection
- **SQLAlchemy 2.0** (async) + **asyncpg** + **PostgreSQL**
- **Alembic** for migrations
- **Pydantic v2** for schemas/DTOs, **pydantic-settings** for config
- **PyJWT** + **bcrypt** for auth
- **structlog** / **python-json-logger** for structured logging

## Architecture

Three layers with a strict data flow. No layer skipping.

```
Controller (schemas) → Service (DTOs) → Repository (models)
```

- **Controllers** (`src/api/v1/`) — HTTP in/out. Validate with Pydantic schemas, call services.
- **Services** (`src/services/`) — business logic and authorization. Accept and return DTOs only.
- **Repositories** (`src/repositories/`) — database access. Work with SQLAlchemy models.

Data object locations:

- Schemas — `src/api/v1/schemas/`
- DTOs — `src/dtos/`
- Models — `src/models/`

Conversion rules live in `CLAUDE.md`.

## Project Structure

```
src/
├── api/
│   ├── v1/              # Versioned endpoints and request/response schemas
│   ├── exceptions/      # Exception handlers and decorators
│   └── middlewares/     # Request/response middleware
├── core/                # Config, security, logging
├── db/                  # Database engine and session setup
├── dtos/                # Internal DTOs
├── enums/               # Shared enums
├── ioc/                 # Dishka providers (DB, repositories, services)
├── models/              # SQLAlchemy models (ULID-based PKs + timestamps)
├── repositories/        # Data access layer
├── services/            # Business logic
└── main.py              # FastAPI app factory + lifespan
alembic/                 # Migrations
tests/                   # pytest suite
```

## Getting Started

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
```

Required variables:

```env
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost         # use "db" when running via docker-compose
DB_PORT=5432
DB_NAME=nn

SECRET_KEY=change-me      # see below
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
```

Generate a strong `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Run migrations

```bash
make migrate-upgrade
# or: uv run alembic upgrade head
```

### 4. Start the dev server

```bash
make dev-backend
# serves on http://localhost:3838 with --reload
```

Production-style run:

```bash
make prod-backend
# serves on http://0.0.0.0:8000
```

## Docker

A `docker-compose.yml` is provided for Postgres + the app. Current status: **only local development via `uv` + `make dev-backend` is verified to work**. The Docker/compose flows and deployed preview environment are not wired up end-to-end yet — use the local flow above.

If you want to experiment with the compose file:

```bash
docker compose up --build
```

## Make Targets

| Target              | Description                                |
|---------------------|--------------------------------------------|
| `dev-backend`       | Run uvicorn with `--reload` on port 3838   |
| `prod-backend`      | Run uvicorn on `0.0.0.0:8000`              |
| `migrate msg="..."` | Autogenerate a new Alembic revision        |
| `migrate-upgrade`   | Apply all pending migrations               |
| `migrate-downgrade` | Revert the last migration                  |
| `migrate-current`   | Show the current revision                  |
| `migrate-history`   | Show the full migration history            |

## API

Base path: `/api/v1`

### Authentication (cookie-based)

Access and refresh tokens are set as `HttpOnly`, `Secure`, `SameSite=None` cookies. The client does not handle tokens directly.

| Method | Path                     | Description                                    |
|--------|--------------------------|------------------------------------------------|
| POST   | `/api/v1/auth/register`  | Register a user, set auth cookies              |
| POST   | `/api/v1/auth/login`     | Log in, set auth cookies                       |
| POST   | `/api/v1/auth/refresh`   | Rotate tokens using the `refresh_token` cookie |
| POST   | `/api/v1/auth/logout`    | Clear auth cookies                             |
| GET    | `/api/v1/auth/me`        | Current authenticated user                     |
| GET    | `/api/v1/auth/profile`   | Current user profile                           |

### Health

| Method | Path            | Description                          |
|--------|-----------------|--------------------------------------|
| GET    | `/health`       | Liveness                             |
| GET    | `/health/ready` | Readiness (verifies DB connectivity) |

### Docs

- Swagger UI — `/docs`
- ReDoc — `/redoc`

### Example: login

```bash
curl -i -X POST http://localhost:3838/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{"username": "alice", "password": "SecurePass123"}'
```

### Example: authenticated request

```bash
curl http://localhost:3838/api/v1/auth/me -b cookies.txt
```

## Testing

```bash
uv run pytest
```

## Conventions

- Services accept and return DTOs; never schemas or raw models.
- Controllers convert schemas → DTOs with `schema.model_dump()`.
- Services convert models → DTOs with `DTO.model_validate(model, from_attributes=True)`.
- Keep docstrings short (1–2 sentences), type hints everywhere.

Full rules are in `CLAUDE.md`.

## Status

- Local dev with `uv` + `make dev-backend`: working.
- Preview/deployed environment: not currently working — do not rely on a hosted preview URL.
