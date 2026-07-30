"""Tests for shared API schema base models."""

import pytest
from pydantic import ValidationError

from src.core.schemas import ResponseModel, StrictRequestModel


class StrictChild(StrictRequestModel):
    name: str


class ResponseChild(ResponseModel):
    id: str
    name: str


def test_strict_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        StrictChild(name="ok", surprise="nope")


def test_strict_request_accepts_known_fields():
    assert StrictChild(name="ok").name == "ok"


def test_response_model_builds_from_attributes():
    class Obj:
        id = "01H"
        name = "john"

    m = ResponseChild.model_validate(Obj())
    assert m.id == "01H"
    assert m.name == "john"
