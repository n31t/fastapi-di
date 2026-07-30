"""Map database integrity violations to domain errors."""

from sqlalchemy.exc import IntegrityError

from src.core.exceptions import ConflictError, EmailTakenError, UsernameTakenError

_CONSTRAINT_MAP: dict[str, type[ConflictError]] = {
    "ix_users_username": UsernameTakenError,
    "ix_users_email": EmailTakenError,
}


def map_integrity_error(exc: IntegrityError) -> ConflictError:
    """Return the domain error for a uniqueness violation."""
    constraint = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
    if constraint is None:
        text = str(exc.orig)
        constraint = next((name for name in _CONSTRAINT_MAP if name in text), None)
    error_cls = _CONSTRAINT_MAP.get(constraint, ConflictError)
    return error_cls()
