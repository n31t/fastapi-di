"""
Custom exception handlers for consistent API error responses.

This module provides:
1. Global FastAPI exception handlers (register with app)
2. Route decorators for fine-grained error handling

"""

from functools import wraps
from typing import Callable, Any
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import ValidationError

from src.core.logging import get_logger

logger = get_logger(__name__)

# Constants for sanitized error messages
VALIDATION_ERROR_MSG = "Invalid data provided"
INVALID_REQUEST_MSG = "Invalid request"
INTERNAL_ERROR_MSG = "Internal server error"


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    Handle HTTPException with standardized error response.

    Returns sanitized error message - does not expose internal error details.
    """
    detail = str(exc.detail) if exc.detail else "An error occurred"
    
    # Sanitize error messages - don't expose internal validation details
    detail_lower = detail.lower()
    if "validation error" in detail_lower or "pydantic" in detail_lower:
        sanitized_message = VALIDATION_ERROR_MSG
    else:
        # For other errors, use the detail but limit exposure of internal details
        sanitized_message = detail
    
    logger.error(
        "http_exception",
        path=request.url.path,
        method=request.method,
        status_code=exc.status_code,
        detail=exc.detail
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "code": exc.status_code,
            "message": sanitized_message
        }
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Handle validation errors with standardized error response.
    """
    logger.error(
        "validation_exception",
        path=request.url.path,
        method=request.method,
        errors=exc.errors()
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "status": "error",
            "code": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "message": "Invalid request data"
        }
    )


async def pydantic_validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """
    Handle Pydantic model validation errors (internal validation, not request validation).
    
    Returns sanitized error message - does not expose internal validation details.
    """
    logger.error(
        "pydantic_validation_error",
        path=request.url.path,
        method=request.method,
        errors=str(exc),
        exc_info=True
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "error",
            "code": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "message": INTERNAL_ERROR_MSG
        }
    )


async def value_error_exception_handler(request: Request, exc: ValueError) -> JSONResponse:
    """
    Handle ValueError with standardized error response.
    """
    error_message = str(exc)
    
    # Sanitize error messages - don't expose internal validation details
    error_lower = error_message.lower()
    if "validation error" in error_lower or "pydantic" in error_lower:
        sanitized_message = VALIDATION_ERROR_MSG
    else:
        # For other ValueErrors, use a generic message
        sanitized_message = INVALID_REQUEST_MSG
    
    logger.error(
        "value_error_exception",
        path=request.url.path,
        method=request.method,
        error=error_message  # Log full error internally
    )

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "status": "error",
            "code": status.HTTP_400_BAD_REQUEST,
            "message": sanitized_message
        }
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle unexpected exceptions with standardized error response.

    Returns 500 Internal Server Error.
    """
    logger.error(
        "unexpected_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "error",
            "code": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "message": INTERNAL_ERROR_MSG
        }
    )


def register_exception_handlers(app):
    """
    Register all custom exception handlers with the FastAPI app.
    """
    # Standard FastAPI exceptions
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    
    # Pydantic model validation errors (internal validation, not request validation)
    app.add_exception_handler(ValidationError, pydantic_validation_error_handler)
    
    # Standard Python exceptions
    app.add_exception_handler(ValueError, value_error_exception_handler)
    
    # Catch-all for any other exceptions
    app.add_exception_handler(Exception, generic_exception_handler)


# ============================================================================
# Route Decorators for Fine-Grained Error Handling
# ============================================================================

def handle_service_errors(func: Callable) -> Callable:
    """
    Decorator for handling service-layer exceptions in individual routes.

    This decorator converts application exceptions to HTTP exceptions,
    providing more control than global handlers. Use this when you need
    route-specific error handling or when global handlers are not suitable.
    """
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)

        except ValidationError as e:
            # Pydantic model validation error - don't expose internal details
            logger.error(
                "route_validation_error",
                error=str(e),
                route=func.__name__,
                exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=INTERNAL_ERROR_MSG
            )
        
        except ValueError as e:
            error_message = str(e)
            # Sanitize error messages - don't expose internal validation details
            error_lower = error_message.lower()
            if "validation error" in error_lower or "pydantic" in error_lower:
                sanitized_message = VALIDATION_ERROR_MSG
            else:
                sanitized_message = INVALID_REQUEST_MSG
            
            logger.warning(
                "route_value_error",
                error=error_message,  # Log full error internally
                route=func.__name__
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=sanitized_message
            )

        except Exception as e:
            # Unexpected errors - log with full traceback
            logger.error(
                "route_unexpected_error",
                error=str(e),
                error_type=type(e).__name__,
                route=func.__name__,
                exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=INTERNAL_ERROR_MSG
            )

    return wrapper


def handle_auth_errors(func: Callable) -> Callable:
    """
    Specialized decorator for authentication routes.
    """
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)

        except ValueError as e:
            logger.warning(
                "auth_route_invalid_input",
                error=str(e),
                route=func.__name__
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e) or "Invalid credentials provided"
            )

        except Exception as e:
            logger.error(
                "auth_route_error",
                error=str(e),
                error_type=type(e).__name__,
                route=func.__name__,
                exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication error"
            )

    return wrapper
