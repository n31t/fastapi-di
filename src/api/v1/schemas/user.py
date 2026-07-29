from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.core.types import Password, Username


class UserRegister(BaseModel):
    """User registration payload."""

    model_config = ConfigDict(extra="forbid")

    username: Username
    email: EmailStr
    password: Password


class UserLogin(BaseModel):
    """User login payload. Deliberately loose: wrong credentials are a 401, never a 422."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserResponse(BaseModel):
    """User response model."""

    model_config = ConfigDict(from_attributes=True)

    id: str  # ULID
    username: str
    email: EmailStr
    is_active: bool
