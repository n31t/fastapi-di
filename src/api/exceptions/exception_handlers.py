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
