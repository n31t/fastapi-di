"""
Authentication API endpoints.
"""

from typing import Annotated, Optional

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from src.api.v1.schemas.user import UserRegister, UserLogin, UserResponse
from src.core.config import config
from src.core.exceptions import UnauthorizedError
from src.core.logging import get_logger
from src.dtos import UserRegisterDTO, UserLoginDTO, AuthenticatedUserDTO
from src.services.auth_service import AuthService
from src.services.shared.auth_helpers import get_authenticated_user_dependency

logger = get_logger(__name__)

router = APIRouter(
    prefix="/auth",
    route_class=DishkaRoute,
)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserRegister,
    request: Request,
    response: Response,
    service: FromDishka[AuthService],
):
    """Register a new user."""
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None

    logger.info(
        "registration_request",
        username=user_data.username,
        email=user_data.email,
        ip_address=ip_address
    )

    user_dto = UserRegisterDTO(**user_data.model_dump())
    tokens = await service.register_user(
        user_data=user_dto,
        user_agent=user_agent,
        ip_address=ip_address
    )

    response.set_cookie(
        key="access_token",
        value=tokens.access_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=config.access_token_expire_minutes * 60,
        path="/"
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens.refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=config.refresh_token_expire_days * 24 * 60 * 60,
        path="/"
    )

    return {"message": "Registration successful"}


@router.post("/login", summary="Login a user", description="Authenticates a user and sets authentication cookies.", status_code=status.HTTP_200_OK)
async def login(
    login_data: UserLogin,
    request: Request,
    response: Response,
    service: FromDishka[AuthService],
):
    """Login user and set cookies."""
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None

    logger.info("login_request", username=login_data.username, ip_address=ip_address)

    payload = UserLoginDTO(**login_data.model_dump())
    tokens = await service.login_user(
        login_data=payload,
        user_agent=user_agent,
        ip_address=ip_address
    )

    response.set_cookie(
        key="access_token",
        value=tokens.access_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=config.access_token_expire_minutes * 60,
        path="/"
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens.refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=config.refresh_token_expire_days * 24 * 60 * 60,
        path="/"
    )

    return {"message": "Login successful"}


@router.post("/refresh", summary="Refresh access token", description="Refreshes the access token using a refresh token from cookies.", status_code=status.HTTP_200_OK)
async def refresh_token(
    request: Request,
    response: Response,
    service: FromDishka[AuthService],
    refresh_token: Annotated[Optional[str], Cookie()] = None,
):
    """Refresh access token using refresh token from cookie."""
    if not refresh_token:
        raise UnauthorizedError("Refresh token missing")

    # Extract request metadata
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None

    logger.info("refresh_token_request", ip_address=ip_address)

    tokens = await service.refresh_token(
        refresh_token=refresh_token,
        user_agent=user_agent,
        ip_address=ip_address
    )

    response.set_cookie(
        key="access_token",
        value=tokens.access_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=config.access_token_expire_minutes * 60,
        path="/"
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens.refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=config.refresh_token_expire_days * 24 * 60 * 60,
        path="/"
    )

    return {"message": "Token refreshed"}


@router.post("/logout", summary="Logout user", description="Clears authentication cookies.", status_code=status.HTTP_200_OK)
async def logout(response: Response):
    """Logout user by clearing cookies."""
    response.delete_cookie(key="access_token", httponly=True, secure=True, samesite="none", path="/")
    response.delete_cookie(key="refresh_token", httponly=True, secure=True, samesite="none", path="/")
    return {"message": "Logout successful"}


@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def get_current_user_info(
    user: Annotated[AuthenticatedUserDTO, Depends(get_authenticated_user_dependency)],
):
    """Get current authenticated user information."""
    logger.info("get_current_user_request", user_id=user.id, username=user.username)
    return user


@router.get("/profile", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def get_profile(
    user: Annotated[AuthenticatedUserDTO, Depends(get_authenticated_user_dependency)],
):
    """Get current user profile."""
    logger.info("get_profile_request", user_id=user.id)
    return user
