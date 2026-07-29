"""Domain exception hierarchy. Raised by services/repositories, translated by API handlers."""


class AppError(Exception):
    """Base application error."""

    code: str = "app_error"  # stable, machine-readable, part of the API contract
    status_code: int = 500
    title: str = "Internal Server Error"
    headers: dict[str, str] | None = None  # e.g. auth challenge, emitted by the handler

    def __init__(self, message: str | None = None, **context: object) -> None:
        self.message = message or self.title
        self.context = context  # extra k/v for logging only, never sent to clients
        super().__init__(self.message)


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404
    title = "Not Found"


class ConflictError(AppError):
    code = "conflict"
    status_code = 409
    title = "Conflict"


class UnauthorizedError(AppError):
    code = "unauthorized"
    status_code = 401
    title = "Unauthorized"
    headers = {"WWW-Authenticate": "Bearer"}  # RFC 9110 §11.6.1: 401 MUST carry a challenge


class PermissionDeniedError(AppError):
    code = "permission_denied"
    status_code = 403
    title = "Forbidden"


class UsernameTakenError(ConflictError):
    code = "username_taken"


class EmailTakenError(ConflictError):
    code = "email_taken"


class InvalidCredentialsError(UnauthorizedError):
    code = "invalid_credentials"


class InvalidTokenError(UnauthorizedError):
    code = "invalid_token"


class TokenExpiredError(UnauthorizedError):
    code = "token_expired"


class InactiveUserError(PermissionDeniedError):
    code = "inactive_user"
