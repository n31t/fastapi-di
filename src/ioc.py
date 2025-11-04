"""
Dependency injection container configuration using Dishka.

This module defines the AppProvider that manages all application dependencies
and their lifecycles using the Dishka framework.
"""

from typing import AsyncIterable

from dishka import Provider, Scope, from_context, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, AsyncEngine, create_async_engine

from src.core.config import Config
from src.repositories.auth_repository import AuthRepository
from src.services.auth_service import AuthService


class AppProvider(Provider):
    """
    Main dependency injection provider for the application.

    Manages dependencies with two scopes:
    - APP: Singleton dependencies (engine, session maker, config)
    - REQUEST: Per-request dependencies (session, repositories, services)
    """

    # Config injected from application context at startup
    config = from_context(provides=Config, scope=Scope.APP)

    @provide(scope=Scope.APP)
    def get_engine(self, config: Config) -> AsyncEngine:
        """
        Create and provide SQLAlchemy async engine.

        Args:
            config: Application configuration

        Returns:
            AsyncEngine configured with connection pooling
        """
        return create_async_engine(
            config.db_url,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_timeout=20,
            max_overflow=0,
        )

    @provide(scope=Scope.APP)
    def get_session_maker(self, engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
        """
        Create and provide session maker factory.

        Args:
            engine: SQLAlchemy async engine

        Returns:
            async_sessionmaker configured for the application
        """
        return async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

    @provide(scope=Scope.REQUEST)
    async def get_session(
        self, session_maker: async_sessionmaker[AsyncSession]
    ) -> AsyncIterable[AsyncSession]:
        """
        Provide database session for the current request.

        Uses async context manager to ensure proper cleanup.
        Automatically commits on success, rolls back on error.

        Args:
            session_maker: Session factory

        Yields:
            AsyncSession for the current request
        """
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    @provide(scope=Scope.REQUEST)
    def get_auth_repository(self, session: AsyncSession) -> AuthRepository:
        """
        Provide AuthRepository for the current request.

        Args:
            session: Database session

        Returns:
            AuthRepository instance
        """
        return AuthRepository(session)

    @provide(scope=Scope.REQUEST)
    def get_auth_service(
        self, auth_repository: AuthRepository, config: Config
    ) -> AuthService:
        """
        Provide AuthService for the current request.

        Args:
            auth_repository: Authentication repository
            config: Application configuration

        Returns:
            AuthService instance
        """
        return AuthService(auth_repository, config)
