"""Reusable plain validator functions. Wrapped by Annotated types in core/types.py."""
import re


def validate_utf8_max_72_bytes(v: str) -> str:
    # bcrypt's limit is 72 BYTES, not chars; multibyte UTF-8 can exceed it
    # even when max_length=72 passes. bcrypt 5.x raises on longer input.
    if len(v.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return v


def validate_password_complexity(v: str) -> str:
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain at least one digit")
    return v
