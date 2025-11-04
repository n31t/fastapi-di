"""
Authentication API endpoints.

This module provides endpoints for user registration, login, token refresh,
and other authentication-related operations.
"""

from typing import Annotated

import jwt
from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.models.auth import UserRegister, UserLogin, TokenResponse, UserResponse
from src.services.auth_service import AuthService
from src.repositories.auth_repository import AuthRepository
from src.core.config import Config
from src.core.security import decode_access_token
from src.core.logging import get_logger
from src.schemas.user import User

logger = get_logger(__name__)

router = APIRouter(
    prefix="/auth",
    route_class=DishkaRoute,
)

# HTTPBearer scheme for extracting tokens from Authorization header
security = HTTPBearer()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserRegister,
    request: Request,
    service: FromDishka[AuthService]
):
    """
    Register a new user.

    Creates a new user account and returns access and refresh tokens.

    Args:
        user_data: User registration data (username, email, password)
        request: FastAPI request object for extracting metadata
        service: AuthService dependency

    Returns:
        TokenResponse with access_token and refresh_token

    Raises:
        HTTPException 400: If username or email already exists
        HTTPException 500: If registration fails
    """
    try:
        # Extract request metadata
        user_agent = request.headers.get("user-agent")
        ip_address = request.client.host if request.client else None

        logger.info(
            "registration_request",
            username=user_data.username,
            email=user_data.email,
            ip_address=ip_address
        )

        # Register user
        tokens = await service.register_user(
            user_data=user_data,
            user_agent=user_agent,
            ip_address=ip_address
        )

        logger.info(
            "registration_successful",
            username=user_data.username
        )

        return tokens

    except ValueError as e:
        logger.warning(
            "registration_validation_error",
            username=user_data.username,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(
            "registration_failed",
            username=user_data.username,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register user"
        )


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def login(
    login_data: UserLogin,
    request: Request,
    service: FromDishka[AuthService]
):
    """
    Login a user.

    Authenticates a user with username and password, returning access and refresh tokens.

    Args:
        login_data: User login credentials (username, password)
        request: FastAPI request object for extracting metadata
        service: AuthService dependency

    Returns:
        TokenResponse with access_token and refresh_token

    Raises:
        HTTPException 401: If credentials are invalid or user is inactive
        HTTPException 500: If login fails
    """
    try:
        # Extract request metadata
        user_agent = request.headers.get("user-agent")
        ip_address = request.client.host if request.client else None

        logger.info(
            "login_request",
            username=login_data.username,
            ip_address=ip_address
        )

        # Login user
        tokens = await service.login_user(
            login_data=login_data,
            user_agent=user_agent,
            ip_address=ip_address
        )

        logger.info(
            "login_endpoint_successful",
            username=login_data.username
        )

        return tokens

    except ValueError as e:
        logger.warning(
            "login_authentication_error",
            username=login_data.username,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except Exception as e:
        logger.error(
            "login_endpoint_failed",
            username=login_data.username,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to login"
        )


@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def get_current_user_info(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    service: FromDishka[AuthService],
    auth_repository: FromDishka[AuthRepository],
    config: FromDishka[Config]
):
    """
    Get current authenticated user information.

    Returns the profile information of the currently authenticated user
    based on the JWT token in the Authorization header.

    Args:
        credentials: HTTP Bearer token credentials
        service: AuthService dependency
        auth_repository: AuthRepository dependency
        config: Application configuration

    Returns:
        UserResponse with user profile information

    Raises:
        HTTPException 401: If token is invalid or expired
        HTTPException 403: If user account is inactive

    Headers:
        Authorization: Bearer <access_token>
    """
    token = credentials.credentials

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

    # Fetch user from database
    user = await auth_repository.get_user_by_id(int(user_id))

    if user is None:
        logger.warning("user_not_found", user_id=user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if user is active
    if not user.is_active:
        logger.warning("user_inactive", user_id=user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account"
        )

    logger.info(
        "get_current_user_request",
        user_id=user.id,
        username=user.username
    )

    return service.get_user_response(user)
