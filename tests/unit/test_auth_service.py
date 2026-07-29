"""AuthService failure-mode tests with mocked repository."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.config import config
from src.core.exceptions import (
    EmailTakenError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
    TokenExpiredError,
    UsernameTakenError,
)
from src.core.security import hash_password
from src.dtos import UserLoginDTO, UserRegisterDTO
from src.services.auth_service import AuthService


def make_user(**overrides):
    defaults = dict(
        id="01HUSER",
        username="john",
        email="john@example.com",
        hashed_password=hash_password("Secure123"),
        is_active=True,
    )
    return SimpleNamespace(**{**defaults, **overrides})


def make_token_record(**overrides):
    defaults = dict(
        user_id="01HUSER",
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    return SimpleNamespace(**{**defaults, **overrides})


@pytest.fixture
def repo():
    r = AsyncMock()
    r.get_user_by_username.return_value = None
    r.get_user_by_email.return_value = None
    return r


@pytest.fixture
def service(repo):
    return AuthService(auth_repository=repo, config=config)


REGISTER_DTO = UserRegisterDTO(username="john", email="john@example.com", password="Secure123")
LOGIN_DTO = UserLoginDTO(username="john", password="Secure123")


async def test_register_duplicate_username(service, repo):
    repo.get_user_by_username.return_value = make_user()
    with pytest.raises(UsernameTakenError):
        await service.register_user(REGISTER_DTO)


async def test_register_duplicate_email(service, repo):
    repo.get_user_by_email.return_value = make_user()
    with pytest.raises(EmailTakenError):
        await service.register_user(REGISTER_DTO)


async def test_login_unknown_user(service, repo):
    with pytest.raises(InvalidCredentialsError):
        await service.login_user(LOGIN_DTO)


async def test_login_wrong_password(service, repo):
    repo.get_user_by_username.return_value = make_user()
    with pytest.raises(InvalidCredentialsError):
        await service.login_user(UserLoginDTO(username="john", password="Wrong456x"))


async def test_login_inactive_user(service, repo):
    repo.get_user_by_username.return_value = make_user(is_active=False)
    with pytest.raises(InactiveUserError):
        await service.login_user(LOGIN_DTO)


async def test_refresh_unknown_token(service, repo):
    repo.get_refresh_token.return_value = None
    with pytest.raises(InvalidTokenError):
        await service.refresh_token("nope")


async def test_refresh_revoked_token(service, repo):
    repo.get_refresh_token.return_value = make_token_record(is_revoked=True)
    with pytest.raises(InvalidTokenError):
        await service.refresh_token("tok")


async def test_refresh_expired_token(service, repo):
    repo.get_refresh_token.return_value = make_token_record(
        expires_at=datetime.now(timezone.utc) - timedelta(days=1)
    )
    with pytest.raises(TokenExpiredError):
        await service.refresh_token("tok")


async def test_refresh_vanished_user_is_401_not_404(service, repo):
    repo.get_refresh_token.return_value = make_token_record()
    repo.get_user_by_id.return_value = None
    with pytest.raises(InvalidTokenError):
        await service.refresh_token("tok")


async def test_refresh_inactive_user(service, repo):
    repo.get_refresh_token.return_value = make_token_record()
    repo.get_user_by_id.return_value = make_user(is_active=False)
    with pytest.raises(InactiveUserError):
        await service.refresh_token("tok")
