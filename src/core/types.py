"""Shared Annotated types for boundary schema validation. Format rules ONLY —
anything needing DB or tenant context is a dependency or service rule, not a type."""
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

from src.core.validators import validate_password_complexity, validate_utf8_max_72_bytes

Username = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_-]+$",
        strip_whitespace=True,
    ),
]

Password = Annotated[
    str,
    Field(min_length=8, max_length=72),
    AfterValidator(validate_utf8_max_72_bytes),
    AfterValidator(validate_password_complexity),
]
