"""Tests for shared Annotated validation types."""

import pytest
from pydantic import BaseModel, ValidationError

from src.core.types import Password, Username


class UsernameModel(BaseModel):
    v: Username


class PasswordModel(BaseModel):
    v: Password


def test_username_valid():
    assert UsernameModel(v="john_doe-1").v == "john_doe-1"


def test_username_strips_whitespace():
    assert UsernameModel(v="  john  ").v == "john"


@pytest.mark.parametrize("bad", ["ab", "a" * 51, "has space", "bad!char"])
def test_username_invalid(bad):
    with pytest.raises(ValidationError):
        UsernameModel(v=bad)


def test_password_valid():
    assert PasswordModel(v="Secure123").v == "Secure123"


@pytest.mark.parametrize(
    "bad",
    [
        "Short1A",        # 7 chars: too short
        "alllower123",    # no uppercase
        "ALLUPPER123",    # no lowercase
        "NoDigitsHere",   # no digit
        "A1" + "a" * 71,  # 73 chars: over max_length
    ],
)
def test_password_invalid(bad):
    with pytest.raises(ValidationError):
        PasswordModel(v=bad)


def test_password_multibyte_over_72_bytes_rejected():
    # 24 chars of 'é' (2 bytes each) + 'A1a...' padding: <=72 CHARS but >72 BYTES.
    candidate = "A1a" + "é" * 36  # 39 chars, 3 + 72 = 75 bytes
    assert len(candidate) <= 72
    assert len(candidate.encode("utf-8")) > 72
    with pytest.raises(ValidationError, match="72 bytes"):
        PasswordModel(v=candidate)


def test_password_exactly_72_bytes_accepted():
    candidate = "A1" + "a" * 70  # 72 ASCII chars = 72 bytes
    assert PasswordModel(v=candidate).v == candidate
