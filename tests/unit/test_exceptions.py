"""Tests for the domain exception hierarchy."""

from src.core.exceptions import (
    AppError,
    ConflictError,
    EmailTakenError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
    NotFoundError,
    PermissionDeniedError,
    TokenExpiredError,
    UnauthorizedError,
    UsernameTakenError,
)


def test_app_error_defaults():
    err = AppError()
    assert err.code == "app_error"
    assert err.status_code == 500
    assert err.title == "Internal Server Error"
    assert err.headers is None
    assert err.message == "Internal Server Error"
    assert err.context == {}


def test_app_error_message_and_context():
    err = AppError("boom", user_id="u1")
    assert err.message == "boom"
    assert str(err) == "boom"
    assert err.context == {"user_id": "u1"}


def test_base_classes():
    assert (NotFoundError.code, NotFoundError.status_code) == ("not_found", 404)
    assert (ConflictError.code, ConflictError.status_code) == ("conflict", 409)
    assert (UnauthorizedError.code, UnauthorizedError.status_code) == ("unauthorized", 401)
    assert (PermissionDeniedError.code, PermissionDeniedError.status_code) == ("permission_denied", 403)


def test_unauthorized_carries_www_authenticate_challenge():
    assert UnauthorizedError.headers == {"WWW-Authenticate": "Bearer"}
    assert InvalidCredentialsError().headers == {"WWW-Authenticate": "Bearer"}


def test_auth_catalog():
    assert (UsernameTakenError.code, UsernameTakenError.status_code) == ("username_taken", 409)
    assert (EmailTakenError.code, EmailTakenError.status_code) == ("email_taken", 409)
    assert (InvalidCredentialsError.code, InvalidCredentialsError.status_code) == ("invalid_credentials", 401)
    assert (InvalidTokenError.code, InvalidTokenError.status_code) == ("invalid_token", 401)
    assert (TokenExpiredError.code, TokenExpiredError.status_code) == ("token_expired", 401)
    assert (InactiveUserError.code, InactiveUserError.status_code) == ("inactive_user", 403)


def test_catch_by_base_class():
    assert isinstance(UsernameTakenError(), ConflictError)
    assert isinstance(TokenExpiredError(), UnauthorizedError)
    assert isinstance(InactiveUserError(), PermissionDeniedError)
    assert isinstance(InactiveUserError(), AppError)
