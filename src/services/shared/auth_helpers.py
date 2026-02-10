"""
Authentication helper functions for FastAPI endpoints with DishkaRoute.

This module provides reusable authentication logic for endpoints using DishkaRoute.
Since DishkaRoute doesn't support Depends() with FromDishka parameters, these are
helper functions (not FastAPI dependencies) that can be called manually in endpoints.
"""

from typing import TYPE_CHECKING, Optional

import jwt
from fastapi import HTTPException, Request, status

from src.core.config import Config
from src.core.logging import get_logger
from src.core.security import decode_access_token
from src.dtos.user_dto import AuthenticatedUserDTO
from src.models.auth import User as UserModel
from src.repositories.auth_repository import AuthRepository

if TYPE_CHECKING:
    from dishka import AsyncContainer

logger = get_logger(__name__)

async def get_authenticated_user_dependency(
    request: Request
) -> AuthenticatedUserDTO:
    """FastAPI dependency that authenticates user from cookies and returns DTO with context."""

    # Get Dishka container from request state
    container: Optional[AsyncContainer] = getattr(request.state, "dishka_container", None)

    if not container:
        logger.error("dishka_container_not_found", has_state=hasattr(request, "state"))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error: Dishka container not found"
        )

    try:
        config: Config = await container.get(Config)

        token = request.cookies.get("access_token")

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            # Decode and validate the JWT token
            payload = decode_access_token(token, config)

            user_id: str = payload.get("sub")

            if user_id is None:
                logger.warning("token_missing_user_id")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        except jwt.ExpiredSignatureError:
            logger.warning("token_expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError as e:
            logger.warning("invalid_token", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Get AuthRepository from container
        auth_repository: AuthRepository = await container.get(AuthRepository)

        # Fetch user by ID
        user_model: UserModel = await auth_repository.get_user_by_id(user_id)

        if user_model is None:
            logger.warning("user_not_found", user_id=user_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check if user is active
        if not user_model.is_active:
            logger.warning("user_inactive", user_id=user_model.id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Inactive user account"
            )

        # Create DTO from ORM model
        user_dto = AuthenticatedUserDTO(
            id=user_model.id,
            username=user_model.username,
            email=user_model.email,
            is_active=user_model.is_active,
            created_at=user_model.created_at,
            updated_at=user_model.updated_at,
        )

        # Store ORM model in Dishka context (for backward compatibility if needed)
        container.context[UserModel] = user_model
        # Store DTO in context (preferred for services)
        container.context[AuthenticatedUserDTO] = user_dto

        # Store in request state for logging and middleware access
        request.state.user_id = user_model.id

        logger.debug(
            "user_authenticated",
            user_id=user_dto.id,
            username=user_dto.username,
        )

        return user_dto

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error("authentication_error", error=str(e), error_type=type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error"
        )
