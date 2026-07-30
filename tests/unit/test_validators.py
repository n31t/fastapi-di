"""Tests for plain validator functions in core/validators."""

import pytest

from src.core.validators import validate_password_complexity, validate_utf8_max_72_bytes


def test_72_ascii_bytes_accepted():
    v = "a" * 72
    assert validate_utf8_max_72_bytes(v) == v


def test_73_ascii_bytes_rejected():
    with pytest.raises(ValueError, match="72 bytes"):
        validate_utf8_max_72_bytes("a" * 73)


def test_multibyte_over_72_bytes_rejected():
    # 39 chars but 75 UTF-8 bytes: char-count checks pass, byte check must not.
    candidate = "A1a" + "é" * 36
    assert len(candidate) <= 72
    assert len(candidate.encode("utf-8")) > 72
    with pytest.raises(ValueError, match="72 bytes"):
        validate_utf8_max_72_bytes(candidate)


def test_complexity_valid_passes():
    assert validate_password_complexity("Secure123") == "Secure123"


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        ("alllower123", "uppercase"),
        ("ALLUPPER123", "lowercase"),
        ("NoDigitsHere", "digit"),
    ],
)
def test_complexity_missing_class_rejected(bad, message):
    with pytest.raises(ValueError, match=message):
        validate_password_complexity(bad)
