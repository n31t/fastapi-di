"""Shared Annotated types for boundary schema validation."""

import re
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

Username = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_-]+$",
        strip_whitespace=True,
    ),
]


def _max_72_bytes(v: str) -> str:
    # bcrypt's limit is 72 BYTES, not chars; multibyte UTF-8 can exceed it
    # even when max_length=72 passes. bcrypt 5.x raises on longer input.
    if len(v.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return v


def _check_complexity(v: str) -> str:
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain at least one digit")
    return v


Password = Annotated[
    str,
    Field(min_length=8, max_length=72),
    AfterValidator(_max_72_bytes),
    AfterValidator(_check_complexity),
]
