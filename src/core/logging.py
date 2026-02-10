"""
Structured logging configuration using structlog.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import structlog
from structlog.types import FilteringBoundLogger

# Context variables for request correlation
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_ctx: ContextVar[str | None] = ContextVar("tenant_id", default=None)
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)

# Service context (set once at startup)
_service_name: str = "unknown"
_service_version: str = "0.0.0"
_environment: str = "development"


def set_service_context(name: str, version: str, environment: str) -> None:
    """Set service context for all log entries."""
    global _service_name, _service_version, _environment
    _service_name = name
    _service_version = version
    _environment = environment


def add_service_context(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add service identification to all log entries."""
    event_dict["service"] = _service_name
    event_dict["version"] = _service_version
    event_dict["environment"] = _environment
    return event_dict


def add_request_context(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add request correlation context to log entries."""
    request_id = request_id_ctx.get()
    tenant_id = tenant_id_ctx.get()
    user_id = user_id_ctx.get()

    if request_id:
        event_dict["request_id"] = request_id
    if tenant_id:
        event_dict["tenant_id"] = tenant_id
    if user_id:
        event_dict["user_id"] = user_id

    return event_dict


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    json_logs: bool = True
) -> None:
    """Configure structured logging."""
    if log_file:
        Path("logs").mkdir(exist_ok=True)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper()),
    )

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        add_service_context,
        add_request_context,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if json_logs:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name or __name__)


def generate_request_id() -> str:
    """Generate a unique request ID for correlation."""
    return str(uuid.uuid4())


def set_request_context(
    request_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None
) -> None:
    """Set request context for logging correlation."""
    if request_id:
        request_id_ctx.set(request_id)
    if tenant_id:
        tenant_id_ctx.set(tenant_id)
    if user_id:
        user_id_ctx.set(user_id)


def clear_request_context() -> None:
    """Clear request context."""
    request_id_ctx.set(None)
    tenant_id_ctx.set(None)
    user_id_ctx.set(None)


def bind_context(**kwargs: Any) -> None:
    """Bind context variables for current log entries."""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all bound context variables."""
    structlog.contextvars.clear_contextvars()


logger = get_logger(__name__)
