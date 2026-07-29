"""
Authentication helper functions for FastAPI endpoints with DishkaRoute.

Since DishkaRoute doesn't support Depends() with FromDishka parameters, these are
helper functions (not FastAPI dependencies) that can be called manually in endpoints.
"""

from typing import TYPE_CHECKING, Optional

import jwt
from fastapi import Request

from src.core.config import Config
from src.core.exceptions import (
    AppError,
    InactiveUserError,
    InvalidTokenError,
    TokenExpiredError,
)
from src.core.logging import get_logger
from src.core.security import decode_access_token
from src.dtos.user_dto import AuthenticatedUserDTO
from src.models.auth import User as UserModel
from src.repositories.auth_repository import AuthRepository

if TYPE_CHECKING:
    from dishka import AsyncContainer

logger = get_logger(__name__)


async def get_authenticated_user_dependency(request: Request) -> AuthenticatedUserDTO:
    """Authenticate the user from the access-token cookie and return a DTO."""
    container: Optional["AsyncContainer"] = getattr(request.state, "dishka_container", None)

    if not container:
        logger.error("dishka_container_not_found", has_state=hasattr(request, "state"))
        raise AppError("Authentication service unavailable")

    try:
        config: Config = await container.get(Config)

        token = request.cookies.get("access_token")
        if not token:
            raise InvalidTokenError("Not authenticated")

        try:
            payload = decode_access_token(token, config)
            user_id: Optional[str] = payload.get("sub")
            if user_id is None:
                logger.warning("token_missing_user_id")
                raise InvalidTokenError("Invalid authentication credentials")
        except jwt.ExpiredSignatureError:
            logger.warning("token_expired")
            raise TokenExpiredError("Token has expired")
        except jwt.InvalidTokenError as e:
            logger.warning("invalid_token", error=str(e))
            raise InvalidTokenError("Invalid authentication credentials")

        auth_repository: AuthRepository = await container.get(AuthRepository)
        user_model: Optional[UserModel] = await auth_repository.get_user_by_id(user_id)

        if user_model is None:
            # 401, not 404: an auth endpoint must not leak account existence
            logger.warning("user_not_found", user_id=user_id)
            raise InvalidTokenError("Invalid authentication credentials")

        if not user_model.is_active:
            logger.warning("user_inactive", user_id=user_model.id)
            raise InactiveUserError("Inactive user account")

        user_dto = AuthenticatedUserDTO(
            id=user_model.id,
            username=user_model.username,
            email=user_model.email,
            is_active=user_model.is_active,
            created_at=user_model.created_at,
            updated_at=user_model.updated_at,
        )

        container.context[UserModel] = user_model
        container.context[AuthenticatedUserDTO] = user_dto
        request.state.user_id = user_model.id

        logger.debug("user_authenticated", user_id=user_dto.id, username=user_dto.username)
        return user_dto

    except AppError:
        raise  # domain errors pass through; the catch-all below must never see them
    except Exception as e:
        logger.error("authentication_error", error=str(e), error_type=type(e).__name__, exc_info=True)
        raise AppError("Authentication failed") from e
