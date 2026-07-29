"""
Authentication repository for database operations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.auth import User, RefreshToken
from src.repositories.error_mapping import map_integrity_error


class AuthRepository:
    """Repository for authentication-related database operations."""

    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get a user by username."""
        result = await self.session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get a user by email."""
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get a user by ID."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def create_user(self, username: str, email: str, hashed_password: str) -> User:
        """Create a new user; raises a ConflictError subclass on uniqueness violation."""
        user = User(
            username=username,
            email=email,
            hashed_password=hashed_password,
            is_active=True
        )

        self.session.add(user)
        try:
            # flush() inside the try: the commit happens later in DI teardown,
            # so the constraint violation must surface within the request scope.
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise map_integrity_error(exc) from exc
        await self.session.refresh(user)
        return user

    async def create_refresh_token(
        self,
        user_id: str,
        token: str,
        expires_days: int,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> RefreshToken:
        """Create a new refresh token in the database."""
        refresh_token = RefreshToken(
            token=token,
            user_id=user_id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=expires_days),
            user_agent=user_agent,
            ip_address=ip_address,
            is_revoked=False
        )

        self.session.add(refresh_token)
        await self.session.flush()
        await self.session.refresh(refresh_token)
        return refresh_token

    async def get_refresh_token(self, token: str) -> Optional[RefreshToken]:
        """Get a refresh token by token string."""
        result = await self.session.execute(
            select(RefreshToken).where(RefreshToken.token == token)
        )
        return result.scalar_one_or_none()

    async def revoke_refresh_token(self, token: str) -> None:
        """Revoke a refresh token by marking it as revoked."""
        refresh_token = await self.get_refresh_token(token)
        if refresh_token:
            refresh_token.is_revoked = True
            await self.session.flush()
