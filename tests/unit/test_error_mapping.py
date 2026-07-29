"""Tests for IntegrityError → domain error mapping."""

from sqlalchemy.exc import IntegrityError

from src.core.exceptions import ConflictError, EmailTakenError, UsernameTakenError
from src.repositories.error_mapping import map_integrity_error


class FakeUniqueViolation(Exception):
    """Stands in for asyncpg.exceptions.UniqueViolationError."""

    def __init__(self, constraint_name: str | None):
        self.constraint_name = constraint_name


def make_integrity_error(
    constraint_name: str | None = None, orig_text: str = "duplicate key"
) -> IntegrityError:
    # SQLAlchemy's asyncpg adapter wraps the driver error: the constraint name
    # lives at exc.orig.__cause__.constraint_name, not on exc.orig itself.
    orig = Exception(orig_text)
    if constraint_name is not None:
        orig.__cause__ = FakeUniqueViolation(constraint_name)
    return IntegrityError("INSERT INTO users ...", {}, orig)


def test_maps_username_index():
    err = map_integrity_error(make_integrity_error("ix_users_username"))
    assert isinstance(err, UsernameTakenError)


def test_maps_email_index():
    err = map_integrity_error(make_integrity_error("ix_users_email"))
    assert isinstance(err, EmailTakenError)


def test_unknown_constraint_falls_back_to_generic_conflict():
    err = map_integrity_error(make_integrity_error("some_other_constraint"))
    assert type(err) is ConflictError


def test_string_fallback_when_no_constraint_attr():
    err = map_integrity_error(
        make_integrity_error(None, 'duplicate key value violates "ix_users_email"')
    )
    assert isinstance(err, EmailTakenError)


def test_no_signal_at_all_returns_generic_conflict():
    err = map_integrity_error(make_integrity_error(None, "something opaque"))
    assert type(err) is ConflictError
