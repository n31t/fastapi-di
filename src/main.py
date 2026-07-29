"""
Main FastAPI application with logging, monitoring, and middleware setup.
"""
from contextlib import asynccontextmanager

from asgi_correlation_id import CorrelationIdMiddleware
from dishka import AsyncContainer, make_async_container
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from dishka.integrations import fastapi as fastapi_integration
from fastapi import APIRouter, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine

from src.api.middlewares.response_middleware import StandardResponseMiddleware
from src.api.v1.auth import router as auth_router
from src.api.exceptions.exception_handlers import register_exception_handlers
from src.core.config import config, Config
from src.core.logging import get_logger, setup_logging
from src.db.database import check_db_connection
from src.ioc import AppProvider

setup_logging(
    level="DEBUG" if config.debug else "INFO",
    json_logs=not config.debug,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    """
    logger.info("application_startup", app_name=config.app_name)

    try:
        async with app.state.dishka_container() as request_container:
            engine = await request_container.get(AsyncEngine)
            is_connected = await check_db_connection(engine)

            if not is_connected:
                logger.error("startup_failed_database_unreachable")
                raise RuntimeError("Database connection failed at startup")

            logger.info("startup_database_connected")
    except Exception as e:
        logger.error(
            "startup_failed",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True
        )
        raise

    yield

    logger.info("application_shutdown", app_name=config.app_name)


health_router = APIRouter(route_class=DishkaRoute, tags=["Health"])


@health_router.get("/health")
async def health_check():
    """
    Basic liveness check endpoint.
    """
    return {"status": "healthy", "service": config.app_name}


@health_router.get("/health/ready")
async def readiness_check(engine: FromDishka[AsyncEngine]):
    """
    Readiness check endpoint with database connectivity verification.
    """
    is_db_connected = await check_db_connection(engine)

    if not is_db_connected:
        logger.error("readiness_check_failed_database_unreachable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed"
        )

    return {
        "status": "ready",
        "service": config.app_name,
        "database": "connected"
    }


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


app = create_app()