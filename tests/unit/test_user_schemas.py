"""Tests for auth request/response schemas."""

import pytest
from pydantic import ValidationError

from src.api.v1.schemas.user import UserLogin, UserRegister, UserResponse


def test_register_valid():
    m = UserRegister(username="john", email="john@example.com", password="Secure123")
    assert m.username == "john"


def test_register_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        UserRegister(
            username="john", email="john@example.com", password="Secure123", extra="x"
        )


def test_register_rejects_weak_password():
    with pytest.raises(ValidationError):
        UserRegister(username="john", email="john@example.com", password="alllower1")


def test_login_allows_any_nonempty_credentials():
    # Login must NOT enforce the registration policy: wrong creds are a 401,
    # not a 422, and a policy change must not lock out existing users.
    m = UserLogin(username="ab", password="x")
    assert m.username == "ab"


def test_login_rejects_empty_fields():
    with pytest.raises(ValidationError):
        UserLogin(username="", password="x")
    with pytest.raises(ValidationError):
        UserLogin(username="ab", password="")


def test_login_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        UserLogin(username="ab", password="x", extra="y")


def test_user_response_from_attributes():
    class Obj:
        id = "01H"
        username = "john"
        email = "john@example.com"
        is_active = True

    m = UserResponse.model_validate(Obj())
    assert m.id == "01H"


def test_token_response_removed():
    with pytest.raises(ImportError):
        from src.api.v1.schemas.user import TokenResponse  # noqa: F401
