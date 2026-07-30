from pydantic import EmailStr, Field

from src.core.schemas import ResponseModel, StrictRequestModel
from src.core.types import Password, Username


class UserRegister(StrictRequestModel):
    """User registration payload."""

    username: Username
    email: EmailStr
    password: Password


class UserLogin(StrictRequestModel):
    """User login payload. Deliberately loose: wrong credentials are a 401, never a 422."""

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserResponse(ResponseModel):
    """User response model."""

    id: str  # ULID
    username: str
    email: EmailStr
    is_active: bool
